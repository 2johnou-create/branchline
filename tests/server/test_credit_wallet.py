"""Real SQLite wallet transitions and concurrent free-allowance spending."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

from cryptography.fernet import Fernet
import pytest

from server import store as store_module
from server.store import FREE_INTERVAL_SECONDS, QuotaExceeded, Store


@pytest.fixture
def wallet_fixture(tmp_path, monkeypatch):
    clock = [1_800_000_000]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = Store(str(tmp_path / "wallet.sqlite3"), Fernet.generate_key())
    with store.connection(write=True) as db:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY,workspace_id TEXT UNIQUE,email TEXT,email_verified INTEGER,disabled INTEGER DEFAULT 0)")
    return store, clock


def account(store, banked=0, verified=True, email=None):
    wid, token = store.provision("Wallet test", banked)
    with store.connection(write=True) as db:
        db.execute("INSERT INTO users(id,workspace_id,email,email_verified) VALUES(?,?,?,?)", ("user-" + wid, wid, email or wid + "@example.test", int(verified)))
    return wid, token


def payload(rounds=1):
    return {"title": "Fictional test", "rounds": rounds, "privacy": {"retention_days": 1}}


def test_only_verified_accounts_receive_the_free_allowance(wallet_fixture):
    store, clock = wallet_fixture
    wid, token = account(store, 499994, verified=False)
    operator, _ = store.provision("Operator-only token", 8)
    assert store.wallet(wid)["free"] == 0
    assert store.wallet(operator)["free"] == 0
    with store.connection(write=True) as db:
        db.execute("UPDATE users SET email_verified=1 WHERE workspace_id=?", (wid,))
    wallet = store.wallet(wid)
    assert (wallet["free"], wallet["banked"], wallet["total"]) == (4, 499994, 499998)
    expected = datetime.fromtimestamp(clock[0] + FREE_INTERVAL_SECONDS, timezone.utc).isoformat()
    assert wallet["free_next_refresh_at"] == expected
    assert store.workspace(token)["credits"] == 499998


def test_refresh_is_rolling_capped_and_never_erases_banked_credits(wallet_fixture):
    store, clock = wallet_fixture
    wid, _ = account(store, 499994)
    first = store.wallet(wid)
    store.reserve(wid, payload(2), 100, 100)
    assert store.wallet(wid)["free"] == 1
    clock[0] += FREE_INTERVAL_SECONDS - 1
    assert store.wallet(wid)["free"] == 1
    clock[0] += 1
    assert store.wallet(wid)["free"] == 4
    store.reserve(wid, payload(), 100, 100)
    assert store.wallet(wid)["free"] == 2
    clock[0] += 5 * FREE_INTERVAL_SECONDS + 100
    refreshed = store.wallet(wid)
    assert refreshed["free"] == 4  # missed windows never stack
    assert refreshed["banked"] == 499994
    assert refreshed["free_next_refresh_at"] != first["free_next_refresh_at"]
    assert store.wallet(wid) == refreshed


def test_concurrent_requests_cannot_double_refresh_or_overspend(wallet_fixture):
    store, clock = wallet_fixture
    wid, _ = account(store)
    def attempt(_):
        try:
            return store.reserve(wid, payload(), 100, 100)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(8)))
    assert len([rid for rid in results if rid]) == 2
    assert store.wallet(wid)["total"] == 0
    assert len(store.list(wid)) == 2
    with store.connection() as db:
        row = db.execute("SELECT free_credits,free_next_refresh_at FROM workspaces WHERE id=?", (wid,)).fetchone()
    assert tuple(row) == (0, clock[0] + FREE_INTERVAL_SECONDS)


def test_spending_order_and_subscription_expiry_preserve_bank(wallet_fixture):
    store, clock = wallet_fixture
    wid, _ = account(store, 10)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET subscription_credits=7,subscription_expires_at=? WHERE id=?", (clock[0] + 100, wid))
    store.reserve(wid, payload(5), 100, 100)
    wallet = store.wallet(wid)
    assert (wallet["free"], wallet["subscription"], wallet["banked"]) == (0, 5, 10)
    store.reserve(wid, payload(5), 100, 100)
    wallet = store.wallet(wid)
    assert (wallet["free"], wallet["subscription"], wallet["banked"]) == (0, 0, 9)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET subscription_credits=20 WHERE id=?", (wid,))
    clock[0] += 101
    assert store.wallet(wid)["total"] == 9
    store.reserve(wid, payload(), 100, 100)
    assert store.wallet(wid)["banked"] == 7


def test_legacy_migration_separates_only_subscription_balances_once(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE workspaces(id TEXT PRIMARY KEY,name TEXT,token_hash TEXT UNIQUE,credits INTEGER,blocked INTEGER DEFAULT 0,subscription_expires_at INTEGER DEFAULT 0)")
        db.execute("INSERT INTO workspaces VALUES('owner','Owner','owner-hash',499994,0,0)")
        db.execute("INSERT INTO workspaces VALUES('paid','Paid','paid-hash',12,0,9999999999)")
    key = Fernet.generate_key()
    store = Store(str(path), key)
    assert store.wallet("owner")["banked"] == 499994
    assert (store.wallet("paid")["banked"], store.wallet("paid")["subscription"]) == (0, 12)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=7 WHERE id='paid'")
    reopened = Store(str(path), key)
    assert (reopened.wallet("paid")["banked"], reopened.wallet("paid")["subscription"]) == (7, 12)


def test_telemetry_merges_without_replacing_private_request(wallet_fixture):
    store, _ = wallet_fixture
    wid, _ = account(store)
    rid = store.reserve(wid, payload(), 100, 100)
    store.update(wid, rid, telemetry={"agents_total": 2})
    store.update(wid, rid, telemetry={"current_round": 1, "actions_count": 2})
    private = store.get(wid, rid)["private"]
    assert private["telemetry"] == {"agents_total": 2, "current_round": 1, "actions_count": 2}
    assert private["request"]["title"] == "Fictional test"


def test_same_email_recreation_waits_for_prior_cooldown_without_retaining_email(wallet_fixture):
    store, clock = wallet_fixture
    email = "private-owner@example.test"
    original, _ = account(store, email=email)
    first = store.wallet(original)
    store.reserve(original, payload(3), 100, 100)
    with store.connection(write=True) as db:
        db.execute("UPDATE users SET email=NULL,disabled=1 WHERE workspace_id=?", (original,))
        db.execute("UPDATE workspaces SET blocked=1,free_credits=0 WHERE id=?", (original,))
    recreated, _ = account(store, email=email)
    wallet = store.wallet(recreated)
    assert wallet["free"] == 0
    assert wallet["free_next_refresh_at"] == first["free_next_refresh_at"]
    with store.connection() as db:
        markers = [dict(row) for row in db.execute("SELECT * FROM free_credit_cooldowns")]
    assert len(markers) == 1 and len(markers[0]["email_digest"]) == 64
    assert set(markers[0]) == {"email_digest", "next_refresh_at"}
    assert email not in str(markers) and original not in str(markers)
    clock[0] += FREE_INTERVAL_SECONDS
    assert store.wallet(recreated)["free"] == 4


def test_concurrent_verified_workspaces_cannot_claim_same_email_twice(wallet_fixture):
    store, _ = wallet_fixture
    first, _ = account(store, email="shared@example.test")
    second, _ = account(store, email="shared@example.test")
    with ThreadPoolExecutor(max_workers=2) as executor:
        wallets = list(executor.map(store.wallet, [first, second]))
    assert sorted(wallet["free"] for wallet in wallets) == [0, 4]


def test_expired_email_marker_is_purged_even_when_deleted_account_never_returns(wallet_fixture):
    store, clock = wallet_fixture
    first, _ = account(store)
    store.wallet(first)
    clock[0] += FREE_INTERVAL_SECONDS
    operator, _ = store.provision("No email", 0)
    store.wallet(operator)
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM free_credit_cooldowns").fetchone()[0] == 0
