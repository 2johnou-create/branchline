"""Single-node SQLite persistence with atomic quotas and encrypted content."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from cryptography.fernet import Fernet

ACTIVE = ("queued", "building", "preparing", "running", "reporting")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")
FREE_ALLOWANCE = 4
FREE_INTERVAL_SECONDS = 48 * 3600


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class QuotaExceeded(Exception):
    pass


class Store:
    def __init__(self, filename, key):
        self.filename = filename
        key_bytes = key.encode() if isinstance(key, str) else key
        self.cipher = Fernet(key_bytes)
        self._free_credit_key = hmac.new(base64.urlsafe_b64decode(key_bytes), b"branchline/free-allowance/email-cooldown/v1", hashlib.sha256).digest()
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE, credits INTEGER NOT NULL CHECK(credits>=0));
              CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                credits_reserved INTEGER NOT NULL, private BLOB NOT NULL);
              CREATE INDEX IF NOT EXISTS runs_workspace ON runs(workspace_id, created_at DESC);
              CREATE TABLE IF NOT EXISTS rate_limits (
                workspace_id TEXT PRIMARY KEY, window INTEGER NOT NULL, requests INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS cleanup_tasks (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                run_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, private BLOB NOT NULL);
              CREATE TABLE IF NOT EXISTS job_queue (
                run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                status TEXT NOT NULL, worker_id TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS free_credit_cooldowns (
                email_digest TEXT PRIMARY KEY, next_refresh_at INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS free_credit_cooldowns_expiry ON free_credit_cooldowns(next_refresh_at);
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {r["name"] for r in db.execute("PRAGMA table_info(workspaces)")}
            for name in ("blocked", "subscription_expires_at"):
                if name not in columns:
                    db.execute(f"ALTER TABLE workspaces ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            # Legacy paid-period balances lived in credits. Move them once;
            # ordinary operator grants and purchased credits remain banked.
            if "subscription_credits" not in columns:
                db.execute("ALTER TABLE workspaces ADD COLUMN subscription_credits INTEGER NOT NULL DEFAULT 0 CHECK(subscription_credits>=0)")
                db.execute("UPDATE workspaces SET subscription_credits=credits,credits=0 WHERE subscription_expires_at>0")
            for name in ("free_credits", "free_next_refresh_at"):
                if name not in columns:
                    db.execute(f"ALTER TABLE workspaces ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0 CHECK({name}>=0)")
            db.commit()

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.filename, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value))

    def provision(self, name, credits, workspace_id=None):
        token = "bl_" + secrets.token_urlsafe(36)
        wid = workspace_id or str(uuid.uuid4())
        with self.connection(write=True) as db:
            if workspace_id:
                changed = db.execute("UPDATE workspaces SET name=?, token_hash=?, credits=? WHERE id=?",
                                     (name, token_hash(token), credits, wid)).rowcount
                if not changed:
                    raise ValueError("Workspace does not exist")
            else:
                db.execute("INSERT INTO workspaces(id,name,token_hash,credits) VALUES (?,?,?,?)", (wid, name, token_hash(token), credits))
        return wid, token

    def workspace(self, token):
        with self.connection(write=True) as db:
            row = db.execute("SELECT id,name FROM workspaces WHERE token_hash=? AND blocked=0", (token_hash(token),)).fetchone()
            if not row:
                return None
            wallet = self._wallet(db, row["id"], int(time.time()))
            return {**dict(row), "credits": wallet["total"], "credit_wallet": wallet}

    def _wallet(self, db, wid, now):
        row = db.execute("SELECT * FROM workspaces WHERE id=? AND blocked=0", (wid,)).fetchone()
        if not row:
            return None
        users_exist = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        user = db.execute("SELECT email FROM users WHERE workspace_id=? AND email_verified=1 AND disabled=0", (wid,)).fetchone() if users_exist else None
        eligible = bool(user and isinstance(user["email"], str) and user["email"])
        db.execute("DELETE FROM free_credit_cooldowns WHERE next_refresh_at<=?", (now,))
        digest = hmac.new(self._free_credit_key, user["email"].strip().lower().encode(), hashlib.sha256).hexdigest() if eligible else None
        cooldown = db.execute("SELECT next_refresh_at FROM free_credit_cooldowns WHERE email_digest=?", (digest,)).fetchone() if digest else None
        free = row["free_credits"] if eligible else 0
        next_refresh = row["free_next_refresh_at"]
        if eligible and (not next_refresh or now >= next_refresh):
            if cooldown and cooldown["next_refresh_at"] > now:
                # Deleting/recreating an account cannot reset its email's
                # allowance. This marker contains neither email nor account ID.
                next_refresh, free = cooldown["next_refresh_at"], 0
            else:
                next_refresh = now + FREE_INTERVAL_SECONDS if not next_refresh else next_refresh + ((now - next_refresh) // FREE_INTERVAL_SECONDS + 1) * FREE_INTERVAL_SECONDS
                free = FREE_ALLOWANCE
            db.execute("UPDATE workspaces SET free_credits=?,free_next_refresh_at=? WHERE id=?", (free, next_refresh, wid))
        if eligible and next_refresh > now:
            db.execute("INSERT INTO free_credit_cooldowns(email_digest,next_refresh_at) VALUES(?,?) ON CONFLICT(email_digest) DO UPDATE SET next_refresh_at=MAX(next_refresh_at,excluded.next_refresh_at)", (digest, next_refresh))
        subscription = row["subscription_credits"]
        if row["subscription_expires_at"] > 0 and row["subscription_expires_at"] <= now:
            subscription = 0
            if row["subscription_credits"]:
                db.execute("UPDATE workspaces SET subscription_credits=0 WHERE id=?", (wid,))
        return {"banked": row["credits"], "subscription": subscription, "free": free,
                "total": row["credits"] + subscription + free,
                "free_eligible": eligible, "free_allowance": FREE_ALLOWANCE,
                "free_capacity": FREE_ALLOWANCE, "free_interval_hours": FREE_INTERVAL_SECONDS // 3600,
                "free_next_refresh_at": datetime.fromtimestamp(next_refresh, timezone.utc).isoformat() if eligible and next_refresh else None}

    def wallet(self, wid, *, now=None):
        """Refresh a verified account's capped allowance; banked credits never expire."""
        with self.connection(write=True) as db:
            return self._wallet(db, wid, int(time.time()) if now is None else int(now))

    def allow_request(self, wid, limit):
        import time
        window = int(time.time()) // 60
        with self.connection(write=True) as db:
            db.execute("INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(workspace_id) DO UPDATE SET requests=CASE WHEN window=excluded.window THEN requests+1 ELSE 1 END, window=excluded.window", (wid, window))
            count = db.execute("SELECT requests FROM rate_limits WHERE workspace_id=?", (wid,)).fetchone()[0]
        return count <= limit

    def reserve(self, wid, payload, max_active, max_global):
        rid, now = str(uuid.uuid4()), utcnow()
        cost = 1 + payload["rounds"]
        retention = payload.get("privacy", {}).get("retention_days", 7)
        expires = (datetime.now(timezone.utc) + timedelta(days=retention)).isoformat()
        private = {"request": payload, "upstream": {}, "result": None, "error": None}
        placeholders = ",".join("?" for _ in ACTIVE)
        with self.connection(write=True) as db:
            wallet = self._wallet(db, wid, int(time.time()))
            if wallet is None:
                raise QuotaExceeded("This workspace is unavailable.")
            active = db.execute(f"SELECT count(*) FROM runs WHERE workspace_id=? AND status IN ({placeholders})", (wid, *ACTIVE)).fetchone()[0]
            total = db.execute(f"SELECT count(*) FROM runs WHERE status IN ({placeholders})", ACTIVE).fetchone()[0]
            if active >= max_active or total >= max_global:
                raise QuotaExceeded("The active simulation limit has been reached. Wait for a run to finish.")
            if wallet["total"] < cost:
                raise QuotaExceeded("This workspace has insufficient credits for this run.")
            free_cost = min(cost, wallet["free"])
            subscription_cost = min(cost - free_cost, wallet["subscription"])
            bank_cost = cost - free_cost - subscription_cost
            db.execute("UPDATE workspaces SET free_credits=free_credits-?,subscription_credits=subscription_credits-?,credits=credits-? WHERE id=?", (free_cost, subscription_cost, bank_cost, wid))
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (rid, wid, "queued", "Queued", 0, now, now, expires, cost, self.encrypt(private)))
            db.execute("INSERT INTO job_queue(run_id,status) VALUES (?, 'queued')", (rid,))
        return rid

    def claim_next(self, worker_id, lease_seconds=90):
        import time
        with self.connection(write=True) as db:
            row = db.execute("SELECT runs.* FROM job_queue JOIN runs ON runs.id=job_queue.run_id JOIN workspaces ON workspaces.id=runs.workspace_id WHERE job_queue.status='queued' AND runs.status='queued' AND workspaces.blocked=0 ORDER BY runs.created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE job_queue SET status='claimed',worker_id=?,lease_until=?,attempts=attempts+1 WHERE run_id=? AND status='queued'", (worker_id, int(time.time()) + lease_seconds, row["id"]))
            return self.unpack(row)

    def heartbeat(self, rid, worker_id):
        import time
        with self.connection(write=True) as db:
            return db.execute("UPDATE job_queue SET lease_until=? WHERE run_id=? AND worker_id=? AND status='claimed'", (int(time.time()) + 90, rid, worker_id)).rowcount == 1

    def finish_job(self, rid, worker_id=None):
        with self.connection(write=True) as db:
            if worker_id is not None:
                db.execute("UPDATE job_queue SET status='done',lease_until=0 WHERE run_id=? AND worker_id=?", (rid, worker_id))
            else:
                db.execute("UPDATE job_queue SET status='done',lease_until=0 WHERE run_id=?", (rid,))

    def claim_interrupted_jobs(self, worker_id):
        # A claimed task may have triggered paid upstream work. Never replay it.
        import time
        with self.connection(write=True) as db:
            now = int(time.time())
            rows = db.execute("SELECT runs.* FROM runs LEFT JOIN job_queue ON job_queue.run_id=runs.id WHERE runs.status IN ('queued','building','preparing','running','reporting') AND ((job_queue.status IN ('claimed','recovering') AND job_queue.lease_until<=?) OR job_queue.run_id IS NULL)", (now,)).fetchall()
            for row in rows:
                db.execute("INSERT INTO job_queue(run_id,status,worker_id,lease_until,attempts) VALUES(?,'recovering',?,?,1) ON CONFLICT(run_id) DO UPDATE SET status='recovering',worker_id=excluded.worker_id,lease_until=excluded.lease_until", (row["id"], worker_id, now + 90))
            return [self.unpack(r) for r in rows]

    def get(self, wid, rid):
        with self.connection() as db:
            row = db.execute("SELECT * FROM runs WHERE workspace_id=? AND id=?", (wid, rid)).fetchone()
        return self.unpack(row) if row else None

    def unpack(self, row):
        value = dict(row)
        value["private"] = self.decrypt(value["private"])
        return value

    def list(self, wid):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100", (wid,)).fetchall()
        return [self.unpack(row) for row in rows]

    def update(self, wid, rid, *, status=None, stage=None, progress=None, upstream=None, result=None, error=None, telemetry=None):
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM runs WHERE workspace_id=? AND id=?", (wid, rid)).fetchone()
            if not row:
                return
            private = self.decrypt(row["private"])
            if upstream:
                private["upstream"].update(upstream)
            if telemetry is not None:
                private.setdefault("telemetry", {}).update(telemetry)
            if result is not None:
                private["result"] = result
            if error is not None:
                private["error"] = error
            db.execute("UPDATE runs SET status=?,stage=?,progress=?,updated_at=?,private=? WHERE id=? AND workspace_id=?",
                       (status or row["status"], stage or row["stage"], progress if progress is not None else row["progress"], utcnow(), self.encrypt(private), rid, wid))

    def all_active(self):
        placeholders = ",".join("?" for _ in ACTIVE)
        with self.connection() as db:
            return [self.unpack(r) for r in db.execute(f"SELECT * FROM runs WHERE status IN ({placeholders})", ACTIVE).fetchall()]

    def expired(self):
        placeholders = ",".join("?" for _ in TERMINAL)
        with self.connection() as db:
            return [self.unpack(r) for r in db.execute(f"SELECT * FROM runs WHERE expires_at<? AND status IN ({placeholders}) LIMIT 20", (utcnow(), *TERMINAL)).fetchall()]

    def delete(self, wid, rid):
        with self.connection(write=True) as db:
            db.execute("DELETE FROM runs WHERE workspace_id=? AND id=?", (wid, rid))

    def delete_with_cleanup_ledger(self, wid, rid, refs, receipt):
        pending = any(v == "operator_cleanup_required" for v in receipt.values())
        cid = str(uuid.uuid4()) if pending else None
        with self.connection(write=True) as db:
            if cid:
                existing = db.execute("SELECT id FROM cleanup_tasks WHERE run_id=? AND workspace_id=?", (rid, wid)).fetchone()
                if existing:
                    return existing[0]
                # No customer brief, title, question or generated report survives here.
                db.execute("INSERT INTO cleanup_tasks VALUES (?,?,?,?,?)", (
                    cid, wid, rid, utcnow(), self.encrypt({"upstream": refs, "receipt": receipt})))
            db.execute("DELETE FROM runs WHERE workspace_id=? AND id=?", (wid, rid))
        return cid

    def cleanup_tasks(self):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM cleanup_tasks ORDER BY created_at").fetchall()
        return [self.unpack(r) for r in rows]

    def update_cleanup(self, cid, receipt):
        with self.connection(write=True) as db:
            row = db.execute("SELECT private FROM cleanup_tasks WHERE id=?", (cid,)).fetchone()
            if row:
                private = self.decrypt(row["private"])
                private["receipt"] = receipt
                db.execute("UPDATE cleanup_tasks SET private=? WHERE id=?", (self.encrypt(private), cid))

    def resolve_cleanup(self, cid):
        with self.connection(write=True) as db:
            return db.execute("DELETE FROM cleanup_tasks WHERE id=?", (cid,)).rowcount > 0

