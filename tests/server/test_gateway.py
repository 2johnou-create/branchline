import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from server.app import create_app
from server.config import Settings
from server.engine import Engine, EngineFailure
from server.store import QuotaExceeded, Store


PAYLOAD = {
    "title": "Private launch plan",
    "question": "How might members react to our proposed price change?",
    "context": "CONFIDENTIAL: test brief for a price change with additional membership benefits.",
    "audience": "Existing community gym members",
    "rounds": 5,
    "privacy": {"retention_days": 7},
    "consent_external_processing": True,
}


class FakeEngine:
    async def stop(self, refs):
        return True

    async def cleanup(self, refs):
        return {"project_and_cloud_graph": "operator_cleanup_required", "report": "deletion_acknowledged", "simulation_artifacts": "operator_cleanup_required"}

    async def run(self, payload, update):
        update(status="running", stage="Running scenario", progress=70,
               upstream={"project_id": "private-project-ref", "simulation_id": "private-sim-ref"})
        return {"markdown": "# Synthetic report\nA comparison, not measured customer behaviour."}


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / "private.db"), encryption_key=Fernet.generate_key().decode(),
                    origins=("https://branchline.example",), poll_interval=.001)


@pytest.fixture
def pilot(settings):
    app = create_app(settings, engine=FakeEngine(), launch_jobs=False)
    first, first_token = app.state.store.provision("First", 30)
    second, second_token = app.state.store.provision("Second", 30)
    with TestClient(app) as client:
        yield app, client, first, first_token, second, second_token


def auth(token):
    return {"Authorization": "Bearer " + token}


def test_private_api_requires_valid_workspace_token(pilot):
    _, client, *_ = pilot
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/runs").status_code == 401
    assert client.get("/api/v1/runs", headers=auth("invalid")).status_code == 401
    assert client.get("/api/v1/capabilities", headers=auth("x" * 513)).status_code == 401


def test_workspace_ids_are_never_an_authorization_boundary(pilot):
    app, client, wid, token, other_wid, other_token = pilot
    response = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token))
    assert response.status_code == 202
    rid = response.json()["id"]
    assert client.get(f"/api/v1/runs/{rid}", headers=auth(token)).status_code == 200
    assert client.get(f"/api/v1/runs/{rid}", headers=auth(other_token)).status_code == 404
    assert client.delete(f"/api/v1/runs/{rid}", headers=auth(other_token)).status_code == 404
    assert client.get("/api/v1/runs", headers=auth(other_token)).json() == {"runs": []}
    assert client.delete(f"/api/v1/runs/{rid}", headers=auth(token)).status_code == 409
    assert app.state.store.get(other_wid, rid) is None


def test_content_and_tokens_are_not_stored_in_plaintext(pilot, settings):
    app, client, wid, token, *_ = pilot
    rid = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token)).json()["id"]
    app.state.store.update(wid, rid, result={"markdown": "SECRET-REPORT-CONTENT"}, upstream={"simulation_id": "PRIVATE-UPSTREAM-REFERENCE"})
    persisted = b"".join(path.read_bytes() for path in Path(settings.database).parent.glob("private.db*"))
    for text in [PAYLOAD["title"], PAYLOAD["context"], PAYLOAD["question"], token, "SECRET-REPORT-CONTENT", "PRIVATE-UPSTREAM-REFERENCE"]:
        assert text.encode() not in persisted
    assert app.state.store.get(wid, rid)["private"]["request"]["context"] == PAYLOAD["context"]


def test_active_and_credit_limits_do_not_create_unfunded_runs(pilot):
    app, client, wid, token, *_ = pilot
    first = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token))
    assert first.status_code == 202
    second = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token))
    assert second.status_code == 429
    assert app.state.store.workspace(token)["credits"] == 24
    app.state.store.update(wid, first.json()["id"], status="completed")
    _, rotated_token = app.state.store.provision("First", 1, workspace_id=wid)
    # Token rotation revokes the old credential immediately.
    assert client.get("/api/v1/runs", headers=auth(token)).status_code == 401
    assert client.post("/api/v1/runs", json=PAYLOAD, headers=auth(rotated_token)).status_code == 429
    assert app.state.store.workspace(rotated_token)["credits"] == 1


def test_atomic_reservations_under_concurrency(settings):
    store = Store(settings.database, settings.encryption_key)
    wid, token = store.provision("Concurrent", 6)
    def reserve(_):
        try:
            return store.reserve(wid, PAYLOAD, 100, 100)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(reserve, range(8)))
    assert len([rid for rid in ids if rid]) == 1
    assert store.workspace(token)["credits"] == 0
    assert len(store.list(wid)) == 1


@pytest.mark.parametrize("changes", [
    {"consent_external_processing": False}, {"rounds": 21}, {"rounds": 0},
    {"rounds": "5"}, {"context": "too short"}, {"privacy": {"retention_days": 365}},
    {"engine_url": "http://attacker.internal"},
])
def test_validation_and_processing_consent(pilot, changes):
    _, client, _, token, *_ = pilot
    response = client.post("/api/v1/runs", json={**PAYLOAD, **changes}, headers=auth(token))
    assert response.status_code == 422
    # Validation errors identify fields without echoing the confidential input.
    assert "CONFIDENTIAL" not in response.text


