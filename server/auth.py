"""Server-side accounts, password hashing, one-time mail tokens and sessions."""
import asyncio
from email.message import EmailMessage
import hashlib
import hmac
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import ACTIVE, token_hash, utcnow

SESSION_SECONDS = 7 * 24 * 3600


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1,
                            maxmem=256 * 1024 * 1024, dklen=32)
    return "scrypt$131072$8$1$" + salt.hex() + "$" + digest.hex()


def verify_password(password, encoded):
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if (scheme, n, r, p) != ("scrypt", "131072", "8", "1"):
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=256 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


class EmailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", value):
            raise ValueError("Enter a valid email address")
        return value


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=128)


class RegisterBody(EmailBody, PasswordBody):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Enter a name")
        return value.strip()


class LoginBody(EmailBody):
    password: str = Field(min_length=1, max_length=128)


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=256)


class ResetBody(TokenBody, PasswordBody):
    pass


class SMTPMailer:
    def __init__(self, settings):
        self.settings = settings

    @property
    def ready(self):
        s = self.settings
        return bool(s.smtp_host and s.smtp_from and (s.smtp_starttls or s.smtp_port == 465 or s.smtp_host in ("localhost", "127.0.0.1")))

    def send(self, email, subject, body):
        if not self.ready:
            raise RuntimeError("Email delivery is not configured")
        s = self.settings
        message = EmailMessage()
        message["From"] = s.smtp_from
        message["To"] = email
        message["Subject"] = subject
        message.set_content(body)
        if s.smtp_port == 465:
            connection = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
        else:
            connection = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        with connection as client:
            if s.smtp_starttls and s.smtp_port != 465:
                client.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                client.login(s.smtp_username, s.smtp_password)
            client.send_message(message)


