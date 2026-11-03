"""Explicit deployment configuration. Never load provider secrets into the UI."""
from dataclasses import dataclass
import os
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database: str
    encryption_key: str
    engine_url: str = "http://mirofish:5001"
    origins: tuple[str, ...] = ("http://localhost:8000",)
    job_timeout: int = 7200
    request_timeout: int = 180
    poll_interval: float = 5
    max_rounds: int = 20
    max_agents: int = 40
    max_active_runs: int = 1
    max_active_global: int = 2
    requests_per_minute: int = 90

    @classmethod
    def from_env(cls):
        key = os.environ.get("BRANCHLINE_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError("BRANCHLINE_ENCRYPTION_KEY must be set before startup")
        origins = tuple(o.strip().rstrip("/") for o in os.environ.get(
            "BRANCHLINE_ALLOWED_ORIGINS", "http://localhost:8000"
        ).split(",") if o.strip())
        if not origins or "*" in origins:
            raise RuntimeError("Configure explicit BRANCHLINE_ALLOWED_ORIGINS; wildcard is forbidden")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path:
                raise RuntimeError("CORS origins must be exact HTTP(S) origins without paths")
            if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "[::1]"):
                raise RuntimeError("Public CORS origins require HTTPS")
        engine = os.environ.get("MIROFISH_BASE_URL", "http://mirofish:5001").rstrip("/")
        parsed = urlparse(engine)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("MIROFISH_BASE_URL must be a server-configured HTTP(S) origin")
        return cls(
            database=os.environ.get("BRANCHLINE_DATABASE", "/data/branchline.sqlite3"),
            encryption_key=key, engine_url=engine, origins=origins,
            job_timeout=int(os.environ.get("BRANCHLINE_JOB_TIMEOUT", "7200")),
            max_rounds=min(20, max(1, int(os.environ.get("BRANCHLINE_MAX_ROUNDS", "20")))),
            max_agents=min(40, max(1, int(os.environ.get("BRANCHLINE_MAX_AGENTS", "40")))),
        )

