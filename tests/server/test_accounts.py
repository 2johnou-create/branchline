from dataclasses import replace
import re
import time
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from server.app import create_app
from server.auth import hash_password, verify_password
from server.config import Settings
from server.store import Store
from tests.server.test_gateway import FakeEngine, PAYLOAD

PASSWORD = "Correct horse battery staple 2026"
NEW_PASSWORD = "A completely different private phrase 2026"
ORIGIN = "https://branchline.example"


class Mailer:
    ready = True
    def __init__(self):
        self.messages = []
    def send(self, email, subject, body):
        self.messages.append((email, subject, body))


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / "accounts.db"), encryption_key=Fernet.generate_key().decode(),
                    public_url=ORIGIN, origins=(ORIGIN,), require_email_verification=False,
                    static_directory=str(tmp_path / "no-static"), poll_interval=.001)


@pytest.fixture
def client(settings):
    app = create_app(settings, engine=FakeEngine(), launch_jobs=False, mailer=Mailer())
    with TestClient(app, base_url=ORIGIN) as client:
        yield app, client


def origin(csrf=None):
    return {"Origin": ORIGIN, **({"X-CSRF-Token": csrf} if csrf else {})}


def register(client, email="person@example.com"):
    return client.post("/api/v1/auth/register", headers=origin(), json={"name": "A person", "email": email, "password": PASSWORD})


def token_from(message, kind):
    return re.search(r"/#" + kind + r"=([A-Za-z0-9_-]+)", message[2]).group(1)


def test_default_signup_is_disabled_without_email_delivery(settings):
    app = create_app(replace(settings, require_email_verification=True), engine=FakeEngine(), launch_jobs=False)
    with TestClient(app, base_url=ORIGIN) as client:
        config = client.get("/api/v1/config").json()
        assert config["auth"]["signup_enabled"] is False
        assert config["auth"]["email_delivery_ready"] is False
        assert config["billing"]["enabled"] is False
        response = register(client)
        assert response.status_code == 503
        assert app.state.auth.user(email="person@example.com") is None


def test_pilot_registration_rejects_unapproved_addresses_without_storing_or_sending(settings):
    mailer = Mailer()
    app = create_app(replace(settings, require_email_verification=True,
                             signup_allowed_emails=("owner@example.com",)),
                     engine=FakeEngine(), launch_jobs=False, mailer=mailer)
    with TestClient(app, base_url=ORIGIN) as client:
        config = client.get("/api/v1/config")
        assert config.json()["auth"]["signup_restricted"] is True
        assert "owner@example.com" not in config.text
        assert register(client, "visitor@example.com").status_code == 403
        assert app.state.auth.user(email="visitor@example.com") is None
        assert mailer.messages == []
        with app.state.store.connection() as db:
            assert db.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 0
        assert register(client, "OWNER@EXAMPLE.COM").status_code == 202
        assert mailer.messages[0][0] == "owner@example.com"


def test_signup_creates_isolated_free_account_and_secure_session(client):
    app, client = client
    response = register(client)
    assert response.status_code == 201
    result = response.json()
    assert result["user"]["email_verified"] is True
    assert result["credits_remaining"] == 4
    assert "password_hash" not in response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert cookie.startswith("__Host-branchline_session=")
    user = app.state.auth.user(email="person@example.com")
    assert user["password_hash"].startswith("scrypt$131072$8$1$")
    assert PASSWORD not in user["password_hash"]
    me = client.get("/api/v1/auth/me").json()
    assert me["user"]["id"] == result["user"]["id"]
    assert me["csrf_token"] == result["csrf_token"]
    with app.state.store.connection() as db:
        sessions = db.execute("SELECT token_hash FROM sessions").fetchall()
    raw = client.cookies.get(app.state.auth.cookie_name)
    assert all(raw != row[0] for row in sessions)
    quote = client.post("/api/v1/runs/quote", headers=origin(result["csrf_token"]), json={"rounds": 5})
    assert {k: quote.json()[k] for k in ("credits_required", "credits_remaining", "sufficient")} == {"credits_required": 6, "credits_remaining": 4, "sufficient": False}
    assert client.post("/api/v1/runs", headers=origin(result["csrf_token"]), json=PAYLOAD).status_code == 429


def test_cookie_mutations_require_session_bound_csrf_and_exact_origin(client):
    _, client = client
    result = register(client).json()
    assert client.post("/api/v1/runs/quote", headers=origin(), json={"rounds": 2}).status_code == 403
    assert client.post("/api/v1/runs/quote", headers={"Origin": "https://attacker.example", "X-CSRF-Token": result["csrf_token"]}, json={"rounds": 2}).status_code == 403
    assert client.post("/api/v1/runs/quote", headers=origin("invalid"), json={"rounds": 2}).status_code == 403
    assert client.post("/api/v1/auth/login", headers={"Origin": "https://attacker.example"}, json={"email": "person@example.com", "password": PASSWORD}).status_code == 403


