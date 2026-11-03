"""Authenticated, tenant-isolated gateway for an operator-managed pilot."""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .engine import Engine, EngineFailure
from .store import ACTIVE, Store, QuotaExceeded

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
        "privacy_receipt": {"processors": ["Branchline gateway", "Private MiroFish engine", "Operator-configured LLM provider", "Zep Cloud"],
                            "gateway_retention_days": request.get("privacy", {}).get("retention_days", 7),
                            "notes": PRIVACY_NOTES},
    }


def create_app(settings=None, *, engine=None, launch_jobs=True):
    settings = settings or Settings.from_env()
    os.umask(0o077)
    store = Store(settings.database, settings.encryption_key)
    engine = engine or Engine(settings)
    jobs = set()

    async def execute(wid, rid, payload):
        def update(**changes):
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

    async def delete_row(row):
        receipt = await engine.cleanup(row["private"]["upstream"])
        cid = store.delete_with_cleanup_ledger(row["workspace_id"], row["id"], row["private"]["upstream"], receipt)
        return {"id": row["id"], "gateway_deleted": True, "upstream_cleanup": receipt,
                "cleanup_task_id": cid, "cleanup_pending": cid is not None,
                "notes": ["Deleted content may remain in operator backups until backup expiry.",
                          "Upstream deletion acknowledgements are not proof of provider backup erasure.",
                          "MiroFish has no simulation-artifact deletion API. Its profiles/logs require operator cleanup.",
                          "Minimal encrypted upstream references are retained in the cleanup ledger while remediation is pending; the customer brief and report are removed."]}

    async def retention_loop():
        while True:
            for row in store.expired():
                try:
                    await delete_row(row)
                except Exception:
                    logger.error("Retention cleanup needs operator attention; run_id=%s", row["id"])
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(app):
        # This pilot runs one gateway worker. Do not silently replay paid tasks after a restart.
        for row in store.all_active():
            await engine.stop(row["private"]["upstream"])
            store.update(row["workspace_id"], row["id"], status="interrupted", stage="Gateway restarted",
                         error="The gateway restarted during this run. Ask the operator to review upstream jobs before retrying.")
        retention = asyncio.create_task(retention_loop())
        yield
        retention.cancel()
        for task in list(jobs):
            task.cancel()
        await asyncio.gather(retention, *list(jobs), return_exceptions=True)

    app = FastAPI(title="Branchline Gateway", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.engine = engine
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

    async def workspace(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if not credentials or credentials.scheme.lower() != "bearer" or len(credentials.credentials) > 512:
            raise HTTPException(401, "A valid workspace token is required", headers={"WWW-Authenticate": "Bearer"})
        row = store.workspace(credentials.credentials)
        if not row:
            raise HTTPException(401, "A valid workspace token is required", headers={"WWW-Authenticate": "Bearer"})
        if not store.allow_request(row["id"], settings.requests_per_minute):
            raise HTTPException(429, "Workspace request limit reached. Try again shortly.", headers={"Retry-After": "60"})
        return row

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "branchline"}

    @app.get("/api/v1/capabilities")
    async def capabilities(ws=Depends(workspace)):
        return {"workspace": {"id": ws["id"], "name": ws["name"]},
                "usage": {"credits_remaining": ws["credits"], "max_rounds": settings.max_rounds,
                          "max_active_runs": settings.max_active_runs, "credit_cost_formula": "1 + rounds",
                          "max_agents": settings.max_agents},
                "privacy": {"gateway_encryption": True, "upstream_processors": ["Operator-configured LLM provider", "Zep Cloud"], "notes": PRIVACY_NOTES},
                "billing": {"enabled": False, "mode": "operator-managed pilot"}}

    @app.post("/api/v1/runs", status_code=202)
    async def create_run(body: NewRun, ws=Depends(workspace)):
        if body.rounds > settings.max_rounds:
            raise HTTPException(422, "Round count exceeds the workspace limit")
        payload = body.model_dump()
        try:
            rid = store.reserve(ws["id"], payload, settings.max_active_runs, settings.max_active_global)
        except QuotaExceeded as exc:
            raise HTTPException(429, str(exc)) from exc
        if launch_jobs:
            task = asyncio.create_task(execute(ws["id"], rid, payload))
            jobs.add(task)
            task.add_done_callback(jobs.discard)
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

    @app.delete("/api/v1/runs/{rid}")
    async def delete_run(rid: str, ws=Depends(workspace)):
        row = store.get(ws["id"], rid)
        if not row:
            raise HTTPException(404, "Run not found")
        if row["status"] in ACTIVE:
            raise HTTPException(409, "Wait for the run to finish before deleting it")
        return await delete_row(row)

    return app