def test_request_body_and_cors_limits(pilot):
    _, client, _, token, *_ = pilot
    response = client.post("/api/v1/runs", content=b"x" * 100_001, headers=auth(token))
    assert response.status_code == 413
    allowed = client.options("/api/v1/runs", headers={"Origin": "https://branchline.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization,Content-Type"})
    denied = client.options("/api/v1/runs", headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"})
    assert allowed.headers["access-control-allow-origin"] == "https://branchline.example"
    assert "access-control-allow-origin" not in denied.headers
    response = client.get("/api/v1/capabilities", headers=auth(token))
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["billing"]["enabled"] is False


def test_deletion_retains_minimal_encrypted_cleanup_ledger(pilot, settings):
    app, client, wid, token, *_ = pilot
    rid = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token)).json()["id"]
    app.state.store.update(wid, rid, status="completed", result={"markdown": "Report"}, upstream={"project_id": "private-project", "simulation_id": "private-sim"})
    response = client.delete(f"/api/v1/runs/{rid}", headers=auth(token))
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["gateway_deleted"] is True
    assert receipt["cleanup_pending"] is True
    assert app.state.store.get(wid, rid) is None
    pending = app.state.store.cleanup_tasks()
    assert len(pending) == 1
    assert pending[0]["id"] == receipt["cleanup_task_id"]
    assert pending[0]["private"]["upstream"]["project_id"] == "private-project"
    assert "request" not in pending[0]["private"]
    assert "result" not in pending[0]["private"]
    assert app.state.store.delete_with_cleanup_ledger(wid, rid, pending[0]["private"]["upstream"], receipt["upstream_cleanup"]) == receipt["cleanup_task_id"]
    assert len(app.state.store.cleanup_tasks()) == 1
    persisted = b"".join(path.read_bytes() for path in Path(settings.database).parent.glob("private.db*"))
    assert b"private-project" not in persisted
    assert app.state.store.resolve_cleanup(receipt["cleanup_task_id"]) is True


def test_worker_persists_actual_adapter_result(settings):
    app = create_app(settings, engine=FakeEngine())
    wid, token = app.state.store.provision("Live test", 30)
    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token))
        rid = response.json()["id"]
        for _ in range(100):
            result = client.get(f"/api/v1/runs/{rid}", headers=auth(token)).json()
            if result["status"] == "completed":
                break
            time.sleep(.005)
        assert result["status"] == "completed"
        assert result["result"]["markdown"].startswith("# Synthetic report")
        assert "private-project-ref" not in json.dumps(result)


def test_restart_marks_tasks_interrupted_without_replaying(settings):
    store = Store(settings.database, settings.encryption_key)
    wid, token = store.provision("Restart", 30)
    rid = store.reserve(wid, PAYLOAD, 1, 2)
    store.claim_next("previous-worker")
    with store.connection(write=True) as db:
        db.execute("UPDATE job_queue SET lease_until=0 WHERE run_id=?", (rid,))
    app = create_app(settings, engine=FakeEngine())
    with TestClient(app) as client:
        result = client.get(f"/api/v1/runs/{rid}", headers=auth(token)).json()
        assert result["status"] == "interrupted"
        assert result["result"] is None
        assert store.workspace(token)["credits"] == 24


