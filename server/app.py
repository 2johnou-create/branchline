"""Authenticated, tenant-isolated gateway for an operator-managed pilot."""
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path
from typing import Literal
import uuid
import time
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .auth import Auth, EmailBody, LoginBody, PasswordBody, RegisterBody, ResetBody, TokenBody, hash_password, verify_password
from .billing import Billing, BillingError
from .engine import Engine, EngineFailure
from .store import ACTIVE, FREE_ALLOWANCE, FREE_INTERVAL_SECONDS, Store, QuotaExceeded

logger = logging.getLogger("branchline")

PRIVACY_NOTES = [
    "Gateway request and report content is encrypted at rest; authorised inference services process plaintext.",
    "MiroFish stores source documents and simulation artifacts on its private engine disk. Host disk encryption and operator access controls are required.",
    "Real runs send context to the operator's LLM provider and Zep Cloud; their retention policies apply, including backups.",
    "Gateway retention does not guarantee erasure of engine logs, simulation profiles, provider logs or backups.",
    "Synthetic participants are not real customer research; validate findings with people before making decisions.",
]


class PrivacyOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retention_days: int = Field(default=7, ge=1, le=30)


class NewRun(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=10, max_length=4000)
    context: str = Field(min_length=20, max_length=30000)
    audience: str = Field(min_length=1, max_length=1000)
    rounds: int = Field(default=5, ge=1, le=20, strict=True)
    template: str = Field(default="custom", max_length=80)
    privacy: PrivacyOptions = Field(default_factory=PrivacyOptions)
    consent_external_processing: Literal[True]


