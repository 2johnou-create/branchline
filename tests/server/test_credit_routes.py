from dataclasses import replace

from fastapi.testclient import TestClient

from server.app import create_app
from tests.server.test_gateway import FakeEngine, settings


ORIGIN = "https://branchline.example"


def test_free_account_wallet_quote_and_pricing_are_server_authoritative(settings):
    app = create_app(replace(settings, require_email_verification=False), engine=FakeEngine(), launch_jobs=False)
    with TestClient(app, base_url=ORIGIN) as client:
        account = client.post("/api/v1/auth/register", headers={"Origin": ORIGIN}, json={
            "name": "Free account", "email": "free@example.com", "password": "Test-only long password phrase 2026",
        }).json()
        assert account["credits_remaining"] == 4
        wallet = account["credit_wallet"]
        assert wallet["free"] == 4 and wallet["banked"] == 0 and wallet["subscription"] == 0
        assert wallet["free_interval_hours"] == 48 and wallet["free_capacity"] == 4
        headers = {"Origin": ORIGIN, "X-CSRF-Token": account["csrf_token"]}
        quote = client.post("/api/v1/runs/quote", headers=headers, json={"rounds": 3}).json()
        assert quote["sufficient"] is True and quote["credits_required"] == 4
        assert quote["credit_wallet"]["free"] == 4
        config = client.get("/api/v1/config").json()["billing"]
        assert [(plan["price_aud"], plan["monthly_credits"]) for plan in config["plans"]] == [(9, 90), (19, 240), (49, 700)]
        assert [(pack["price_aud"], pack["credits"]) for pack in config["packs"]] == [(4, 24), (9, 60), (19, 150)]
        assert config["free_plan"] == {"credits": 4, "capacity": 4, "interval_hours": 48}
        assert config["enabled"] is False and config["packs_enabled"] is False
        assert client.post("/api/v1/billing/pack", headers={"Origin": ORIGIN}, json={"pack": "spark"}).status_code == 403
        assert client.post("/api/v1/billing/pack", headers=headers, json={"pack": "spark"}).status_code == 503
        assert client.post("/api/v1/billing/pack", headers=headers, json={"pack": "custom", "credits": 500000}).status_code == 422


def test_pack_checkout_rejects_bearer_only_operator_credentials(settings):
    app = create_app(settings, engine=FakeEngine(), launch_jobs=False)
    _, token = app.state.store.provision("Operator", 500000)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post("/api/v1/billing/pack", headers={"Authorization": "Bearer " + token}, json={"pack": "reserve"}).status_code == 401
