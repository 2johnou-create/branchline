"""Explicit deployment configuration. Never load provider secrets into the UI."""
from dataclasses import dataclass
import base64
import hashlib
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
    public_url: str = "https://branchline.example"
    static_directory: str = "dist"
    engine_enabled: bool = True
    require_email_verification: bool = True
    signup_allowed_emails: tuple[str, ...] = ()
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_solo: str = ""
    stripe_price_studio: str = ""
    stripe_price_agency: str = ""
    stripe_price_pack_spark: str = ""
    stripe_price_pack_boost: str = ""
    stripe_price_pack_reserve: str = ""
    engine_cleanup_secret: str = ""
    enforce_host: bool = False
    billing_enabled: bool = False

    @classmethod
    def from_env(cls):
        key = os.environ.get("BRANCHLINE_ENCRYPTION_KEY", "")
        if not key:
            master = os.environ.get("BRANCHLINE_MASTER_SECRET", "")
            if master:
                if len(master) < 32:
                    raise RuntimeError("BRANCHLINE_MASTER_SECRET requires at least 32 characters of cryptographically random entropy")
                key = base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest()).decode()
        if not key:
            raise RuntimeError("BRANCHLINE_ENCRYPTION_KEY or BRANCHLINE_MASTER_SECRET must be set before startup")
        origins = tuple(o.strip().rstrip("/") for o in os.environ.get(
            "BRANCHLINE_ALLOWED_ORIGINS", os.environ.get("BRANCHLINE_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        ).split(",") if o.strip())
        if not origins or "*" in origins:
            raise RuntimeError("Configure explicit BRANCHLINE_ALLOWED_ORIGINS; wildcard is forbidden")
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path:
                raise RuntimeError("CORS origins must be exact HTTP(S) origins without paths")
            if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "[::1]"):
                raise RuntimeError("Public CORS origins require HTTPS")
        private_hostport = os.environ.get("MIROFISH_PRIVATE_HOSTPORT", "")
        engine = os.environ.get("MIROFISH_BASE_URL", "http://" + private_hostport if private_hostport else "http://mirofish:5001").rstrip("/")
        parsed = urlparse(engine)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("MIROFISH_BASE_URL must be a server-configured HTTP(S) origin")
        public_url = (os.environ.get("BRANCHLINE_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or origins[0]).rstrip("/")
        public = urlparse(public_url)
        if public.scheme not in ("http", "https") or not public.netloc or public.path or public.query or public.fragment or public.username:
            raise RuntimeError("BRANCHLINE_PUBLIC_URL must be an exact HTTP(S) origin")
        if public.scheme != "https" and public.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError("Public account sessions require HTTPS (HTTP is allowed only on localhost)")
        return cls(
            database=os.environ.get("BRANCHLINE_DATABASE", "/data/branchline.sqlite3"),
            encryption_key=key, engine_url=engine, origins=origins,
            job_timeout=int(os.environ.get("BRANCHLINE_JOB_TIMEOUT", "7200")),
            max_rounds=min(20, max(1, int(os.environ.get("BRANCHLINE_MAX_ROUNDS", "20")))),
            max_agents=min(40, max(1, int(os.environ.get("BRANCHLINE_MAX_AGENTS", "40")))),
            max_active_global=min(2, max(1, int(os.environ.get("BRANCHLINE_MAX_ACTIVE_GLOBAL", "1")))),
            public_url=public_url, static_directory=os.environ.get("BRANCHLINE_STATIC_DIRECTORY", "dist"),
            engine_enabled=os.environ.get("BRANCHLINE_ENGINE_ENABLED", "false").lower() == "true",
            require_email_verification=os.environ.get("BRANCHLINE_REQUIRE_EMAIL_VERIFICATION", "true").lower() != "false",
            signup_allowed_emails=tuple(address.strip().lower() for address in os.environ.get("BRANCHLINE_SIGNUP_ALLOWED_EMAILS", "").split(",") if address.strip()),
            smtp_host=os.environ.get("BRANCHLINE_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("BRANCHLINE_SMTP_PORT", "587")),
            smtp_username=os.environ.get("BRANCHLINE_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("BRANCHLINE_SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("BRANCHLINE_SMTP_FROM", ""),
            smtp_starttls=os.environ.get("BRANCHLINE_SMTP_STARTTLS", "true").lower() != "false",
            stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_solo=os.environ.get("STRIPE_PRICE_SOLO", ""),
            stripe_price_studio=os.environ.get("STRIPE_PRICE_STUDIO", ""),
            stripe_price_agency=os.environ.get("STRIPE_PRICE_AGENCY", ""),
            stripe_price_pack_spark=os.environ.get("STRIPE_PRICE_PACK_SPARK", ""),
            stripe_price_pack_boost=os.environ.get("STRIPE_PRICE_PACK_BOOST", ""),
            stripe_price_pack_reserve=os.environ.get("STRIPE_PRICE_PACK_RESERVE", ""),
            engine_cleanup_secret=os.environ.get("BRANCHLINE_ENGINE_CLEANUP_SECRET", ""),
            enforce_host=True,
            billing_enabled=os.environ.get("BRANCHLINE_BILLING_ENABLED", "false").lower() == "true",
        )