def public_run(row):
    private = row["private"]
    request = private["request"]
    return {
        "id": row["id"], "title": request["title"], "question": request["question"],
        "audience": request["audience"], "rounds": request["rounds"], "template": request.get("template", "custom"),
        "status": row["status"], "stage": row["stage"], "progress": row["progress"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "expires_at": row["expires_at"],
        "credits_reserved": row["credits_reserved"], "result": private.get("result"), "error": private.get("error"),
        "telemetry": public_telemetry(private.get("telemetry", {})),
        "privacy_receipt": {"processors": ["Branchline gateway", "Private MiroFish engine", "Operator-configured LLM provider", "Zep Cloud"],
                            "gateway_retention_days": request.get("privacy", {}).get("retention_days", 7),
                            "notes": PRIVACY_NOTES},
    }


def public_telemetry(value):
    """Publish observed counts and workflow timestamps, never provider bodies."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("agents_total", "entities_count", "agents_active", "current_round", "total_rounds", "actions_count"):
        number = value.get(key)
        if isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= 1_000_000_000:
            result[key] = number
    for key in ("observed_at", "stage_started_at"):
        timestamp = value.get(key)
        if isinstance(timestamp, str) and len(timestamp) <= 64:
            try:
                datetime.fromisoformat(timestamp)
            except ValueError:
                continue
            result[key] = timestamp
    if value.get("source") in ("gateway", "mirofish"):
        result["source"] = value["source"]
    if value.get("runner_status") in ("idle", "starting", "running", "paused", "stopping", "stopped", "completed", "failed"):
        result["runner_status"] = value["runner_status"]
    timeline = value.get("timeline")
    if isinstance(timeline, list):
        result["timeline"] = [{"stage": item["stage"][:100], "status": item["status"], "at": item["at"][:64]}
                              for item in timeline[-12:] if isinstance(item, dict)
                              and isinstance(item.get("stage"), str) and isinstance(item.get("at"), str)
                              and item.get("status") in (*ACTIVE, "completed", "failed", "interrupted", "cancelled")]
    return result


def create_app(settings=None, *, engine=None, launch_jobs=True, mailer=None, billing=None):
    settings = settings or Settings.from_env()
    os.umask(0o077)
    store = Store(settings.database, settings.encryption_key)
    engine = engine or Engine(settings)
    auth = Auth(settings, store, mailer=mailer)
    billing = billing or Billing(settings, store)
    jobs = set()
    worker_id = str(uuid.uuid4())

    async def execute(wid, rid, payload):
        initial = store.get(wid, rid)
        timeline = [{"stage": "Queued", "status": "queued", "at": initial["created_at"]}] if initial else []
        stage = "Queued"
        status = "queued"
        stage_started_at = initial["created_at"] if initial else datetime.now(timezone.utc).isoformat()

        def update(**changes):
            nonlocal stage, status, stage_started_at
            status = changes.get("status", status)
            now = datetime.now(timezone.utc).isoformat()
            if changes.get("stage") and changes["stage"] != stage:
                stage = changes["stage"]
                stage_started_at = now
                timeline.append({"stage": stage, "status": status, "at": now})
            telemetry = changes.pop("telemetry", {})
            telemetry.update({"stage_started_at": stage_started_at, "observed_at": now, "timeline": timeline[-12:]})
            changes["telemetry"] = telemetry
            store.update(wid, rid, **changes)
        try:
            async with asyncio.timeout(settings.job_timeout):
                result = await engine.run(payload, update)
            update(status="completed", stage="Report ready", progress=100, result=result)
        except asyncio.CancelledError:
            update(status="interrupted", stage="Gateway stopped", error="The gateway stopped during this run. Ask the operator to review upstream jobs before retrying.")
            raise
        except TimeoutError:
            row = store.get(wid, rid)
            if row:
                await engine.stop(row["private"]["upstream"])
            update(status="failed", stage="Time limit reached", error="This run exceeded its time limit. Ask the operator to verify upstream cleanup.")
        except EngineFailure as exc:
            row = store.get(wid, rid)
            if row:
                await engine.stop(row["private"]["upstream"])
            update(status="failed", stage="Run failed", error=str(exc))
        except Exception:
            # Do not serialize exceptions: provider bodies can contain user content.
            logger.error("Simulation job failed; run_id=%s", rid)
            row = store.get(wid, rid)
            if row:
                await engine.stop(row["private"]["upstream"])
            update(status="failed", stage="Run failed", error="An internal processing error occurred. Contact the workspace operator.")
        finally:
            store.finish_job(rid, worker_id)

    async def supervise():
        last_heartbeat = 0
        while True:
            while len(jobs) < settings.max_active_global:
                row = store.claim_next(worker_id)
                if not row:
                    break
                task = asyncio.create_task(execute(row["workspace_id"], row["id"], row["private"]["request"]))
                jobs.add(task)
                task.add_done_callback(jobs.discard)
            if time.monotonic() - last_heartbeat > 20:
                for row in store.all_active():
                    store.heartbeat(row["id"], worker_id)
                last_heartbeat = time.monotonic()
                await recover_claimed()
            await asyncio.sleep(.2)

    async def recover_claimed():
        for row in store.claim_interrupted_jobs(worker_id):
            await engine.stop(row["private"]["upstream"])
            store.update(row["workspace_id"], row["id"], status="interrupted", stage="Gateway restarted",
                         error="The gateway lost this run's execution lease. Ask the operator to review upstream jobs before retrying.")
            store.finish_job(row["id"], worker_id)

    async def delete_row(row):
        receipt = await engine.cleanup(row["private"]["upstream"])
        cid = store.delete_with_cleanup_ledger(row["workspace_id"], row["id"], row["private"]["upstream"], receipt)
        return {"id": row["id"], "gateway_deleted": True, "upstream_cleanup": receipt,
                "cleanup_task_id": cid, "cleanup_pending": cid is not None,
                "notes": ["Deleted content may remain in operator backups until backup expiry.",
                          "Upstream deletion acknowledgements are not proof of provider backup erasure.",
                          "Engine artifact deletion is attempted when the hardened cleanup service is configured. Unresolved copies require operator attention.",
                          "Minimal encrypted upstream references are retained in the cleanup ledger while remediation is pending; the customer brief and report are removed."]}

    async def retention_loop():
        while True:
            auth.expire_ephemeral()
            for row in store.expired():
                try:
                    await delete_row(row)
                except Exception:
                    logger.error("Retention cleanup needs operator attention; run_id=%s", row["id"])
            for task in store.cleanup_tasks()[:3]:
                try:
                    receipt = await engine.cleanup(task["private"]["upstream"])
                    store.update_cleanup(task["id"], receipt)
                    if not any(v == "operator_cleanup_required" for v in receipt.values()):
                        store.resolve_cleanup(task["id"])
                except Exception:
                    logger.error("Upstream erasure retry needs operator attention; cleanup_id=%s", task["id"])
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        # Accepted queued jobs survive restart. Claimed jobs may have triggered paid
        # upstream work, so they are interrupted rather than silently replayed.
        await recover_claimed()
        retention = asyncio.create_task(retention_loop())
        supervisor = asyncio.create_task(supervise()) if launch_jobs else None
        yield
        retention.cancel()
        if supervisor:
            supervisor.cancel()
        for task in list(jobs):
            task.cancel()
        await asyncio.gather(retention, *([supervisor] if supervisor else []), *list(jobs), return_exceptions=True)

    app = FastAPI(title="Branchline Gateway", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.engine = engine
    app.state.auth = auth
    app.state.billing = billing
    if settings.enforce_host:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(settings.public_url).hostname, "localhost", "127.0.0.1"])
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"],
                       allow_credentials=False, max_age=600)
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def limits(request, call_next):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 100_000):
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        # Bound chunked bodies too; do not trust Content-Length.
        if request.method in ("POST", "PUT", "PATCH"):
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 100_000:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI defaults echo invalid user inputs; return only field paths/messages.
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]}, status_code=422)

    @app.exception_handler(BillingError)
    async def billing_error(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    async def account_user(request: Request):
        user = auth.session_user(request)
        if not user:
            raise HTTPException(401, "Sign in to your Branchline account")
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            auth.csrf(request)
        return user

    async def workspace(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if credentials:
            if credentials.scheme.lower() != "bearer" or len(credentials.credentials) > 512:
                raise HTTPException(401, "A valid workspace token is required", headers={"WWW-Authenticate": "Bearer"})
            row = store.workspace(credentials.credentials)
        else:
            user = await account_user(request)
            row = {"id": user["workspace_id"], "name": user["workspace_name"], "credits": user["credits"],
                   "credit_wallet": user["credit_wallet"]}
        if not row:
            raise HTTPException(401, "A valid workspace token is required", headers={"WWW-Authenticate": "Bearer"})
        if not store.allow_request(row["id"], settings.requests_per_minute):
            raise HTTPException(429, "Workspace request limit reached. Try again shortly.", headers={"Retry-After": "60"})
        return row

    def account_result(user, raw_session):
        return {"user": {"id": user["id"], "email": user["email"], "name": user["name"], "email_verified": bool(user["email_verified"])},
                "workspace": {"id": user["workspace_id"], "name": user["workspace_name"]},
                "credits_remaining": user["credits"], "subscription": billing.summary(user["workspace_id"]),
                "credit_wallet": user["credit_wallet"],
                "csrf_token": auth.csrf_token(raw_session)}

    @app.get("/api/v1/config")
    async def public_config():
        return {"mode": "selfhost", "auth": {"enabled": True, "signup_enabled": auth.signup_enabled,
                "signup_restricted": bool(settings.signup_allowed_emails),
                "email_verification_required": settings.require_email_verification, "email_delivery_ready": auth.mailer.ready},
                "billing": {"enabled": billing.enabled, "plans": billing.plans, "packs": billing.packs,
                            "packs_enabled": billing.packs_enabled,
                            "free_plan": {"credits": FREE_ALLOWANCE, "capacity": FREE_ALLOWANCE,
                                          "interval_hours": FREE_INTERVAL_SECONDS // 3600}},
                "engine": {"configured": settings.engine_enabled, "verified": False}}

    @app.post("/api/v1/auth/register")
    async def register(body: RegisterBody, request: Request, response: Response):
        auth.origin(request)
        auth.limit(request, "register", body.email, count=3, seconds=3600, ip_count=30)
        if not auth.signup_enabled:
            raise HTTPException(503, "Account registration requires configured verification email delivery")
        if settings.signup_allowed_emails and body.email not in settings.signup_allowed_emails:
            raise HTTPException(403, "Registration is limited to approved pilot email addresses.")
        encoded = await auth.password_work(hash_password, body.password)
        user = auth.create_user(body, encoded)
        if settings.require_email_verification:
            existing = user or auth.user(email=body.email)
            if existing and not existing["email_verified"]:
                await auth.send_token(existing, "verify")
            response.status_code = 202
            return {"status": "verification_required", "message": "If this address can be registered, a verification link has been sent. Check your inbox or sign in."}
        if not user:
            raise HTTPException(409, "This account cannot be registered. Try signing in or resetting your password.")
        response.status_code = 201
        return account_result(user, auth.session(user, response))

    @app.post("/api/v1/auth/login")
    async def login(body: LoginBody, request: Request, response: Response):
        auth.origin(request)
        auth.limit(request, "login", body.email)
        user = auth.user(email=body.email)
        valid = await auth.password_work(verify_password, body.password, user["password_hash"] if user else auth.dummy_hash)
        if not user or not valid:
            raise HTTPException(401, "Email or password is incorrect")
        if not user["email_verified"]:
            raise HTTPException(403, "Verify your email before signing in. Register again to resend a verification link.")
        return account_result(user, auth.session(user, response))

    @app.get("/api/v1/auth/me")
    async def me(request: Request, user=Depends(account_user)):
        return account_result(user, request.cookies[auth.cookie_name])

    @app.post("/api/v1/auth/logout", status_code=204)
    async def logout(request: Request, user=Depends(account_user)):
        response = Response(status_code=204)
        auth.logout(request, response)
        return response

    @app.post("/api/v1/auth/verify")
    async def verify(body: TokenBody, request: Request, response: Response):
        auth.origin(request)
        auth.limit(request, "verify", count=12)
        user = auth.consume_token(body.token, "verify")
        return account_result(user, auth.session(user, response))

    @app.post("/api/v1/auth/forgot-password", status_code=202)
    async def forgot_password(body: EmailBody, request: Request):
        auth.origin(request)
        auth.limit(request, "reset", body.email, count=3, seconds=3600, ip_count=30)
        if not auth.mailer.ready:
            raise HTTPException(503, "Password recovery requires configured email delivery")
        user = auth.user(email=body.email)
        if user:
            await auth.send_token(user, "reset")
        return {"message": "If this account exists, a password reset link has been sent."}

    @app.post("/api/v1/auth/reset-password")
    async def reset_password(body: ResetBody, request: Request):
        auth.origin(request)
        auth.limit(request, "reset-confirm", count=12)
        if not auth.token_valid(body.token, "reset"):
            raise HTTPException(400, "This link has expired or has already been used")
        encoded = await auth.password_work(hash_password, body.password)
        auth.consume_token(body.token, "reset", password_hash=encoded)
        return {"message": "Your password has been changed. Sign in again."}

    @app.get("/api/v1/account/export")
    async def account_export(request: Request, user=Depends(account_user)):
        with store.connection() as db:
            rows = [store.unpack(r) for r in db.execute("SELECT * FROM runs WHERE workspace_id=? ORDER BY created_at", (user["workspace_id"],)).fetchall()]
        result = account_result(user, request.cookies[auth.cookie_name])
        result.pop("csrf_token", None)
        return {"account": result, "runs": [{**public_run(row), "context": row["private"]["request"]["context"]} for row in rows]}

    @app.delete("/api/v1/account")
    async def account_delete(body: PasswordBody, request: Request, user=Depends(account_user)):
        auth.limit(request, "delete", count=5)
        if not await auth.password_work(verify_password, body.password, user["password_hash"]):
            raise HTTPException(401, "Password is incorrect")
        async with billing.deletion_guard(user):
            pending = auth.freeze_account(user)
        response = JSONResponse({"account_deleted": True, "gateway_content_deleted": True,
            "cleanup_pending": bool(pending), "cleanup_task_ids": pending,
            "notes": ["Minimal encrypted resource references remain while upstream erasure is pending.",
                      "A keyed email marker can remain until the next 48-hour free-credit refresh to prevent duplicate free grants; it contains no raw email address.",
                      "Payment transaction records may be retained for accounting; provider backups follow their own retention policies."]})
        auth.logout(request, response)
        return response

    class CheckoutBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        plan: Literal["solo", "studio", "agency"]

    @app.post("/api/v1/billing/checkout")
    async def checkout(body: CheckoutBody, user=Depends(account_user)):
        return {"url": await billing.checkout(user, body.plan)}

    class PackBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        pack: Literal["spark", "boost", "reserve"]

    @app.post("/api/v1/billing/pack")
    async def checkout_pack(body: PackBody, user=Depends(account_user)):
        return {"url": await billing.checkout_pack(user, body.pack)}

    @app.post("/api/v1/billing/portal")
    async def portal(user=Depends(account_user)):
        return {"url": await billing.portal(user)}

    @app.post("/api/v1/billing/webhook")
    async def stripe_webhook(request: Request):
        return await billing.webhook(await request.body(), request.headers.get("stripe-signature", ""))

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "branchline"}

    @app.get("/api/v1/capabilities")
    async def capabilities(ws=Depends(workspace)):
        return {"workspace": {"id": ws["id"], "name": ws["name"]},
                "usage": {"credits_remaining": ws["credits"], "max_rounds": settings.max_rounds,
                          "credit_wallet": ws.get("credit_wallet") or store.wallet(ws["id"]),
                          "max_active_runs": settings.max_active_runs, "credit_cost_formula": "1 + rounds",
                          "max_agents": settings.max_agents},
                "privacy": {"gateway_encryption": True, "upstream_processors": ["Operator-configured LLM provider", "Zep Cloud"], "notes": PRIVACY_NOTES},
                "billing": {"enabled": billing.enabled, "packs_enabled": billing.packs_enabled,
                            "mode": "subscription" if billing.enabled else "operator-managed"}}

    class QuoteBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        rounds: int = Field(ge=1, le=20, strict=True)

    @app.post("/api/v1/runs/quote")
    async def quote_run(body: QuoteBody, ws=Depends(workspace)):
        if body.rounds > settings.max_rounds:
            raise HTTPException(422, "Round count exceeds the workspace limit")
        return {"credits_required": 1 + body.rounds, "credits_remaining": ws["credits"],
                "credit_wallet": ws.get("credit_wallet") or store.wallet(ws["id"]),
                "sufficient": ws["credits"] >= 1 + body.rounds}

    @app.post("/api/v1/runs", status_code=202)
    async def create_run(body: NewRun, ws=Depends(workspace)):
        if not settings.engine_enabled:
            raise HTTPException(503, "Real simulations are not enabled on this deployment")
        if body.rounds > settings.max_rounds:
            raise HTTPException(422, "Round count exceeds the workspace limit")
        payload = body.model_dump()
        try:
            rid = store.reserve(ws["id"], payload, settings.max_active_runs, settings.max_active_global)
        except QuotaExceeded as exc:
            raise HTTPException(429, str(exc)) from exc
        return public_run(store.get(ws["id"], rid))

    @app.get("/api/v1/runs")
    async def list_runs(ws=Depends(workspace)):
        return {"runs": [public_run(row) for row in store.list(ws["id"])]}

    @app.get("/api/v1/runs/{rid}")
    async def get_run(rid: str, ws=Depends(workspace)):
        row = store.get(ws["id"], rid)
        if not row:
            raise HTTPException(404, "Run not found")
        return public_run(row)

    @app.get("/api/v1/runs/{rid}/brief")
    async def get_owned_brief(rid: str, ws=Depends(workspace)):
        row = store.get(ws["id"], rid)
        if not row:
            raise HTTPException(404, "Run not found")
        original = row["private"]["request"]
        # An explicit owner action can reuse their context without exposing it
        # in every library poll. Prior consent is never carried to a new run.
        return {"source_run_id": rid,
                "brief": {key: original[key] for key in ("title", "question", "context", "audience", "rounds", "template", "privacy") if key in original}}

    @app.delete("/api/v1/runs/{rid}")
    async def delete_run(rid: str, ws=Depends(workspace)):
        row = store.get(ws["id"], rid)
        if not row:
            raise HTTPException(404, "Run not found")
        if row["status"] in ACTIVE:
            raise HTTPException(409, "Wait for the run to finish before deleting it")
        return await delete_row(row)

    if Path(settings.static_directory).is_dir():
        app.mount("/", StaticFiles(directory=settings.static_directory, html=True), name="frontend")
    return app

