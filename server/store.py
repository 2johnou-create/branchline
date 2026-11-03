"""Single-node SQLite persistence with atomic quotas and encrypted content."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import uuid

from cryptography.fernet import Fernet

ACTIVE = ("queued", "building", "preparing", "running", "reporting")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class QuotaExceeded(Exception):
    pass


class Store:
    def __init__(self, filename, key):
        self.filename = filename
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
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
            """)

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
                db.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (wid, name, token_hash(token), credits))
        return wid, token

    def workspace(self, token):
        with self.connection() as db:
            row = db.execute("SELECT id,name,credits FROM workspaces WHERE token_hash=?", (token_hash(token),)).fetchone()
        return dict(row) if row else None

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
            row = db.execute("SELECT credits FROM workspaces WHERE id=?", (wid,)).fetchone()
            active = db.execute(f"SELECT count(*) FROM runs WHERE workspace_id=? AND status IN ({placeholders})", (wid, *ACTIVE)).fetchone()[0]
            total = db.execute(f"SELECT count(*) FROM runs WHERE status IN ({placeholders})", ACTIVE).fetchone()[0]
            if active >= max_active or total >= max_global:
                raise QuotaExceeded("The active simulation limit has been reached. Wait for a run to finish.")
            if not row or row[0] < cost:
                raise QuotaExceeded("This workspace has insufficient credits for this run.")
            db.execute("UPDATE workspaces SET credits=credits-? WHERE id=?", (cost, wid))
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (rid, wid, "queued", "Queued", 0, now, now, expires, cost, self.encrypt(private)))
        return rid

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

    def update(self, wid, rid, *, status=None, stage=None, progress=None, upstream=None, result=None, error=None):
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM runs WHERE workspace_id=? AND id=?", (wid, rid)).fetchone()
            if not row:
                return
            private = self.decrypt(row["private"])
            if upstream:
                private["upstream"].update(upstream)
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