@pytest.mark.parametrize("structured_completion", [True, False])
def test_real_engine_adapter_api_flow_and_caps(settings, structured_completion):
    responses = [
        ("POST", "/api/graph/ontology/generate", {"project_id": "proj_1"}),
        ("POST", "/api/graph/build", {"task_id": "graph_task"}),
        ("GET", "/api/graph/task/graph_task", {"status": "processing", "progress": 20}),
        ("GET", "/api/graph/task/graph_task", {"status": "completed", "progress": 100}),
        ("GET", "/api/graph/project/proj_1", {"graph_id": "graph_1"}),
        ("GET", "/api/simulation/entities/graph_1", {"filtered_count": 3, "entities": []}),
        ("POST", "/api/simulation/create", {"simulation_id": "sim_1"}),
        ("POST", "/api/simulation/prepare", {"task_id": "prep_task", "status": "preparing"}),
        ("POST", "/api/simulation/prepare/status", {"status": "ready", "progress": 100}),
        ("GET", "/api/simulation/sim_1", {"profiles_count": 2}),
        ("POST", "/api/simulation/start", {"runner_status": "running"}),
        ("GET", "/api/simulation/sim_1/run-status", {"runner_status": "running", "progress_percent": 30}),
        ("POST", "/api/simulation/env-status", {"env_alive": False}),
        ("GET", "/api/simulation/sim_1/run-status", {"runner_status": "running", "progress_percent": 100, "twitter_completed": structured_completion}),
        ("POST", "/api/simulation/env-status", {"env_alive": False}),
        ("GET", "/api/simulation/sim_1/run-status", {"runner_status": "running", "progress_percent": 100 if structured_completion else 0, "twitter_completed": structured_completion}),
        ("POST", "/api/simulation/env-status", {"env_alive": True}),
        ("POST", "/api/simulation/close-env", {"success": True}),
        ("GET", "/api/simulation/sim_1/run-status", {"runner_status": "completed", "current_round": 5, "total_rounds": 5, "total_actions_count": 17}),
        ("POST", "/api/report/generate", {"report_id": "report_1", "task_id": "report_task"}),
        ("POST", "/api/report/generate/status", {"status": "completed", "progress": 100}),
        ("GET", "/api/report/by-simulation/sim_1", {"report_id": "report_1", "markdown_content": "# Engine report"}),
    ]
    seen = []
    def handler(request):
        method, path, response = responses.pop(0)
        assert (request.method, request.url.path) == (method, path)
        assert request.headers["accept-language"] == "en"
        if path.endswith("ontology/generate"):
            assert b"context.txt" in request.content
            assert PAYLOAD["context"].encode() in request.content
        if path.endswith("/start"):
            data = json.loads(request.content)
            assert data["max_rounds"] == 5
            assert data["enable_graph_memory_update"] is False
            assert data["platform"] == "twitter"
        seen.append(path)
        return httpx.Response(200, json={"success": True, "data": response})
    updates = []
    result = asyncio.run(Engine(settings, transport=httpx.MockTransport(handler)).run(PAYLOAD, lambda **kw: updates.append(kw)))
    assert result == {"markdown": "# Engine report"}
    assert not responses
    assert any(kw.get("status") == "preparing" for kw in updates)
    assert any(kw.get("upstream", {}).get("report_id") == "report_1" for kw in updates)
    telemetry = {}
    for update in updates:
        telemetry.update(update.get("telemetry", {}))
    assert telemetry["entities_count"] == 3
    assert telemetry["agents_total"] == 2
    assert telemetry["current_round"] == 5 and telemetry["actions_count"] == 17
    assert telemetry["runner_status"] == "completed"


def test_adapter_does_not_return_or_log_provider_error_bodies(settings):
    def handler(request):
        return httpx.Response(500, json={"success": False, "error": "SECRET KEY and private customer context", "traceback": "unsafe upstream detail"})
    engine = Engine(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(EngineFailure) as exc:
        asyncio.run(engine.run(PAYLOAD, lambda **_: None))
    assert "SECRET" not in str(exc.value)
    assert "traceback" not in str(exc.value)


def test_adapter_rejects_oversized_audience_before_profile_generation(settings):
    responses = [
        {"project_id": "proj_1"}, {"task_id": "task_1"},
        {"status": "completed"}, {"graph_id": "graph_1"},
        {"filtered_count": 41},
    ]
    def handler(request):
        assert request.url.path != "/api/simulation/create"
        return httpx.Response(200, json={"success": True, "data": responses.pop(0)})
    engine = Engine(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(EngineFailure, match="agent limit"):
        asyncio.run(engine.run(PAYLOAD, lambda **_: None))


def test_engine_cleanup_acknowledges_failures_without_losing_references(settings):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"success": True, "data": {"runner_status": "completed"}})
        if request.url.path.startswith("/api/report/"):
            return httpx.Response(200, json={"success": True})
        return httpx.Response(409, json={"success": False, "error": "Graph busy"})
    engine = Engine(settings, transport=httpx.MockTransport(handler))
    result = asyncio.run(engine.cleanup({"project_id": "proj_1", "simulation_id": "sim_1", "report_id": "report_1"}))
    assert result["project_and_cloud_graph"] == "operator_cleanup_required"
    assert result["report"] == "deletion_acknowledged"
    assert result["simulation_artifacts"] == "operator_cleanup_required"


def test_hardened_engine_artifact_cleanup_requires_positive_acknowledgement(settings):
    settings = replace(settings, engine_cleanup_secret="shared-private-cleanup-key")
    def handler(request):
        if request.url.path.startswith("/internal/"):
            assert request.headers["x-branchline-cleanup-key"] == "shared-private-cleanup-key"
            return httpx.Response(200, json={"success": True, "data": {"deleted": True}})
        return httpx.Response(200, json={"success": True, "data": {"runner_status": "completed"}})
    receipt = asyncio.run(Engine(settings, transport=httpx.MockTransport(handler)).cleanup({"simulation_id": "sim_1"}))
    assert receipt["simulation_artifacts"] == "deletion_acknowledged"


def test_older_engine_404_does_not_imply_artifact_erasure(settings):
    settings = replace(settings, engine_cleanup_secret="shared-private-cleanup-key")
    def handler(request):
        if request.url.path.startswith("/internal/"):
            return httpx.Response(404, json={"error": "Route not found"})
        return httpx.Response(200, json={"success": True, "data": {"runner_status": "completed"}})
    receipt = asyncio.run(Engine(settings, transport=httpx.MockTransport(handler)).cleanup({"simulation_id": "sim_1"}))
    assert receipt["simulation_artifacts"] == "operator_cleanup_required"
