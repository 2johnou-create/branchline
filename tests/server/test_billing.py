"""Billing contract tests: mocked Stripe network, real SQLite atomic ledger."""
import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

from cryptography.fernet import Fernet
import httpx
import pytest

from server.billing import API_VERSION, Billing, BillingError
from server.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path / "billing.sqlite3"), Fernet.generate_key())
    wid, token = store.provision("Billing test", 4)
    user = {"id": "user_a", "workspace_id": wid, "email": "owner@example.test", "name": "Owner", "email_verified": True}
    settings = SimpleNamespace(stripe_secret_key="sk_test_fixture", stripe_webhook_secret="whsec_fixture",
        stripe_price_solo="price_solo", stripe_price_studio="price_studio", stripe_price_agency="price_agency",
        public_url="https://branchline.example", billing_enabled=True, engine_enabled=True)
    return store, user, settings, token


def price(plan="solo", **changes):
    result = {"id": "price_" + plan, "currency": "aud", "unit_amount": {"solo": 4900, "studio": 19900, "agency": 59900}[plan],
              "type": "recurring", "active": True, "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}}
    result.update(changes)
    return result


def subscription(user, *, sid="sub_a", status="active", start=None, end=None, plan="solo", created=None, **changes):
    now = int(time.time())
    start, end = start or now - 100, end or now + 2600000
    result = {"id": sid, "customer": "cus_a", "created": created or now - 1000, "status": status,
        "metadata": {"workspace_id": user["workspace_id"], "user_id": user["id"]},
        "cancel_at_period_end": False,
        "items": {"data": [{"price": price(plan), "quantity": 1, "current_period_start": start, "current_period_end": end}]}}
    result.update(changes)
    return result


def invoice(sub, *, iid="in_a", reason="subscription_cycle", **changes):
    item = sub["items"]["data"][0]
    result = {"id": iid, "customer": "cus_a", "status": "paid", "billing_reason": reason, "currency": "aud",
        "parent": {"type": "subscription_details", "subscription_details": {"subscription": sub["id"]}},
        "lines": {"has_more": False, "data": [{"quantity": 1,
            "parent": {"type": "subscription_item_details", "subscription_item_details": {"proration": False}},
            "pricing": {"price_details": {"price": item["price"]["id"]}},
            "period": {"start": item["current_period_start"], "end": item["current_period_end"]}}]}}
    result.update(changes)
    return result


def event(obj, *, kind="invoice.paid", eid="evt_a", created=None, **changes):
    result = {"id": eid, "type": kind, "created": created or int(time.time()), "api_version": API_VERSION,
              "livemode": False, "data": {"object": obj}}
    result.update(changes)
    return result


def signed(settings, evt, *, timestamp=None):
    raw = json.dumps(evt, separators=(",", ":")).encode()
    stamp = int(time.time()) if timestamp is None else timestamp
    sig = hmac.new(settings.stripe_webhook_secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, f"t={stamp},v1={sig}"


def bind(billing, user, **values):
    billing._owner(user)
    with billing.store.connection(write=True) as db:
        db.execute("UPDATE billing_accounts SET customer_id='cus_a' WHERE workspace_id=?", (user["workspace_id"],))
        for key, value in values.items():
            assert key in {"subscription_id", "subscription_created", "status", "event_created", "current_period_start", "current_period_end"}
            db.execute(f"UPDATE billing_accounts SET {key}=? WHERE workspace_id=?", (value, user["workspace_id"]))


def transport_for(subs, invoices=None, extra=None):
    def handle(request):
        assert request.url.host == "api.stripe.com"
        assert request.headers["Stripe-Version"] == API_VERSION
        path = request.url.path
        if path.startswith("/v1/subscriptions/"):
            result = subs[path.rsplit("/", 1)[1]]
        elif path.startswith("/v1/invoices/"):
            result = (invoices or {})[path.rsplit("/", 1)[1]]
        elif path.startswith("/v1/prices/"):
            result = price(path.rsplit("_", 1)[1])
        elif extra:
            return extra(request)
        else:
            raise AssertionError(f"Unexpected Stripe request: {path}")
        return httpx.Response(200, json=result)
    return httpx.MockTransport(handle)


def run_webhook(billing, settings, evt):
    return asyncio.run(billing.webhook(*signed(settings, evt)))


def credits(store, token):
    return store.workspace(token)["credits"]


def test_disabled_billing_makes_no_network_call(setup):
    store, user, settings, _ = setup
    settings.stripe_secret_key = ""
    billing = Billing(settings, store, httpx.MockTransport(lambda request: pytest.fail("No request expected")))
    assert not billing.enabled
    with pytest.raises(BillingError, match="not enabled") as error:
        asyncio.run(billing.checkout(user, "solo"))
    assert error.value.status_code == 503


@pytest.mark.parametrize("timestamp", [1, 9999999999])
def test_old_and_future_signatures_rejected(setup, timestamp):
    store, user, settings, _ = setup
    billing = Billing(settings, store)
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.webhook(*signed(settings, event({}), timestamp=timestamp)))
    assert error.value.status_code == 400


def test_modified_payload_bad_signature_and_wrong_mode_rejected(setup):
    store, user, settings, _ = setup
    billing = Billing(settings, store)
    raw, signature = signed(settings, event({}))
    for body, header in [(raw + b" ", signature), (raw, "t=broken,v1=bad"), signed(settings, event({}, livemode=True))]:
        with pytest.raises(BillingError) as error:
            asyncio.run(billing.webhook(body, header))
        assert error.value.status_code == 400


def test_monthly_entitlement_replay_and_distinct_event_same_invoice(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    assert run_webhook(billing, settings, event(inv))["received"]
    assert credits(store, token) == 30
    # Spending credits must not be reversed by duplicate delivery or a second event for the same invoice.
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=12 WHERE id=?", (user["workspace_id"],))
    assert run_webhook(billing, settings, event(inv))["duplicate"]
    run_webhook(billing, settings, event(inv, eid="evt_other"))
    assert credits(store, token) == 12
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM billing_credit_ledger").fetchone()[0] == 1


def test_duplicate_period_with_different_invoice_does_not_refill(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    first, duplicate = invoice(sub), invoice(sub, iid="in_other")
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": first, "in_other": duplicate}))
    bind(billing, user)
    run_webhook(billing, settings, event(first))
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=10 WHERE id=?", (user["workspace_id"],))
    run_webhook(billing, settings, event(duplicate, eid="evt_other"))
    assert credits(store, token) == 10


def test_new_period_replaces_nonrollover_credits(setup):
    store, user, settings, token = setup
    now = int(time.time())
    old = subscription(user, start=now-100, end=now+100)
    current = subscription(user, start=now+100, end=now+2600000, plan="studio")
    state = {"sub_a": old}
    invoices = {"in_a": invoice(old), "in_new": invoice(current, iid="in_new")}
    billing = Billing(settings, store, transport_for(state, invoices))
    bind(billing, user)
    run_webhook(billing, settings, event(invoices["in_a"]))
    state["sub_a"] = current
    run_webhook(billing, settings, event(invoices["in_new"], eid="evt_new", created=now+1))
    assert credits(store, token) == 150
    # An older paid invoice fetched after renewal does not restore the old allowance.
    run_webhook(billing, settings, event(invoices["in_a"], eid="evt_late", created=now-1))
    assert credits(store, token) == 150


def test_current_cancellation_cannot_be_undone_by_late_invoice(setup):
    store, user, settings, token = setup
    sub = subscription(user, status="canceled")
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    run_webhook(billing, settings, event(sub, kind="customer.subscription.deleted", eid="evt_cancel"))
    run_webhook(billing, settings, event(inv, created=int(time.time())-10))
    assert credits(store, token) == 0
    assert billing.summary(user["workspace_id"])["status"] == "canceled"


def test_period_end_cancel_keeps_paid_credits(setup):
    store, user, settings, token = setup
    sub = subscription(user, cancel_at_period_end=True)
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    run_webhook(billing, settings, event(inv))
    assert credits(store, token) == 30
    assert billing.summary(user["workspace_id"])["cancel_at_period_end"]


def test_old_subscription_deletion_cannot_cancel_new_subscription(setup):
    store, user, settings, token = setup
    now = int(time.time())
    old = subscription(user, status="canceled", sid="sub_old", created=now-2000)
    new = subscription(user, sid="sub_new", created=now-100)
    inv = invoice(new)
    billing = Billing(settings, store, transport_for({"sub_old": old, "sub_new": new}, {"in_a": inv}))
    bind(billing, user, subscription_id="sub_old", subscription_created=old["created"], status="active")
    # The cancellation notification has not arrived; canonical old-subscription fetch permits safe replacement.
    run_webhook(billing, settings, event(inv))
    assert credits(store, token) == 30
    run_webhook(billing, settings, event(old, kind="customer.subscription.deleted", eid="evt_old"))
    assert credits(store, token) == 30
    assert billing._account(user["workspace_id"])["subscription_id"] == "sub_new"


def test_workspace_binding_mismatch_fails_closed(setup):
    store, user, settings, token = setup
    sub = subscription(user, metadata={"workspace_id": "someone_else", "user_id": "other"})
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    with pytest.raises(BillingError, match="does not match"):
        run_webhook(billing, settings, event(inv))
    assert credits(store, token) == 4


def test_deleted_workspace_never_regains_entitlement(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=0,blocked=1 WHERE id=?", (user["workspace_id"],))
    result = run_webhook(billing, settings, event(inv))
    assert result["ignored"]
    assert store.workspace(token) is None
    with store.connection() as db:
        assert db.execute("SELECT credits FROM workspaces WHERE id=?", (user["workspace_id"],)).fetchone()[0] == 0


@pytest.mark.parametrize("reason,proration", [("subscription_update", False), ("subscription_cycle", True)])
def test_proration_or_plan_change_does_not_grant_monthly_allowance(setup, reason, proration):
    store, user, settings, token = setup
    sub = subscription(user)
    inv = invoice(sub, reason=reason)
    inv["lines"]["data"][0]["parent"]["subscription_item_details"]["proration"] = proration
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    run_webhook(billing, settings, event(inv))
    assert credits(store, token) == 4


def test_checkout_uses_server_price_id_and_reuses_open_session(setup):
    store, user, settings, token = setup
    posts = []
    session = {"id": "cs_test_a", "status": "open", "url": "https://checkout.stripe.com/c/pay/cs_test_a"}
    def extra(request):
        if request.url.path == "/v1/subscriptions":
            return httpx.Response(200, json={"data": [], "has_more": False})
        if request.url.path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_a"})
        if request.url.path == "/v1/checkout/sessions" and request.method == "POST":
            posts.append((parse_qs(request.content.decode()), request.headers["Idempotency-Key"]))
            return httpx.Response(200, json=session)
        if request.url.path == "/v1/checkout/sessions/cs_test_a":
            return httpx.Response(200, json=session)
        pytest.fail(str(request.url))
    billing = Billing(settings, store, transport_for({}, extra=extra))
    async def twice():
        first = await billing.checkout(user, "solo")
        second = await billing.checkout(user, "solo")
        assert first == second == session["url"]
    asyncio.run(twice())
    assert len(posts) == 1
    form, key = posts[0]
    assert form["line_items[0][price]"] == ["price_solo"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["customer"] == ["cus_a"]
    assert form["subscription_data[metadata][workspace_id]"] == [user["workspace_id"]]
    assert credits(store, token) == 4  # redirects/session creation grant nothing
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.checkout(user, "price_attacker"))
    assert error.value.status_code == 422


def test_checkout_rejects_wrong_price_and_unverified_user(setup):
    store, user, settings, _ = setup
    billing = Billing(settings, store, httpx.MockTransport(lambda r: httpx.Response(200, json=price(currency="usd"))))
    with pytest.raises(BillingError, match="configuration"):
        asyncio.run(billing.checkout(user, "solo"))
    user["email_verified"] = False
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.checkout(user, "solo"))
    assert error.value.status_code == 403


def test_portal_uses_bound_customer_and_provider_errors_are_safe(setup):
    store, user, settings, _ = setup
    def portal(request):
        assert request.url.path == "/v1/billing_portal/sessions"
        assert parse_qs(request.content.decode())["customer"] == ["cus_a"]
        return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/test"})
    billing = Billing(settings, store, httpx.MockTransport(portal))
    bind(billing, user)
    assert asyncio.run(billing.portal(user)) == "https://billing.stripe.com/p/session/test"
    billing.transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "SECRET provider debug"}}))
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.portal(user))
    assert "SECRET" not in error.value.detail


