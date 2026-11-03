import io
import json
import logging
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest

from deploy import engine_boot


@pytest.mark.parametrize("environment,port", [({}, "5001"), ({"PORT": "10000"}, "10000")])
def test_gunicorn_uses_render_port_or_local_default(environment, port):
    command = ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "engine_entry:application"]
    result = engine_boot.engine_command(command, environment)
    assert result == ["gunicorn", "--bind", "0.0.0.0:" + port, "--workers", "1", "engine_entry:application"]
    assert command[2] == "0.0.0.0:5001"  # caller's command is not mutated


@pytest.mark.parametrize("option", [["--bind=0.0.0.0:5001"], ["-b", "127.0.0.1:5001"], []])
def test_bind_variants_are_replaced_instead_of_accumulating(option):
    result = engine_boot.engine_command(["gunicorn", *option, "engine_entry:application"], {"PORT": "10000"})
    assert result == ["gunicorn", "--bind", "0.0.0.0:10000", "engine_entry:application"]


@pytest.mark.parametrize("value", ["", "0", "65536", "10000;unsafe", "not-a-port", "-1"])
def test_invalid_port_fails_without_echoing_input(value):
    with pytest.raises(ValueError) as error:
        engine_boot.engine_command(["gunicorn", "engine_entry:application"], {"PORT": value})
    assert str(error.value) == "PORT must be a decimal integer between 1 and 65535"


def test_explicit_administrative_command_is_preserved():
    command = ["python", "-c", "import oasis"]
    assert engine_boot.engine_command(command, {"PORT": "bad"}) == command


def test_missing_keys_are_named_without_values(capsys):
    with pytest.raises(engine_boot.EngineConfigurationError) as error:
        engine_boot.validate_provider_environment({"LLM_API_KEY": "private-real-key", "ZEP_API_KEY": "", "ZEP_API_URL": "private-internal-url"})
    with pytest.raises(RuntimeError):
        engine_boot.startup_failed("provider_configuration", error.value)
    raw = capsys.readouterr().err
    record = json.loads(raw)
    assert record["missing_keys"] == ["ZEP_API_KEY"]
    assert record["unsupported_keys"] == ["ZEP_API_URL"]
    assert "private-real-key" not in raw and "private-internal-url" not in raw


def test_arbitrary_failure_bodies_are_not_logged(capsys):
    try:
        raise RuntimeError("CUSTOMER PROMPT and secret-key-123")
    except RuntimeError as error:
        with pytest.raises(RuntimeError, match="inspect the engine_startup_failed diagnostic"):
            engine_boot.startup_failed("application_factory", error)
    raw = capsys.readouterr().err
    record = json.loads(raw)
    assert record["error_type"] == "RuntimeError"
    assert record["stage"] == "application_factory"
    assert record["frames"]
    assert "CUSTOMER PROMPT" not in raw and "secret-key-123" not in raw


@pytest.fixture
def private_logging(monkeypatch):
    # Restore the logging class after each test; do not affect other tests.
    previous = logging.Logger.handle
    previous_disabled = logging.root.manager.disable
    monkeypatch.setattr(logging.Logger, "handle", previous)
    engine_boot.configure_private_logging()
    yield
    logging.disable(previous_disabled)


def test_upstream_logs_are_dropped_but_supervisor_events_remain(private_logging):
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    vendor, supervisor = logging.Logger("mirofish.request"), logging.Logger("gunicorn.error")
    vendor.addHandler(handler)
    supervisor.addHandler(handler)
    vendor.warning("PRIVATE REQUEST BODY")
    supervisor.warning("Worker failed to boot")
    try:
        raise ValueError("SECRET PROVIDER BODY")
    except ValueError:
        supervisor.exception("PRIVATE EXCEPTION BODY")
    raw = output.getvalue()
    assert "Worker failed to boot" in raw
    assert "exception_type=ValueError" in raw
    assert "PRIVATE" not in raw and "SECRET" not in raw


def test_entrypoint_reports_preflight_before_imports(monkeypatch, capsys, private_logging):
    monkeypatch.setitem(sys.modules, "engine_boot", engine_boot)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    with pytest.raises(RuntimeError):
        runpy.run_path(str(Path(__file__).parents[2] / "deploy/engine_entry.py"))
    record = json.loads(capsys.readouterr().err)
    assert record["stage"] == "provider_configuration"
    assert record["missing_keys"] == ["LLM_API_KEY", "ZEP_API_KEY"]


def test_entrypoint_sanitizes_import_factory_failure(monkeypatch, capsys, private_logging):
    monkeypatch.setitem(sys.modules, "engine_boot", engine_boot)
    monkeypatch.setenv("LLM_API_KEY", "private-provider-key")
    monkeypatch.setenv("ZEP_API_KEY", "private-zep-key")
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    app = ModuleType("app")
    def fail():
        raise ValueError("private-provider-key private-zep-key CUSTOMER PROMPT")
    app.create_app = fail
    config = ModuleType("app.config")
    config.Config = SimpleNamespace(validate=lambda: [])
    monkeypatch.setitem(sys.modules, "app", app)
    monkeypatch.setitem(sys.modules, "app.config", config)
    with pytest.raises(RuntimeError):
        runpy.run_path(str(Path(__file__).parents[2] / "deploy/engine_entry.py"))
    raw = capsys.readouterr().err
    record = json.loads(raw)
    assert record["stage"] == "application_factory"
    assert record["error_type"] == "ValueError"
    assert "private-provider-key" not in raw and "private-zep-key" not in raw and "CUSTOMER PROMPT" not in raw
