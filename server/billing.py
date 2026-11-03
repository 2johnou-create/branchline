"""Optional Stripe-hosted billing. No browser prices or redirect-based grants.

API shape pinned to 2025-06-30.basil; configure the snapshot webhook to match.
See https://docs.stripe.com/api/checkout/sessions/create and
https://docs.stripe.com/events/set-up-events for the verified API contracts.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlparse
import uuid

import httpx

API_VERSION = "2025-06-30.basil"
PLAN_DATA = {
    "solo": {"id": "solo", "name": "Plus", "price_aud": 9, "credits": 90, "monthly_credits": 90, "interval": "month"},
    "studio": {"id": "studio", "name": "Studio", "price_aud": 19, "credits": 240, "monthly_credits": 240, "interval": "month"},
    "agency": {"id": "agency", "name": "Pro", "price_aud": 49, "credits": 700, "monthly_credits": 700, "interval": "month"},
}
PACK_DATA = {
    "spark": {"id": "spark", "name": "Spark", "price_aud": 4, "credits": 24, "interval": "one_time", "expires": False},
    "boost": {"id": "boost", "name": "Boost", "price_aud": 9, "credits": 60, "interval": "one_time", "expires": False},
    "reserve": {"id": "reserve", "name": "Reserve", "price_aud": 19, "credits": 150, "interval": "one_time", "expires": False},
}
REVOKED = {"canceled", "unpaid", "incomplete_expired", "paused"}
TERMINAL_SUBSCRIPTIONS = {"canceled", "incomplete_expired"}
EVENT_TYPES = {"checkout.session.completed", "checkout.session.async_payment_succeeded", "customer.subscription.created",
               "customer.subscription.updated", "customer.subscription.deleted",
               "invoice.paid", "invoice.payment_failed"}


class BillingError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def identifier(value, prefix):
    if isinstance(value, dict):
        value = value.get("id")
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[A-Za-z0-9_]+", value):
        raise BillingError(400, "Billing resource data is invalid. Contact the operator.")
    return value


class Billing:
    def __init__(self, settings, store, transport=None):
        self.settings, self.store, self.transport = settings, store, transport
        self.secret = getattr(settings, "stripe_secret_key", "")
        self.webhook_secret = getattr(settings, "stripe_webhook_secret", "")
        self.public_url = getattr(settings, "public_url", "").rstrip("/")
        self.price_ids = {p: getattr(settings, "stripe_price_" + p, "") for p in PLAN_DATA}
        self.pack_price_ids = {p: getattr(settings, "stripe_price_pack_" + p, "") for p in PACK_DATA}
        self._locks = {}
        with store.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS billing_accounts (
                workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), user_id TEXT NOT NULL,
                customer_id TEXT UNIQUE, subscription_id TEXT UNIQUE,
                subscription_created INTEGER NOT NULL DEFAULT 0,
                plan TEXT, status TEXT NOT NULL DEFAULT 'none',
                current_period_start INTEGER NOT NULL DEFAULT 0,
                current_period_end INTEGER NOT NULL DEFAULT 0,
                cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                event_created INTEGER NOT NULL DEFAULT 0,
                checkout_key TEXT, checkout_plan TEXT, checkout_expires INTEGER,
                checkout_session TEXT, checkout_url TEXT);
              CREATE TABLE IF NOT EXISTS billing_events (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, created INTEGER NOT NULL,
                processed_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS billing_credit_ledger (
                invoice_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id), subscription_id TEXT NOT NULL,
                period_start INTEGER NOT NULL, period_end INTEGER NOT NULL,
                plan TEXT NOT NULL, credits INTEGER NOT NULL,
                UNIQUE(subscription_id,period_start));
              CREATE TABLE IF NOT EXISTS billing_pack_checkouts (
                checkout_key TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                user_id TEXT NOT NULL, pack TEXT NOT NULL, session_id TEXT UNIQUE,
                expires_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                credits_granted INTEGER NOT NULL DEFAULT 0, payment_intent TEXT UNIQUE);
            """)

    @property
    def configured(self):
        parsed = urlparse(self.public_url)
        return bool(self.secret and self.webhook_secret and
                    (self.subscription_prices_configured or self.pack_prices_configured) and
                    parsed.scheme == "https" and parsed.netloc and not parsed.query and not parsed.fragment)

    @property
    def subscription_prices_configured(self):
        return bool(all(self.price_ids.values()) and len(set(self.price_ids.values())) == len(PLAN_DATA))

    @property
    def pack_prices_configured(self):
        return bool(all(self.pack_price_ids.values()) and len(set(self.pack_price_ids.values())) == len(PACK_DATA) and not (set(self.pack_price_ids.values()) & (set(self.price_ids.values()) - {""})))

    @property
    def enabled(self):
        return bool(self.configured and self.subscription_prices_configured and getattr(self.settings, "billing_enabled", False) and
                    getattr(self.settings, "engine_enabled", False))

    @property
    def packs_enabled(self):
        return bool(self.configured and self.pack_prices_configured and getattr(self.settings, "billing_enabled", False) and getattr(self.settings, "engine_enabled", False))

    @property
    def plans(self):
        return [dict(p) for p in PLAN_DATA.values()]

    @property
    def packs(self):
        return [dict(p) for p in PACK_DATA.values()]

    def require_enabled(self):
        if not self.enabled:
            raise BillingError(503, "Subscription checkout is not enabled. Contact the operator.")

    def require_configured(self):
        if not self.configured:
            raise BillingError(503, "Billing is not configured. Contact the operator.")

    def summary(self, wid):
        with self.store.connection() as db:
            row = db.execute("SELECT plan,status,current_period_end,cancel_at_period_end,checkout_expires FROM billing_accounts WHERE workspace_id=?", (wid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["cancel_at_period_end"] = bool(result["cancel_at_period_end"])
        result["checkout_pending"] = bool((result.pop("checkout_expires") or 0) > time.time())
        if not result["plan"] and result["status"] == "none" and not result["checkout_pending"]:
            return None  # a one-time pack buyer is still on the Free plan
        return result

    @asynccontextmanager
    async def deletion_guard(self, user):
        """Keep the checkout lock until the caller atomically freezes the account.

        The app must call freeze_account inside this context, with no awaits
        between a successful yield and freeze. No automatic financial cancellation.
        """
        wid = user["workspace_id"]
        async with self._locks.setdefault(wid, asyncio.Lock()):
            account = self._account(wid)
            if account and account["customer_id"]:
                self.require_configured()
                subscriptions = await self._call("GET", "/v1/subscriptions", params={
                    "customer": account["customer_id"], "status": "all", "limit": 100})
                if subscriptions.get("has_more") or any(s.get("status") not in TERMINAL_SUBSCRIPTIONS for s in subscriptions.get("data", [])):
                    raise BillingError(409, "Cancel your subscription in the billing portal before deleting your account.")
                if (account["checkout_expires"] or 0) > time.time():
                    raise BillingError(409, "An open checkout must finish or expire before this account can be deleted.")
            await self._guard_pack_deletion(wid, account)
            yield

    async def _guard_pack_deletion(self, wid, account):
        # A webhook can be delayed beyond Checkout expiry. Reconcile expired
        # local orders with Stripe before allowing destructive account changes.
        with self.store.connection() as db:
            orders = [dict(row) for row in db.execute("SELECT * FROM billing_pack_checkouts WHERE workspace_id=? AND credits_granted=0 AND status IN ('open','processing')", (wid,))]
        for order in orders:
            if order["status"] == "open" and order["expires_at"] > int(time.time()):
                raise BillingError(409, "An open credit-pack checkout must finish or expire before this account can be deleted.")
            if not order["session_id"] or not account or not account["customer_id"]:
                # A creation timeout may have succeeded remotely. Do not infer
                # that no payment exists from a missing local session ID.
                raise BillingError(409, "The credit-pack checkout needs operator reconciliation before account deletion.")
            self.require_configured()
            session = await self._call("GET", "/v1/checkout/sessions/" + identifier(order["session_id"], "cs"))
            metadata = session.get("metadata") or {}
            if (session.get("id") != order["session_id"] or session.get("mode") != "payment" or
                session.get("customer") != account["customer_id"] or
                metadata.get("checkout_key") != order["checkout_key"] or
                metadata.get("workspace_id") != wid or metadata.get("user_id") != order["user_id"]):
                raise BillingError(409, "The credit-pack checkout needs operator reconciliation before account deletion.")
            if session.get("status") == "expired" and session.get("payment_status") == "unpaid":
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_pack_checkouts SET status='expired' WHERE checkout_key=? AND credits_granted=0", (order["checkout_key"],))
                continue
            if session.get("status") == "complete" and session.get("payment_status") != "paid":
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_pack_checkouts SET status='processing' WHERE checkout_key=? AND credits_granted=0", (order["checkout_key"],))
            raise BillingError(409, "The credit-pack checkout payment must settle and reconcile before account deletion. Wait for your balance to update or contact the operator.")

    def _account(self, wid):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM billing_accounts WHERE workspace_id=?", (wid,)).fetchone()
        return dict(row) if row else None

    def _owner(self, user):
        if not user.get("email_verified"):
            raise BillingError(403, "Verify your email before managing billing.")
        wid, uid = user.get("workspace_id"), user.get("id")
        if not isinstance(wid, str) or not isinstance(uid, str):
            raise BillingError(403, "A signed-in account is required for billing.")
        with self.store.connection(write=True) as db:
            ws = db.execute("SELECT blocked FROM workspaces WHERE id=?", (wid,)).fetchone()
            if not ws or ws["blocked"]:
                raise BillingError(403, "This account cannot manage billing.")
            db.execute("INSERT OR IGNORE INTO billing_accounts(workspace_id,user_id) VALUES (?,?)", (wid, uid))
            row = db.execute("SELECT * FROM billing_accounts WHERE workspace_id=?", (wid,)).fetchone()
            if row["user_id"] != uid:
                raise BillingError(403, "Only the workspace billing owner can manage billing.")
        return wid, dict(row)

    async def _call(self, method, path, *, data=None, params=None, key=None):
        headers = {"Authorization": "Bearer " + self.secret, "Stripe-Version": API_VERSION}
        if key:
            headers["Idempotency-Key"] = key
        try:
            async with httpx.AsyncClient(base_url="https://api.stripe.com", timeout=20,
                                         follow_redirects=False, transport=self.transport) as client:
                response = await client.request(method, path, data=data, params=params, headers=headers)
            if response.status_code >= 400 or len(response.content) > 1_000_000:
                raise BillingError(502, "The billing provider could not complete this request. Try again or contact the operator.")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Unexpected billing response")
            return body
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise BillingError(502, "The billing provider is unavailable. Try again later.") from exc

    def _plan_for_price(self, price):
        pid = price.get("id") if isinstance(price, dict) else price
        for plan, configured in self.price_ids.items():
            if configured == pid:
                return plan
        raise BillingError(400, "The subscription price is not supported. Contact the operator.")

    def _validate_price(self, price, plan, *, active=False):
        recurring = price.get("recurring") or {}
        if (price.get("id") != self.price_ids[plan] or price.get("currency") != "aud" or
            price.get("unit_amount") != PLAN_DATA[plan]["price_aud"] * 100 or
            price.get("type") != "recurring" or recurring.get("interval") != "month" or
            recurring.get("interval_count") != 1 or recurring.get("usage_type", "licensed") != "licensed" or
            (active and price.get("active") is not True)):
            raise BillingError(503, "The billing plan configuration needs operator attention.")

    @staticmethod
    def _hosted_url(value, host):
        parsed = urlparse(value if isinstance(value, str) else "")
        if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.password:
            raise BillingError(502, "The billing provider returned an invalid redirect.")
        return value

    async def checkout(self, user, plan):
        self.require_enabled()
        if plan not in PLAN_DATA:
            raise BillingError(422, "Choose a supported subscription plan.")
        wid, _ = self._owner(user)
        async with self._locks.setdefault(wid, asyncio.Lock()):
            _, account = self._owner(user)
            price = await self._call("GET", "/v1/prices/" + identifier(self.price_ids[plan], "price"))
            self._validate_price(price, plan, active=True)
            customer = account["customer_id"]
            if not customer:
                created = await self._call("POST", "/v1/customers", data={
                    "metadata[workspace_id]": wid, "metadata[user_id]": user["id"],
                }, key="branchline-customer-" + wid)
                customer = identifier(created.get("id"), "cus")
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_accounts SET customer_id=? WHERE workspace_id=? AND customer_id IS NULL", (customer, wid))
                account = self._account(wid)
                customer = account["customer_id"]
            subscriptions = await self._call("GET", "/v1/subscriptions", params={"customer": customer, "status": "all", "limit": 100})
            if subscriptions.get("has_more") or any(s.get("status") not in TERMINAL_SUBSCRIPTIONS for s in subscriptions.get("data", [])):
                raise BillingError(409, "A subscription already exists. Manage it through the billing portal.")
            now = int(time.time())
            if account.get("checkout_expires", 0) and account["checkout_expires"] > now:
                if account["checkout_plan"] != plan:
                    raise BillingError(409, "A checkout is already open for another plan. Complete it or wait for it to expire.")
                if account["checkout_session"]:
                    session = await self._call("GET", "/v1/checkout/sessions/" + identifier(account["checkout_session"], "cs"))
                    if session.get("status") == "open":
                        return self._hosted_url(session.get("url"), "checkout.stripe.com")
                    raise BillingError(409, "This checkout has finished. Wait for billing to synchronise before trying again.")
            else:
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_accounts SET checkout_key=?,checkout_plan=?,checkout_expires=?,checkout_session=NULL,checkout_url=NULL WHERE workspace_id=?",
                               ("branchline-checkout-" + uuid.uuid4().hex, plan, now + 3600, wid))
                account = self._account(wid)
            session = await self._call("POST", "/v1/checkout/sessions", data={
                "mode": "subscription", "customer": customer,
                "client_reference_id": wid,
                "metadata[workspace_id]": wid, "metadata[user_id]": user["id"],
                "subscription_data[metadata][workspace_id]": wid,
                "subscription_data[metadata][user_id]": user["id"],
                "line_items[0][price]": self.price_ids[plan], "line_items[0][quantity]": "1",
                "success_url": self.public_url + "/#plans", "cancel_url": self.public_url + "/#plans",
                "expires_at": str(account["checkout_expires"]),
            }, key=account["checkout_key"])
            sid = identifier(session.get("id"), "cs")
            url = self._hosted_url(session.get("url"), "checkout.stripe.com")
            with self.store.connection(write=True) as db:
                # Hosted URLs contain session secrets; retain only the session identifier.
                db.execute("UPDATE billing_accounts SET checkout_session=? WHERE workspace_id=?", (sid, wid))
            return url

    async def portal(self, user):
        self.require_configured()
        _, account = self._owner(user)
        if not account["customer_id"]:
            raise BillingError(409, "This account has no billing customer yet.")
        session = await self._call("POST", "/v1/billing_portal/sessions", data={
            "customer": account["customer_id"], "return_url": self.public_url + "/#plans",
        })
        return self._hosted_url(session.get("url"), "billing.stripe.com")

    def _validate_pack_price(self, price, pack, *, active=False):
        if (price.get("id") != self.pack_price_ids[pack] or price.get("currency") != "aud" or
            price.get("unit_amount") != PACK_DATA[pack]["price_aud"] * 100 or
            price.get("type") != "one_time" or price.get("recurring") or
            (active and price.get("active") is not True)):
            raise BillingError(503, "The credit-pack configuration needs operator attention.")

    async def checkout_pack(self, user, pack):
        if not self.packs_enabled:
            raise BillingError(503, "Credit-pack checkout is not enabled. Contact the operator.")
        if pack not in PACK_DATA:
            raise BillingError(422, "Choose a supported credit pack.")
        wid, _ = self._owner(user)
        async with self._locks.setdefault(wid, asyncio.Lock()):
            _, account = self._owner(user)
            price = await self._call("GET", "/v1/prices/" + identifier(self.pack_price_ids[pack], "price"))
            self._validate_pack_price(price, pack, active=True)
            customer = account["customer_id"]
            if not customer:
                created = await self._call("POST", "/v1/customers", data={
                    "metadata[workspace_id]": wid, "metadata[user_id]": user["id"],
                }, key="branchline-customer-" + wid)
                customer = identifier(created.get("id"), "cus")
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_accounts SET customer_id=? WHERE workspace_id=? AND customer_id IS NULL", (customer, wid))
                customer = self._account(wid)["customer_id"]
            now = int(time.time())
            with self.store.connection() as db:
                existing = db.execute("SELECT * FROM billing_pack_checkouts WHERE workspace_id=? AND (status='processing' OR (status='open' AND expires_at>?)) ORDER BY expires_at DESC LIMIT 1", (wid, now)).fetchone()
            if existing:
                order = dict(existing)
                if order["status"] == "processing":
                    raise BillingError(409, "Your previous credit-pack payment is still processing. Wait for your balance to update or contact the operator.")
                if order["pack"] != pack:
                    raise BillingError(409, "A checkout is already open for another credit pack. Complete it or wait for it to expire.")
                if order["session_id"]:
                    session = await self._call("GET", "/v1/checkout/sessions/" + identifier(order["session_id"], "cs"))
                    if session.get("status") == "open":
                        return self._hosted_url(session.get("url"), "checkout.stripe.com")
                    raise BillingError(409, "This checkout has finished. Wait for your balance to update.")
            else:
                order = {"checkout_key": "branchline-pack-" + uuid.uuid4().hex, "expires_at": now + 3600, "pack": pack}
                with self.store.connection(write=True) as db:
                    db.execute("INSERT INTO billing_pack_checkouts(checkout_key,workspace_id,user_id,pack,expires_at) VALUES(?,?,?,?,?)", (order["checkout_key"], wid, user["id"], pack, order["expires_at"]))
            session = await self._call("POST", "/v1/checkout/sessions", data={
                "mode": "payment", "customer": customer, "client_reference_id": wid,
                "metadata[purchase_kind]": "credit_pack", "metadata[workspace_id]": wid,
                "metadata[user_id]": user["id"], "metadata[pack]": pack,
                "metadata[checkout_key]": order["checkout_key"],
                "line_items[0][price]": self.pack_price_ids[pack], "line_items[0][quantity]": "1",
                "payment_method_types[0]": "card",
                "success_url": self.public_url + "/#plans", "cancel_url": self.public_url + "/#plans",
                "expires_at": str(order["expires_at"]),
            }, key=order["checkout_key"])
            sid = identifier(session.get("id"), "cs")
            url = self._hosted_url(session.get("url"), "checkout.stripe.com")
            with self.store.connection(write=True) as db:
                db.execute("UPDATE billing_pack_checkouts SET session_id=? WHERE checkout_key=? AND (session_id IS NULL OR session_id=?)", (sid, order["checkout_key"], sid))
            return url

    async def _fulfill_pack(self, event, session):
        """Canonical paid session + bound order + atomic grant, never a redirect."""
        sid = identifier(session.get("id"), "cs")
        metadata = session.get("metadata") or {}
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM billing_pack_checkouts WHERE session_id=? OR checkout_key=?", (sid, metadata.get("checkout_key", ""))).fetchone()
        if not row:
            return {"received": True, "ignored": True}
        order = dict(row)
        pack, wid = order["pack"], order["workspace_id"]
        account = self._account(wid)
        if (not account or pack not in PACK_DATA or
            order["session_id"] not in (None, sid) or session.get("mode") != "payment" or
            metadata.get("purchase_kind") != "credit_pack" or
            metadata.get("workspace_id") != wid or metadata.get("user_id") != order["user_id"] or
            metadata.get("pack") != pack or metadata.get("checkout_key") != order["checkout_key"] or
            session.get("client_reference_id") != wid or
            identifier(session.get("customer"), "cus") != account["customer_id"]):
            raise BillingError(400, "The credit-pack payment does not match its workspace.")
        if session.get("status") != "complete" or session.get("payment_status") != "paid":
            if session.get("status") == "complete":
                # Checkout expiry is not payment settlement. A delayed payment
                # can succeed later, so retain this hold until paid/reconciled.
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE billing_pack_checkouts SET session_id=?,status='processing' WHERE checkout_key=? AND credits_granted=0 AND (session_id IS NULL OR session_id=?)", (sid, order["checkout_key"], sid))
            return {"received": True, "pending": True}
        price = await self._call("GET", "/v1/prices/" + identifier(self.pack_price_ids[pack], "price"))
        self._validate_pack_price(price, pack)
        lines = session.get("line_items")
        if not isinstance(lines, dict):
            lines = await self._call("GET", "/v1/checkout/sessions/" + sid + "/line_items", params={"limit": 100})
        items = lines.get("data") or []
        amount = PACK_DATA[pack]["price_aud"] * 100
        if (lines.get("has_more") or len(items) != 1 or items[0].get("quantity") != 1 or
            (items[0].get("price") or {}).get("id") != self.pack_price_ids[pack] or
            session.get("currency") != "aud" or session.get("amount_subtotal") != amount or
            not isinstance(session.get("amount_total"), int) or session["amount_total"] < amount):
            raise BillingError(400, "The credit-pack amount or line items require reconciliation.")
        payment_intent = identifier(session.get("payment_intent"), "pi")
        with self.store.connection(write=True) as db:
            if db.execute("SELECT 1 FROM billing_events WHERE id=?", (event["id"],)).fetchone():
                return {"received": True, "duplicate": True}
            current = db.execute("SELECT * FROM billing_pack_checkouts WHERE checkout_key=?", (order["checkout_key"],)).fetchone()
            ws = db.execute("SELECT blocked FROM workspaces WHERE id=?", (wid,)).fetchone()
            ignored = not ws or bool(ws["blocked"])
            if not ignored and not current["credits_granted"]:
                other = db.execute("SELECT 1 FROM billing_pack_checkouts WHERE payment_intent=? AND checkout_key!=?", (payment_intent, order["checkout_key"])).fetchone()
                if other:
                    raise BillingError(400, "This payment has already been reconciled.")
                db.execute("UPDATE workspaces SET credits=credits+? WHERE id=? AND blocked=0", (PACK_DATA[pack]["credits"], wid))
                db.execute("UPDATE billing_pack_checkouts SET session_id=?,status='paid',credits_granted=?,payment_intent=? WHERE checkout_key=?", (sid, PACK_DATA[pack]["credits"], payment_intent, order["checkout_key"]))
            db.execute("INSERT INTO billing_events VALUES(?,?,?,?)", (event["id"], event["type"], event["created"], int(time.time())))
        return {"received": True, "ignored": ignored}

    def _verify(self, raw, signature):
        try:
            if not isinstance(signature, str) or len(signature) > 4096:
                raise ValueError("Signature missing")
            parts = [part.split("=", 1) for part in signature.split(",")]
            timestamps = [v for k, v in parts if k == "t"]
            signatures = [v for k, v in parts if k == "v1"]
            if len(timestamps) != 1:
                raise ValueError("Invalid timestamp")
            stamp = int(timestamps[0])
            if abs(time.time() - stamp) > 300:
                raise ValueError("Expired signature")
            digest = hmac.new(self.webhook_secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
            if not any(hmac.compare_digest(digest, value) for value in signatures):
                raise ValueError("Invalid signature")
            event = json.loads(raw)
            if not isinstance(event, dict) or not isinstance(event.get("created"), int):
                raise ValueError("Invalid event")
            identifier(event.get("id"), "evt")
            expected_live = self.secret.startswith(("sk_live_", "rk_live_"))
            if event.get("livemode") is not expected_live:
                raise ValueError("Wrong billing mode")
            return event
        except (ValueError, TypeError, UnicodeError, BillingError) as exc:
            raise BillingError(400, "Invalid billing webhook signature or event.") from exc

    @staticmethod
    def _invoice_subscription(invoice):
        parent = invoice.get("parent") or {}
        details = parent.get("subscription_details") or {}
        if details and parent.get("type") != "subscription_details":
            raise BillingError(400, "The invoice parent is invalid.")
        return identifier(details.get("subscription") or invoice.get("subscription"), "sub")

    async def webhook(self, raw, signature):
        self.require_configured()
        event = self._verify(raw, signature)
        eid, etype = event["id"], event.get("type")
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM billing_events WHERE id=?", (eid,)).fetchone():
                return {"received": True, "duplicate": True}
        if etype not in EVENT_TYPES:
            return {"received": True, "ignored": True}
        if event.get("api_version") != API_VERSION:
            raise BillingError(400, "Configure the billing webhook API version to " + API_VERSION + ".")
        obj = (event.get("data") or {}).get("object")
        if not isinstance(obj, dict):
            raise BillingError(400, "The billing webhook object is invalid.")
        invoice = None
        if etype.startswith("invoice."):
            invoice = await self._call("GET", "/v1/invoices/" + identifier(obj.get("id"), "in"))
            # Ignore unrelated non-subscription invoices in the same Stripe account.
            if not invoice.get("subscription") and not (invoice.get("parent") or {}).get("subscription_details"):
                return {"received": True, "ignored": True}
            sid = self._invoice_subscription(invoice)
            customer = identifier(invoice.get("customer"), "cus")
        elif etype in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
            session = await self._call("GET", "/v1/checkout/sessions/" + identifier(obj.get("id"), "cs"), params={"expand[]": "line_items"})
            if session.get("mode") == "payment":
                return await self._fulfill_pack(event, session)
            if session.get("mode") != "subscription" or session.get("status") != "complete":
                return {"received": True, "ignored": True}
            if etype != "checkout.session.completed":
                return {"received": True, "ignored": True}
            sid, customer = identifier(session.get("subscription"), "sub"), identifier(session.get("customer"), "cus")
        else:
            sid, customer = identifier(obj.get("id"), "sub"), identifier(obj.get("customer"), "cus")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM billing_accounts WHERE customer_id=?", (customer,)).fetchone()
        if not row:
            return {"received": True, "ignored": True}
        account = dict(row)
        subscription = await self._call("GET", "/v1/subscriptions/" + sid)
        metadata = subscription.get("metadata") or {}
        if (identifier(subscription.get("id"), "sub") != sid or
            identifier(subscription.get("customer"), "cus") != customer or
            metadata.get("workspace_id") != account["workspace_id"] or
            metadata.get("user_id") != account["user_id"]):
            raise BillingError(400, "The subscription does not match the billing workspace.")
        items = (subscription.get("items") or {}).get("data") or []
        if len(items) != 1 or items[0].get("quantity") != 1:
            raise BillingError(400, "Unsupported subscription configuration. Contact the operator.")
        item = items[0]
        plan = self._plan_for_price(item.get("price"))
        price = await self._call("GET", "/v1/prices/" + self.price_ids[plan])
        self._validate_price(price, plan)
        start = item.get("current_period_start", subscription.get("current_period_start", 0))
        end = item.get("current_period_end", subscription.get("current_period_end", 0))
        created = subscription.get("created")
        if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in (start, end, created)) or end <= start:
            raise BillingError(400, "The subscription period is invalid.")
        status = subscription.get("status")
        if status not in {"active", "trialing", "past_due", "incomplete", *REVOKED}:
            raise BillingError(400, "The subscription status needs operator attention.")
        replace_allowed = False
        if account["subscription_id"] and account["subscription_id"] != sid:
            previous = await self._call("GET", "/v1/subscriptions/" + identifier(account["subscription_id"], "sub"))
            replace_allowed = (previous.get("status") in TERMINAL_SUBSCRIPTIONS and
                               identifier(previous.get("customer"), "cus") == customer)
        grant = None
        if etype == "invoice.paid" and invoice.get("status") == "paid" and status == "active":
            if invoice.get("billing_reason") in {"subscription_create", "subscription_cycle"}:
                lines = invoice.get("lines") or {}
                data = lines.get("data") or []
                if lines.get("has_more") or len(data) != 1:
                    raise BillingError(400, "The invoice requires billing reconciliation.")
                line = data[0]
                detail = (line.get("parent") or {}).get("subscription_item_details") or {}
                price_id = ((line.get("pricing") or {}).get("price_details") or {}).get("price")
                price_id = price_id or line.get("price")
                invoice_plan = self._plan_for_price(price_id)
                period = line.get("period") or {}
                if ((line.get("parent") or {}).get("type") != "subscription_item_details" or
                    invoice_plan != plan or line.get("quantity") != 1 or line.get("proration") or detail.get("proration") or
                    invoice.get("currency") != "aud" or period.get("start") != start or period.get("end") != end):
                    # A delayed old invoice or a proration cannot refill a newer period.
                    grant = None
                elif end > int(time.time()):
                    grant = {"invoice": identifier(invoice.get("id"), "in"), "credits": PLAN_DATA[plan]["credits"]}
        return self._apply(event, account, sid, created, plan, status, start, end,
                           bool(subscription.get("cancel_at_period_end")), grant, replace_allowed)

    def _apply(self, event, account, sid, created, plan, status, start, end, cancel_at_end, grant, replace_allowed=False):
        """One transaction protects event replay, invoice replay, periods and credit use."""
        wid, eid = account["workspace_id"], event["id"]
        with self.store.connection(write=True) as db:
            if db.execute("SELECT 1 FROM billing_events WHERE id=?", (eid,)).fetchone():
                return {"received": True, "duplicate": True}
            current = db.execute("SELECT * FROM billing_accounts WHERE workspace_id=?", (wid,)).fetchone()
            ws = db.execute("SELECT blocked FROM workspaces WHERE id=?", (wid,)).fetchone()
            ignored = not ws or bool(ws["blocked"])
            different = current["subscription_id"] and current["subscription_id"] != sid
            replacement_verified = replace_allowed and current["subscription_id"] == account["subscription_id"]
            if different and ((current["status"] not in TERMINAL_SUBSCRIPTIONS and not replacement_verified) or created < current["subscription_created"]):
                ignored = True
            stale = not different and event["created"] < current["event_created"]
            # Revoked subscription state can never be revived by a delayed paid snapshot.
            if stale and current["status"] in REVOKED:
                ignored = True
            if not ignored:
                if not stale:
                    db.execute("""UPDATE billing_accounts SET subscription_id=?,subscription_created=?,plan=?,status=?,
                      current_period_start=?,current_period_end=?,cancel_at_period_end=?,event_created=?,
                      checkout_key=NULL,checkout_plan=NULL,checkout_expires=NULL,checkout_session=NULL,checkout_url=NULL
                      WHERE workspace_id=?""", (sid, created, plan, status, start, end, int(cancel_at_end), event["created"], wid))
                if status in REVOKED and not stale:
                    # Revocation removes only the subscription allowance. The
                    # customer's purchased/operator and free pools remain usable.
                    db.execute("UPDATE workspaces SET subscription_credits=0,subscription_expires_at=1 WHERE id=? AND blocked=0", (wid,))
                elif grant:
                    latest = db.execute("SELECT MAX(period_start) FROM billing_credit_ledger WHERE workspace_id=?", (wid,)).fetchone()[0]
                    if latest is None or start >= latest:
                        changed = db.execute("""INSERT OR IGNORE INTO billing_credit_ledger
                          (invoice_id,event_id,workspace_id,subscription_id,period_start,period_end,plan,credits)
                          VALUES (?,?,?,?,?,?,?,?)""", (grant["invoice"], eid, wid, sid, start, end, plan, grant["credits"])).rowcount
                        if changed:
                            db.execute("UPDATE workspaces SET subscription_credits=?,subscription_expires_at=? WHERE id=? AND blocked=0", (grant["credits"], end, wid))
            db.execute("INSERT INTO billing_events VALUES (?,?,?,?)", (eid, event["type"], event["created"], int(time.time())))
        return {"received": True, "ignored": ignored}
