import asyncio
import time
from datetime import datetime

from fastapi.testclient import TestClient

from server.app import create_app, public_telemetry
from server.engine import Engine
from tests.server.test_gateway import FakeEngine, PAYLOAD, auth, settings


def test_public_telemetry_distinguishes_unknown_from_observed_zero_and_removes_private_fields():
    result = public_telemetry({
        "source": "mirofish", "agents_total": 2, "agents_active": None,
        "actions_count": 0, "entities_count": True, "current_round": -1,
        "total_rounds": 1, "observed_at": "2026-11-03T12:00:00+00:00",
        "process_pid": 455, "error": "PRIVATE PROVIDER BODY", "agent_names": ["private"],
    })
    assert result["actions_count"] == 0 and result["agents_total"] == 2
    assert "agents_active" not in result and "entities_count" not in result and "current_round" not in result
    assert set(result) == {"source", "agents_total", "actions_count", "total_rounds", "observed_at"}
    assert public_telemetry({"observed_at": "PRIVATE KEY", "source": "untrusted"}) == {}


class ObservedEngine(FakeEngine):
    async def run(self, payload, update):
        update(status="building", stage="Reading context", telemetry={"source": "gateway", "total_rounds": 1})
        await asyncio.sleep(.001)
        update(status="running", stage="Running scenario", telemetry={"source": "mirofish", "agents_total": 2, "current_round": 0, "actions_count": 0})
        await asyncio.sleep(.001)
        update(telemetry={"current_round": 1, "actions_count": 3, "runner_status": "completed", "process_pid": 999})
        return {"markdown": "# Observed scenario report"}


def test_observed_progress_and_stage_history_survive_completion_and_remain_tenant_private(settings):
    app = create_app(settings, engine=ObservedEngine())
    wid, token = app.state.store.provision("Progress", 30)
    _, other_token = app.state.store.provision("Another workspace", 30)
    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json={**PAYLOAD, "rounds": 1}, headers=auth(token))
        rid = response.json()["id"]
        for _ in range(200):
            result = client.get("/api/v1/runs/" + rid, headers=auth(token)).json()
            if result["status"] == "completed":
                break
            time.sleep(.005)
        assert result["status"] == "completed"
        telemetry = result["telemetry"]
        assert telemetry["agents_total"] == 2 and telemetry["actions_count"] == 3
        assert telemetry["current_round"] == 1 and telemetry["source"] == "mirofish"
        assert "process_pid" not in telemetry
        assert [event["stage"] for event in telemetry["timeline"]] == ["Queued", "Reading context", "Running scenario", "Report ready"]
        assert all(datetime.fromisoformat(event["at"]).tzinfo for event in telemetry["timeline"])
        assert client.get("/api/v1/runs/" + rid, headers=auth(other_token)).status_code == 404
        stored = app.state.store.get(wid, rid)["private"]["telemetry"]
        assert stored["actions_count"] == 3


def test_engine_counter_projection_keeps_only_observed_metadata():
    counts = Engine.observed_counts({"twitter_current_round": 2, "current_round": 4,
                                     "total_rounds": 5, "total_actions_count": 9,
                                     "runner_status": "running", "recent_actions": [{"prompt": "private"}]})
    assert counts["current_round"] == 2 and counts["actions_count"] == 9
    assert "agents_active" not in counts and "recent_actions" not in counts


def test_refinement_fetches_only_owned_brief_without_reusing_consent(settings):
    app = create_app(settings, engine=ObservedEngine(), launch_jobs=False)
    _, token = app.state.store.provision("Brief owner", 30)
    _, other_token = app.state.store.provision("Other workspace", 30)
    with TestClient(app) as client:
        rid = client.post("/api/v1/runs", json=PAYLOAD, headers=auth(token)).json()["id"]
        listing = client.get("/api/v1/runs", headers=auth(token))
        assert PAYLOAD["context"] not in listing.text
        response = client.get("/api/v1/runs/" + rid + "/brief", headers=auth(token))
        assert response.status_code == 200 and response.json()["brief"]["context"] == PAYLOAD["context"]
        assert "consent_external_processing" not in response.json()["brief"]
        assert "upstream" not in response.text
        assert client.get("/api/v1/runs/" + rid + "/brief", headers=auth(other_token)).status_code == 404
        assert client.get("/api/v1/runs/" + rid + "/brief").status_code == 401