def test_login_logout_and_wrong_password(client):
    _, client = client
    result = register(client).json()
    assert client.post("/api/v1/auth/logout", json={}, headers=origin(result["csrf_token"])).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/login", headers=origin(), json={"email": "person@example.com", "password": "incorrect"}).status_code == 401
    response = client.post("/api/v1/auth/login", headers=origin(), json={"email": "PERSON@EXAMPLE.COM", "password": PASSWORD})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_verification_mail_is_real_and_token_single_use(settings):
    mailer = Mailer()
    app = create_app(replace(settings, require_email_verification=True), engine=FakeEngine(), launch_jobs=False, mailer=mailer)
    with TestClient(app, base_url=ORIGIN) as client:
        response = register(client)
        assert response.status_code == 202
        assert response.json()["status"] == "verification_required"
        assert not client.cookies
        assert app.state.auth.user(email="person@example.com")["credits"] == 0
        assert len(mailer.messages) == 1
        raw = token_from(mailer.messages[0], "verify")
        assert raw not in response.text
        assert client.post("/api/v1/auth/login", headers=origin(), json={"email": "person@example.com", "password": PASSWORD}).status_code == 403
        verified = client.post("/api/v1/auth/verify", headers=origin(), json={"token": raw})
        assert verified.status_code == 200
        assert verified.json()["user"]["email_verified"] is True
        assert verified.json()["credits_remaining"] == 4
        assert client.post("/api/v1/auth/verify", headers=origin(), json={"token": raw}).status_code == 400


def test_expired_verification_and_failed_delivery_are_not_claimed_success(settings):
    class BrokenMailer(Mailer):
        def send(self, *args):
            raise RuntimeError("secret SMTP credentials must never reach API")
    app = create_app(replace(settings, require_email_verification=True), engine=FakeEngine(), launch_jobs=False, mailer=BrokenMailer())
    with TestClient(app, base_url=ORIGIN) as client:
        response = register(client)
        assert response.status_code == 503
        assert "secret SMTP" not in response.text
        assert app.state.auth.user(email="person@example.com")["email_verified"] == 0
    mailer = Mailer()
    app = create_app(replace(settings, require_email_verification=True), engine=FakeEngine(), launch_jobs=False, mailer=mailer)
    with TestClient(app, base_url=ORIGIN) as client:
        register(client, "another@example.com")
        raw = token_from(mailer.messages[0], "verify")
        with app.state.store.connection(write=True) as db:
            db.execute("UPDATE auth_tokens SET expires_at=0")
        assert client.post("/api/v1/auth/verify", headers=origin(), json={"token": raw}).status_code == 400


