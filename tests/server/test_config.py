import base64
import hashlib

import pytest

from server.config import Settings


def test_render_master_key_and_private_hostport(monkeypatch):
    for key in ("BRANCHLINE_ENCRYPTION_KEY", "BRANCHLINE_PUBLIC_URL", "BRANCHLINE_ALLOWED_ORIGINS", "MIROFISH_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    master = "a-cryptographically-generated-render-secret-1234567890"
    monkeypatch.setenv("BRANCHLINE_MASTER_SECRET", master)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://branchline.onrender.com")
    monkeypatch.setenv("MIROFISH_PRIVATE_HOSTPORT", "branchline-engine.internal:5001")
    settings = Settings.from_env()
    assert settings.encryption_key == base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest()).decode()
    assert settings.public_url == "https://branchline.onrender.com"
    assert settings.origins == ("https://branchline.onrender.com",)
    assert settings.engine_url == "http://branchline-engine.internal:5001"
    assert settings.engine_enabled is False and settings.billing_enabled is False
    assert settings.require_email_verification is True
    assert settings.max_active_global == 1
    assert settings.enforce_host is True


def test_public_http_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("BRANCHLINE_ENCRYPTION_KEY", "placeholder")
    monkeypatch.setenv("BRANCHLINE_ALLOWED_ORIGINS", "http://public.example")
    with pytest.raises(RuntimeError, match="HTTPS"):
        Settings.from_env()


def test_weak_master_secret_is_rejected(monkeypatch):
    monkeypatch.delenv("BRANCHLINE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("BRANCHLINE_MASTER_SECRET", "short")
    with pytest.raises(RuntimeError, match="32 characters"):
        Settings.from_env()
