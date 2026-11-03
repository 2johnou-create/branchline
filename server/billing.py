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
    "solo": {"id": "solo", "name": "Solo", "price_aud": 49, "credits": 30, "monthly_credits": 30, "interval": "month"},
    "studio": {"id": "studio", "name": "Studio", "price_aud": 199, "credits": 150, "monthly_credits": 150, "interval": "month"},
    "agency": {"id": "agency", "name": "Agency", "price_aud": 599, "credits": 500, "monthly_credits": 500, "interval": "month"},
}
REVOKED = {"canceled", "unpaid", "incomplete_expired", "paused"}
TERMINAL_SUBSCRIPTIONS = {"canceled", "incomplete_expired"}
EVENT_TYPES = {"checkout.session.completed", "customer.subscription.created",
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
            """)

    @property
    def configured(self):
        parsed = urlparse(self.public_url)
        return bool(self.secret and self.webhook_secret and
                    all(self.price_ids.values()) and len(set(self.price_ids.values())) == 3 and
                    parsed.scheme == "https" and parsed.netloc and not parsed.query and not parsed.fragment)

    @property
    def enabled(self):
        return bool(self.configured and getattr(self.settings, "billing_enabled", False) and
                    getattr(self.settings, "engine_enabled", False))

    @property
    def plans(self):
        return [dict(p) for p in PLAN_DATA.values()]

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
            yield

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
        elif etype == "checkout.session.completed":
            session = await self._call("GET", "/v1/checkout/sessions/" + identifier(obj.get("id"), "cs"))
            if session.get("mode") != "subscription" or session.get("status") != "complete":
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
                    # blocked is reserved for account deletion; expiry=1 disables compute.
                    db.execute("UPDATE workspaces SET credits=0,subscription_expires_at=1 WHERE id=? AND blocked=0", (wid,))
                elif grant:
                    latest = db.execute("SELECT MAX(period_start) FROM billing_credit_ledger WHERE workspace_id=?", (wid,)).fetchone()[0]
                    if latest is None or start >= latest:
                        changed = db.execute("""INSERT OR IGNORE INTO billing_credit_ledger
                          (invoice_id,event_id,workspace_id,subscription_id,period_start,period_end,plan,credits)
                          VALUES (?,?,?,?,?,?,?,?)""", (grant["invoice"], eid, wid, sid, start, end, plan, grant["credits"])).rowcount
                        if changed:
                            db.execute("UPDATE workspaces SET credits=?,subscription_expires_at=? WHERE id=? AND blocked=0", (grant["credits"], end, wid))
            db.execute("INSERT INTO billing_events VALUES (?,?,?,?)", (eid, event["type"], event["created"], int(time.time())))
        return {"received": True, "ignored": ignored}
