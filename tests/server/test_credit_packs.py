"""One-time Checkout fulfillment: canonical payment, durable exactly-once grant."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs

from cryptography.fernet import Fernet
import httpx
import pytest

from server.billing import Billing, BillingError
from server.store import Store
from tests.server.test_billing import event, signed


class StripeFixture:
    def __init__(self):
        self.sessions = {}
        self.forms = []
        self.price_overrides = {}

    def price(self, pack):
        result = {"id": "price_pack_" + pack, "type": "one_time", "currency": "aud",
                  "unit_amount": {"spark": 400, "boost": 900, "reserve": 1900}[pack], "active": True}
        result.update(self.price_overrides)
        return result

    def __call__(self, request):
        path = request.url.path
        if path.startswith("/v1/prices/price_pack_"):
            return httpx.Response(200, json=self.price(path.removeprefix("/v1/prices/price_pack_")))
        if path == "/v1/customers":
            return httpx.Response(200, json={"id": "cus_a"})
        if path == "/v1/subscriptions":
            return httpx.Response(200, json={"data": [], "has_more": False})
        if path == "/v1/checkout/sessions" and request.method == "POST":
            form = parse_qs(request.content.decode())
            self.forms.append((form, request.headers["Idempotency-Key"]))
            sid = "cs_test_" + str(len(self.sessions) + 1)
            metadata = {key[9:-1]: value[0] for key, value in form.items() if key.startswith("metadata[")}
            self.sessions[sid] = {"id": sid, "mode": form["mode"][0], "status": "open",
                "payment_status": "unpaid", "customer": form["customer"][0],
                "client_reference_id": form["client_reference_id"][0], "metadata": metadata,
                "url": "https://checkout.stripe.com/c/pay/" + sid}
            return httpx.Response(200, json=self.sessions[sid])
        if path.startswith("/v1/checkout/sessions/"):
            suffix = path.removeprefix("/v1/checkout/sessions/")
            sid = suffix.split("/")[0]
            session = self.sessions[sid]
            if suffix.endswith("/line_items"):
                price = self.price(session["metadata"]["pack"])
                return httpx.Response(200, json={"data": [{"price": price, "quantity": 1}], "has_more": False})
            return httpx.Response(200, json=session)
        pytest.fail("Unexpected Stripe path: " + path)

    def pay(self, sid, *, paid=True):
        session = self.sessions[sid]
        price = self.price(session["metadata"]["pack"])
        session.update(status="complete", payment_status="paid" if paid else "unpaid",
                       currency="aud", amount_subtotal=price["unit_amount"], amount_total=price["unit_amount"],
                       payment_intent="pi_" + sid)
        session["line_items"] = {"data": [{"price": price, "quantity": 1}], "has_more": False}


@pytest.fixture
def pack_setup(tmp_path):
    store = Store(str(tmp_path / "packs.sqlite3"), Fernet.generate_key())
    wid, token = store.provision("Pack test", 4)
    user = {"id": "user_a", "workspace_id": wid, "email_verified": True}
    settings = SimpleNamespace(stripe_secret_key="sk_test_fixture", stripe_webhook_secret="whsec_fixture",
        stripe_price_solo="price_solo", stripe_price_studio="price_studio", stripe_price_agency="price_agency",
        stripe_price_pack_spark="price_pack_spark", stripe_price_pack_boost="price_pack_boost", stripe_price_pack_reserve="price_pack_reserve",
        public_url="https://branchline.example", billing_enabled=True, engine_enabled=True)
    provider = StripeFixture()
    billing = Billing(settings, store, httpx.MockTransport(provider))
    return store, user, settings, token, provider, billing


def open_pack(fixture, pack="spark"):
    _, user, _, _, provider, billing = fixture
    url = asyncio.run(billing.checkout_pack(user, pack))
    return url.rsplit("/", 1)[1]


def deliver(fixture, sid, *, eid="evt_pack", kind="checkout.session.completed"):
    _, _, settings, _, _, billing = fixture
    return asyncio.run(billing.webhook(*signed(settings, event({"id": sid}, eid=eid, kind=kind))))


def test_pack_checkout_is_one_time_and_reuses_pending_session(pack_setup):
    store, user, _, token, provider, billing = pack_setup
    sid = open_pack(pack_setup)
    assert open_pack(pack_setup) == sid
    assert len(provider.forms) == 1
    form, key = provider.forms[0]
    assert form["mode"] == ["payment"]
    assert form["line_items[0][price]"] == ["price_pack_spark"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["metadata[workspace_id]"] == [user["workspace_id"]]
    assert form["metadata[checkout_key]"] == [key]
    assert store.workspace(token)["credits"] == 4
    with pytest.raises(BillingError, match="another credit pack"):
        asyncio.run(billing.checkout_pack(user, "boost"))


def test_canonical_paid_pack_grants_once_and_banked_value_has_no_subscription_expiry(pack_setup):
    store, user, _, token, provider, billing = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    assert deliver(pack_setup, sid)["received"]
    assert deliver(pack_setup, sid)["duplicate"]
    deliver(pack_setup, sid, eid="evt_other")
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET subscription_expires_at=1 WHERE id=?", (user["workspace_id"],))
    wallet = store.workspace(token)["credit_wallet"]
    assert wallet["banked"] == wallet["total"] == 28
    assert billing.summary(user["workspace_id"]) is None  # no accidental recurring subscription
    with store.connection() as db:
        assert db.execute("SELECT credits_granted FROM billing_pack_checkouts WHERE session_id=?", (sid,)).fetchone()[0] == 24


def test_unpaid_completion_cannot_grant_but_delayed_success_can(pack_setup):
    store, _, _, token, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid, paid=False)
    assert deliver(pack_setup, sid)["pending"]
    assert store.workspace(token)["credits"] == 4
    provider.pay(sid)
    deliver(pack_setup, sid, eid="evt_paid", kind="checkout.session.async_payment_succeeded")
    assert store.workspace(token)["credits"] == 28


def test_concurrent_distinct_events_for_same_paid_session_grant_once(pack_setup):
    store, _, _, token, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda index: deliver(pack_setup, sid, eid="evt_pack_" + str(index)), range(8)))
    assert all(result["received"] for result in results)
    assert store.workspace(token)["credits"] == 28


@pytest.mark.parametrize("field", ["customer", "workspace", "user", "pack", "reference", "currency", "amount", "quantity", "price"])
def test_wrong_binding_or_amount_does_not_grant(pack_setup, field):
    store, _, _, token, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    session = provider.sessions[sid]
    if field == "customer":
        session["customer"] = "cus_other"
    elif field in {"workspace", "user", "pack"}:
        key = {"workspace": "workspace_id", "user": "user_id", "pack": "pack"}[field]
        session["metadata"][key] = "someone_else"
    elif field == "reference":
        session["client_reference_id"] = "someone_else"
    elif field == "currency":
        session["currency"] = "usd"
    elif field == "amount":
        session["amount_subtotal"] = session["amount_total"] = 1
    elif field == "quantity":
        session["line_items"]["data"][0]["quantity"] = 2
    else:
        session["line_items"]["data"][0]["price"]["id"] = "price_other"
    with pytest.raises(BillingError):
        deliver(pack_setup, sid)
    assert store.workspace(token)["credits"] == 4


def test_webhook_can_reconcile_creation_callback_before_session_id_save(pack_setup):
    store, _, _, token, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_pack_checkouts SET session_id=NULL WHERE session_id=?", (sid,))
    deliver(pack_setup, sid)
    assert store.workspace(token)["credits"] == 28


def test_missing_expanded_line_items_are_fetched_canonically(pack_setup):
    store, _, _, token, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    del provider.sessions[sid]["line_items"]
    deliver(pack_setup, sid)
    assert store.workspace(token)["credits"] == 28


def test_deleted_account_cannot_receive_pack_credits(pack_setup):
    store, user, _, _, provider, _ = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid)
    with store.connection(write=True) as db:
        db.execute("UPDATE workspaces SET credits=0,blocked=1 WHERE id=?", (user["workspace_id"],))
    assert deliver(pack_setup, sid)["ignored"]
    with store.connection() as db:
        assert db.execute("SELECT credits FROM workspaces WHERE id=?", (user["workspace_id"],)).fetchone()[0] == 0


def test_pack_only_configuration_and_launch_gates(pack_setup):
    store, user, settings, _, provider, _ = pack_setup
    settings.stripe_price_solo = settings.stripe_price_studio = settings.stripe_price_agency = ""
    billing = Billing(settings, store, httpx.MockTransport(provider))
    assert billing.configured and billing.packs_enabled and not billing.enabled
    settings.billing_enabled = False
    with pytest.raises(BillingError, match="not enabled"):
        asyncio.run(billing.checkout_pack(user, "spark"))
    assert provider.forms == []


def test_open_pack_checkout_blocks_account_deletion(pack_setup):
    _, user, _, _, _, billing = pack_setup
    open_pack(pack_setup)
    async def attempt():
        with pytest.raises(BillingError, match="credit-pack checkout"):
            async with billing.deletion_guard(user):
                pytest.fail("An outstanding pack payment must reconcile first")
    asyncio.run(attempt())


def test_processing_payment_stays_protected_after_checkout_expiry(pack_setup):
    store, user, _, token, provider, billing = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid, paid=False)
    assert deliver(pack_setup, sid)["pending"]
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_pack_checkouts SET expires_at=1 WHERE session_id=?", (sid,))
        assert db.execute("SELECT status FROM billing_pack_checkouts WHERE session_id=?", (sid,)).fetchone()[0] == "processing"
    async def attempt_delete():
        with pytest.raises(BillingError, match="credit-pack checkout"):
            async with billing.deletion_guard(user):
                pytest.fail("Checkout expiry must not abandon an unsettled payment")
    asyncio.run(attempt_delete())
    with pytest.raises(BillingError, match="still processing"):
        asyncio.run(billing.checkout_pack(user, "spark"))
    provider.pay(sid)
    deliver(pack_setup, sid, eid="evt_delayed", kind="checkout.session.async_payment_succeeded")
    assert store.workspace(token)["credits"] == 28
    async def allow_after_settlement():
        async with billing.deletion_guard(user):
            pass
    asyncio.run(allow_after_settlement())


def test_delayed_webhook_cannot_hide_payment_behind_local_checkout_expiry(pack_setup):
    store, user, _, _, provider, billing = pack_setup
    sid = open_pack(pack_setup)
    provider.pay(sid, paid=False)  # completion webhook has not arrived
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_pack_checkouts SET expires_at=1 WHERE session_id=?", (sid,))
    async def attempt():
        with pytest.raises(BillingError, match="credit-pack checkout"):
            async with billing.deletion_guard(user):
                pytest.fail("An unseen delayed payment must be protected")
    asyncio.run(attempt())
    with store.connection() as db:
        assert db.execute("SELECT status FROM billing_pack_checkouts WHERE session_id=?", (sid,)).fetchone()[0] == "processing"


def test_canonically_expired_unpaid_checkout_releases_deletion_hold(pack_setup):
    store, user, _, _, provider, billing = pack_setup
    sid = open_pack(pack_setup)
    provider.sessions[sid]["status"] = "expired"
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_pack_checkouts SET expires_at=1 WHERE session_id=?", (sid,))
    async def attempt():
        async with billing.deletion_guard(user):
            pass
    asyncio.run(attempt())
    with store.connection() as db:
        assert db.execute("SELECT status FROM billing_pack_checkouts WHERE session_id=?", (sid,)).fetchone()[0] == "expired"


def test_uncertain_creation_cannot_silently_expire_before_account_deletion(pack_setup):
    store, user, _, _, _, billing = pack_setup
    sid = open_pack(pack_setup)
    with store.connection(write=True) as db:
        db.execute("UPDATE billing_pack_checkouts SET session_id=NULL,expires_at=1 WHERE session_id=?", (sid,))
    async def attempt():
        with pytest.raises(BillingError, match="operator reconciliation"):
            async with billing.deletion_guard(user):
                pytest.fail("Unknown remote checkout outcomes need review")
    asyncio.run(attempt())