def test_password_reset_revokes_sessions_and_does_not_enumerate_users(client):
    app, client = client
    register(client)
    response = client.post("/api/v1/auth/forgot-password", headers=origin(), json={"email": "person@example.com"})
    missing = client.post("/api/v1/auth/forgot-password", headers=origin(), json={"email": "missing@example.com"})
    assert response.status_code == missing.status_code == 202
    assert response.json() == missing.json()
    raw = token_from(app.state.auth.mailer.messages[0], "reset")
    reset = client.post("/api/v1/auth/reset-password", headers=origin(), json={"token": raw, "password": NEW_PASSWORD})
    assert reset.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/reset-password", headers=origin(), json={"token": raw, "password": NEW_PASSWORD}).status_code == 400
    assert client.post("/api/v1/auth/login", headers=origin(), json={"email": "person@example.com", "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", headers=origin(), json={"email": "person@example.com", "password": NEW_PASSWORD}).status_code == 200


def test_accounts_cannot_access_each_others_runs_and_deletion_erases_content(client):
    app, client = client
    first = register(client).json()
    wid = first["workspace"]["id"]
    with app.state.store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=30 WHERE id=?", (wid,))
    rid = client.post("/api/v1/runs", headers=origin(first["csrf_token"]), json=PAYLOAD).json()["id"]
    assert client.request("DELETE", "/api/v1/account", headers=origin(first["csrf_token"]), json={"password": PASSWORD}).status_code == 409
    app.state.store.update(wid, rid, status="completed", upstream={"project_id": "private-project"}, result={"markdown": "Private report"})
    exported = client.get("/api/v1/account/export").json()
    assert exported["runs"][0]["context"] == PAYLOAD["context"]
    assert "password_hash" not in str(exported) and "upstream" not in exported["runs"][0]
    client.post("/api/v1/auth/logout", headers=origin(first["csrf_token"]), json={})
    second = register(client, "second@example.com").json()
    assert second["workspace"]["id"] != wid
    assert client.get(f"/api/v1/runs/{rid}").status_code == 404
    client.post("/api/v1/auth/logout", headers=origin(second["csrf_token"]), json={})
    login = client.post("/api/v1/auth/login", headers=origin(), json={"email": "person@example.com", "password": PASSWORD}).json()
    response = client.request("DELETE", "/api/v1/account", headers=origin(login["csrf_token"]), json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["cleanup_pending"] is True
    assert app.state.store.get(wid, rid) is None
    assert app.state.store.cleanup_tasks()[0]["private"]["upstream"]["project_id"] == "private-project"
    assert client.get("/api/v1/auth/me").status_code == 401
    assert app.state.auth.user(email="person@example.com") is None


def test_account_auth_rate_limit_precedes_expensive_hashing(client):
    _, client = client
    assert register(client).status_code == 201
    for i in range(2):
        assert register(client).status_code == 409
    response = register(client)
    assert response.status_code == 429


def test_account_deletion_rolls_back_if_cleanup_mapping_cannot_be_saved(client, monkeypatch):
    app, browser = client
    result = register(browser).json()
    user = app.state.auth.user(email="person@example.com")
    wid = user["workspace_id"]
    with app.state.store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=30 WHERE id=?", (wid,))
    rid = app.state.store.reserve(wid, PAYLOAD, 1, 1)
    app.state.store.update(wid, rid, status="completed", upstream={"project_id": "retain-this-reference"})
    def unavailable_cipher(value):
        raise RuntimeError("Simulated persistence fault")
    monkeypatch.setattr(app.state.store, "encrypt", unavailable_cipher)
    with pytest.raises(RuntimeError, match="persistence fault"):
        app.state.auth.freeze_account(user)
    assert app.state.auth.user(email="person@example.com") is not None
    assert app.state.store.get(wid, rid) is not None
    assert app.state.store.cleanup_tasks() == []


def test_deleted_email_cannot_restart_its_free_allowance(client, monkeypatch):
    app, browser = client
    first = register(browser).json()
    wid = first["workspace"]["id"]
    original_deadline = app.state.store.wallet(wid)["free_next_refresh_at"]
    rid = app.state.store.reserve(wid, {**PAYLOAD, "rounds": 3}, 1, 1)
    app.state.store.update(wid, rid, status="completed")
    assert app.state.store.wallet(wid)["free"] == 0
    deleted = browser.request("DELETE", "/api/v1/account", headers=origin(first["csrf_token"]), json={"password": PASSWORD})
    assert deleted.status_code == 200
    recreated = register(browser).json()
    assert recreated["workspace"]["id"] != wid
    assert recreated["credits_remaining"] == 0
    assert app.state.store.wallet(recreated["workspace"]["id"])["free_next_refresh_at"] == original_deadline


def test_engine_disabled_prevents_credit_reservation(settings):
    app = create_app(replace(settings, engine_enabled=False), engine=FakeEngine(), launch_jobs=False)
    wid, token = app.state.store.provision("Operator", 30)
    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=PAYLOAD, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 503
        assert app.state.store.workspace(token)["credits"] == 30


def test_durable_queue_claims_once_under_concurrency(settings):
    store = Store(settings.database, settings.encryption_key)
    wid, token = store.provision("Queue", 30)
    rid = store.reserve(wid, PAYLOAD, 1, 1)
    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(lambda i: store.claim_next(str(i)), range(8)))
    assert len([row for row in rows if row]) == 1
    assert [row for row in rows if row][0]["id"] == rid
    with store.connection() as db:
        assert db.execute("SELECT attempts FROM job_queue WHERE run_id=?", (rid,)).fetchone()[0] == 1


def test_accepted_unclaimed_queue_survives_restart_without_double_charge(settings):
    store = Store(settings.database, settings.encryption_key)
    wid, token = store.provision("Queued", 30)
    rid = store.reserve(wid, PAYLOAD, 1, 1)
    app = create_app(settings, engine=FakeEngine())
    with TestClient(app) as client:
        for _ in range(100):
            result = client.get(f"/api/v1/runs/{rid}", headers={"Authorization": "Bearer " + token}).json()
            if result["status"] == "completed":
                break
            time.sleep(.01)
        assert result["status"] == "completed"
        assert store.workspace(token)["credits"] == 24
        with store.connection() as db:
            assert db.execute("SELECT attempts FROM job_queue WHERE run_id=?", (rid,)).fetchone()[0] == 1


def test_new_instance_respects_another_workers_unexpired_lease(settings):
    store = Store(settings.database, settings.encryption_key)
    wid, token = store.provision("Rolling deployment", 30)
    rid = store.reserve(wid, PAYLOAD, 1, 1)
    store.claim_next("still-alive-worker")
    store.update(wid, rid, status="running")
    app = create_app(settings, engine=FakeEngine())
    with TestClient(app) as client:
        result = client.get(f"/api/v1/runs/{rid}", headers={"Authorization": "Bearer " + token}).json()
        assert result["status"] == "running"
        assert store.claim_next("other-worker") is None
        assert store.claim_interrupted_jobs("new-worker") == []
        store.finish_job(rid, "wrong-worker")
        with store.connection() as db:
            assert db.execute("SELECT status FROM job_queue WHERE run_id=?", (rid,)).fetchone()[0] == "claimed"