def test_checkout_completed_never_grants_credits(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    session = {"id": "cs_a", "mode": "subscription", "status": "complete", "customer": "cus_a", "subscription": "sub_a"}
    billing = Billing(settings, store, transport_for({"sub_a": sub}, extra=lambda r: httpx.Response(200, json=session)))
    bind(billing, user)
    run_webhook(billing, settings, event(session, kind="checkout.session.completed"))
    assert credits(store, token) == 4


def test_unknown_price_and_wrong_api_version_fail_closed(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    sub["items"]["data"][0]["price"] = {"id": "price_other"}
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    bind(billing, user)
    with pytest.raises(BillingError, match="price is not supported"):
        run_webhook(billing, settings, event(inv))
    with pytest.raises(BillingError, match="API version"):
        run_webhook(billing, settings, event(inv, api_version="future"))
    assert credits(store, token) == 4


def test_deleted_workspace_checkout_is_denied(setup):
    store, user, settings, token = setup
    billing = Billing(settings, store, httpx.MockTransport(lambda request: pytest.fail("No request expected")))
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET blocked=1 WHERE id=?", (user["workspace_id"],))
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.checkout(user, "solo"))
    assert error.value.status_code == 403


def test_checkout_rejects_canonical_active_subscription(setup):
    store, user, settings, _ = setup
    sub = subscription(user)
    def extra(request):
        assert request.url.path == "/v1/subscriptions"
        return httpx.Response(200, json={"data": [sub], "has_more": False})
    billing = Billing(settings, store, transport_for({}, extra=extra))
    bind(billing, user)
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.checkout(user, "solo"))
    assert error.value.status_code == 409