class Auth:
    def __init__(self, settings, store, mailer=None):
        self.settings, self.store = settings, store
        self.mailer = mailer or SMTPMailer(settings)
        self.hash_slots = asyncio.Semaphore(2)
        self.secure = settings.public_url.startswith("https://")
        self.cookie_name = "__Host-branchline_session" if self.secure else "branchline_session"
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))
        with store.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT NOT NULL,
                password_hash TEXT NOT NULL, workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id),
                email_verified INTEGER NOT NULL, created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_tokens (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL, expires_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_limits (
                key TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL);
            """)

    @property
    def signup_enabled(self):
        return not self.settings.require_email_verification or self.mailer.ready

    def origin(self, request):
        if request.headers.get("origin") != self.settings.public_url:
            raise HTTPException(403, "This action must originate from the Branchline application")
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            raise HTTPException(403, "Cross-site requests are not allowed")
        if request.method != "DELETE" and request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise HTTPException(415, "Send an application/json request")

    def csrf(self, request):
        self.origin(request)
        raw = request.cookies.get(self.cookie_name, "")
        actual = request.headers.get("x-csrf-token", "")
        if not raw or len(actual) > 256 or not hmac.compare_digest(actual, self.csrf_token(raw)):
            raise HTTPException(403, "Refresh your session before performing this action")

    def csrf_token(self, raw_session):
        return hmac.new(self.settings.encryption_key.encode(), ("branchline-csrf:" + raw_session).encode(), hashlib.sha256).hexdigest()

    def limit(self, request, action, email=None, *, count=12, seconds=60, ip_count=None):
        ip = request.client.host if request.client else "unknown"
        # Hash network identifiers; never trust arbitrary forwarded headers.
        keys = [action + ":ip:" + token_hash(ip)]
        if email:
            keys.append(action + ":email:" + token_hash(email))
        with self.store.connection(write=True) as db:
            window = int(time.time()) // seconds
            for index, key in enumerate(keys):
                db.execute("INSERT INTO auth_limits VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END,window=excluded.window", (key, window))
                allowed = ip_count if index == 0 and ip_count is not None else count
                if db.execute("SELECT count FROM auth_limits WHERE key=?", (key,)).fetchone()[0] > allowed:
                    raise HTTPException(429, "Too many account attempts. Try again later.", headers={"Retry-After": str(seconds)})

    async def password_work(self, function, *args):
        try:
            await asyncio.wait_for(self.hash_slots.acquire(), timeout=.1)
        except TimeoutError as exc:
            raise HTTPException(429, "Account service is busy. Try again shortly.") from exc
        try:
            return await asyncio.to_thread(function, *args)
        finally:
            self.hash_slots.release()

    def user(self, uid=None, email=None):
        with self.store.connection() as db:
            row = db.execute("SELECT users.*,workspaces.name AS workspace_name,CASE WHEN workspaces.subscription_expires_at>0 AND workspaces.subscription_expires_at<=CAST(strftime('%s','now') AS INTEGER) THEN 0 ELSE workspaces.credits END AS credits FROM users JOIN workspaces ON workspaces.id=users.workspace_id WHERE users.disabled=0 AND workspaces.blocked=0 AND " + ("users.id=?" if uid else "users.email=?"), (uid or email,)).fetchone()
        return dict(row) if row else None

    def session_user(self, request):
        raw = request.cookies.get(self.cookie_name, "")
        if not raw or len(raw) > 256:
            return None
        with self.store.connection() as db:
            row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash(raw), int(time.time()))).fetchone()
        user = self.user(uid=row[0]) if row else None
        return user if user and user["email_verified"] else None

    def session(self, user, response):
        raw = secrets.token_urlsafe(48)
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash(raw), user["id"], int(time.time()) + SESSION_SECONDS))
        response.set_cookie(self.cookie_name, raw, max_age=SESSION_SECONDS, httponly=True,
                            secure=self.secure, samesite="strict", path="/")
        return raw

    def logout(self, request, response):
        raw = request.cookies.get(self.cookie_name, "")
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(raw),))
        response.delete_cookie(self.cookie_name, path="/", secure=self.secure, httponly=True, samesite="strict")

    def create_user(self, body, password_hash):
        uid, wid = str(uuid.uuid4()), str(uuid.uuid4())
        try:
            with self.store.connection(write=True) as db:
                db.execute("INSERT INTO workspaces(id,name,token_hash,credits) VALUES(?,?,?,0)", (wid, body.name + "'s workspace", token_hash(secrets.token_urlsafe(48))))
                db.execute("INSERT INTO users(id,email,name,password_hash,workspace_id,email_verified,created_at) VALUES(?,?,?,?,?,?,?)", (uid, body.email, body.name, password_hash, wid, not self.settings.require_email_verification, utcnow()))
        except sqlite3.IntegrityError:
            return None
        return self.user(uid=uid)

    async def send_token(self, user, kind):
        raw = secrets.token_urlsafe(48)
        lifetime = 3600 if kind == "verify" else 1800
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM auth_tokens WHERE user_id=? AND kind=?", (user["id"], kind))
            db.execute("INSERT INTO auth_tokens VALUES(?,?,?,?)", (token_hash(raw), user["id"], kind, int(time.time()) + lifetime))
        link = self.settings.public_url + ("/#verify=" if kind == "verify" else "/#reset=") + raw
        subject = "Verify your Branchline email" if kind == "verify" else "Reset your Branchline password"
        body = f"{subject}\n\nOpen this link:\n{link}\n\nThis link expires in {lifetime // 60} minutes and can be used once. If you did not request this, ignore this email."
        try:
            await asyncio.to_thread(self.mailer.send, user["email"], subject, body)
        except Exception as exc:
            # Never log SMTP credentials or reset/verification links.
            raise HTTPException(503, "Email delivery is temporarily unavailable. Try again later.") from exc

    def consume_token(self, raw, kind, *, password_hash=None):
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT auth_tokens.user_id FROM auth_tokens JOIN users ON users.id=auth_tokens.user_id WHERE token_hash=? AND kind=? AND expires_at>? AND users.disabled=0", (token_hash(raw), kind, int(time.time()))).fetchone()
            if not row:
                raise HTTPException(400, "This link has expired or has already been used")
            uid = row[0]
            db.execute("DELETE FROM auth_tokens WHERE user_id=? AND kind=?", (uid, kind))
            if kind == "verify":
                db.execute("UPDATE users SET email_verified=1 WHERE id=?", (uid,))
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))
                db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        return self.user(uid=uid)

    def token_valid(self, raw, kind):
        with self.store.connection() as db:
            return db.execute("SELECT 1 FROM auth_tokens JOIN users ON users.id=auth_tokens.user_id WHERE token_hash=? AND kind=? AND expires_at>? AND users.disabled=0", (token_hash(raw), kind, int(time.time()))).fetchone() is not None

    def freeze_account(self, user):
        with self.store.connection(write=True) as db:
            placeholders = ",".join("?" for _ in ACTIVE)
            if db.execute(f"SELECT count(*) FROM runs WHERE workspace_id=? AND status IN ({placeholders})", (user["workspace_id"], *ACTIVE)).fetchone()[0]:
                raise HTTPException(409, "Wait for all simulations to finish before deleting your account")
            pending = []
            # Account revocation, content erasure and minimal cleanup mapping
            # are one transaction: a crash cannot erase identity but lose refs.
            for row in db.execute("SELECT id,private FROM runs WHERE workspace_id=?", (user["workspace_id"],)).fetchall():
                refs = self.store.decrypt(row["private"])["upstream"]
                if refs:
                    receipt = {"project_and_cloud_graph": "operator_cleanup_required" if refs.get("project_id") else "not_created",
                               "report": "operator_cleanup_required" if refs.get("report_id") else "not_created",
                               "simulation_artifacts": "operator_cleanup_required" if refs.get("simulation_id") else "not_created"}
                    cid = str(uuid.uuid4())
                    db.execute("INSERT INTO cleanup_tasks VALUES(?,?,?,?,?)", (cid, user["workspace_id"], row["id"], utcnow(), self.store.encrypt({"upstream": refs, "receipt": receipt})))
                    pending.append(cid)
            db.execute("DELETE FROM runs WHERE workspace_id=?", (user["workspace_id"],))
            db.execute("UPDATE workspaces SET blocked=1,credits=0,token_hash=?,name='Deleted account' WHERE id=?", (token_hash(secrets.token_urlsafe(48)), user["workspace_id"]))
            db.execute("UPDATE users SET disabled=1,email=NULL,name='Deleted account',password_hash='' WHERE id=?", (user["id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            db.execute("DELETE FROM auth_tokens WHERE user_id=?", (user["id"],))
            return pending

    def expire_ephemeral(self):
        now = int(time.time())
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
            db.execute("DELETE FROM auth_tokens WHERE expires_at<?", (now,))
            # Rate-limit buckets have no bearing on account identity after 48h.
            db.execute("DELETE FROM auth_limits WHERE ((key LIKE 'register:%' OR key LIKE 'reset:%') AND window<?) OR ((key NOT LIKE 'register:%' AND key NOT LIKE 'reset:%') AND window<?)", ((now - 172800) // 3600, (now - 172800) // 60))