def test_deletion_guard_blocks_pending_checkout_and_releases_lock(setup):
    store, user, settings, _ = setup
    billing = Billing(settings, store, httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [], "has_more": False})))
    bind(billing, user)
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_accounts SET checkout_expires=? WHERE workspace_id=?", (int(time.time())+100, user["workspace_id"]))
    assert billing.summary(user["workspace_id"])["checkout_pending"]
    async def guarded():
        with pytest.raises(BillingError) as error:
            async with billing.deletion_guard(user):
                pytest.fail("Deletion must not proceed")
        assert error.value.status_code == 409
        assert not billing._locks[user["workspace_id"]].locked()
    asyncio.run(guarded())


def test_deletion_guard_holds_checkout_lock_until_freeze(setup):
    store, user, settings, _ = setup
    billing = Billing(settings, store)
    async def guarded():
        async with billing.deletion_guard(user):
            assert billing._locks[user["workspace_id"]].locked()
            with store.connection(write=True) as db:
                db.execute("UPDATE workspaces SET blocked=1 WHERE id=?", (user["workspace_id"],))
        with pytest.raises(BillingError):
            await billing.checkout(user, "solo")
    asyncio.run(guarded())


def test_stale_snapshot_cannot_undo_newer_revocation(setup):
    store, user, settings, token = setup
    sub = subscription(user)
    inv = invoice(sub)
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}))
    # Simulate concurrent canonical fetch racing with a newer cancellation commit.
    bind(billing, user, subscription_id="sub_a", subscription_created=sub["created"], status="canceled", event_created=int(time.time())+1)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=0,subscription_expires_at=1 WHERE id=?", (user["workspace_id"],))
    assert run_webhook(billing, settings, event(inv))["ignored"]
    assert credits(store, token) == 0


def test_checkout_launch_flag_and_engine_readiness_required(setup):
    store, user, settings, _ = setup
    billing = Billing(settings, store, httpx.MockTransport(lambda request: pytest.fail("No request expected")))
    settings.billing_enabled = False
    assert billing.configured and not billing.enabled
    with pytest.raises(BillingError) as error:
        asyncio.run(billing.checkout(user, "solo"))
    assert error.value.status_code == 503
    settings.billing_enabled, settings.engine_enabled = True, False
    assert not billing.enabled


def test_paused_checkout_keeps_existing_portal_and_webhook_working(setup):
    store, user, settings, token = setup
    settings.billing_enabled = settings.engine_enabled = False
    sub = subscription(user, status="canceled")
    inv = invoice(sub)
    def extra(request):
        assert request.url.path == "/v1/billing_portal/sessions"
        return httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/test"})
    billing = Billing(settings, store, transport_for({"sub_a": sub}, {"in_a": inv}, extra))
    bind(billing, user)
    assert not billing.enabled
    assert asyncio.run(billing.portal(user)).startswith("https://billing.stripe.com/")
    run_webhook(billing, settings, event(inv))
    assert credits(store, token) == 0
