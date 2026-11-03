"""Secret-safe engine startup checks and Render/local port selection."""
import copy
import json
import logging
import os
from pathlib import Path
import re
import sys
import traceback


class EngineConfigurationError(RuntimeError):
    def __init__(self, *, missing=(), unsupported=()):
        super().__init__("Engine provider configuration is incomplete")
        self.missing = tuple(missing)
        self.unsupported = tuple(unsupported)


def validate_provider_environment(environment=None):
    environment = os.environ if environment is None else environment
    missing = [name for name in ("LLM_API_KEY", "ZEP_API_KEY")
               if not environment.get(name, "").strip()]
    unsupported = ["ZEP_API_URL"] if environment.get("ZEP_API_URL") else []
    if missing or unsupported:
        raise EngineConfigurationError(missing=missing, unsupported=unsupported)


def engine_command(command, environment=None):
    """Use Render's runtime PORT; ordinary Docker/Compose defaults to 5001."""
    environment = os.environ if environment is None else environment
    command = list(command)
    if not command or Path(command[0]).name != "gunicorn":
        return command  # Preserve explicit CI/administrative command overrides.
    raw_port = environment.get("PORT", "5001")
    if not re.fullmatch(r"[0-9]{1,5}", raw_port) or not 1 <= int(raw_port) <= 65535:
        raise ValueError("PORT must be a decimal integer between 1 and 65535")
    address = "0.0.0.0:" + str(int(raw_port))
    result = []
    index = 0
    while index < len(command):
        arg = command[index]
        if arg in ("--bind", "-b"):
            if index + 1 >= len(command):
                raise ValueError("Gunicorn bind option is missing its value")
            index += 2
            continue
        if arg.startswith("--bind="):
            index += 1
            continue
        result.append(arg)
        index += 1
    return [result[0], "--bind", address, *result[1:]]


def configure_private_logging():
    """Keep Gunicorn supervisor messages while discarding app/provider logs.

    Upstream creates DEBUG handlers that include request bodies. A global
    logging.disable also hides worker-boot errors. Gate Logger.handle instead:
    runtime app/provider records are discarded, and Gunicorn exception bodies
    are replaced with the exception class. Startup details use explicit safe
    JSON below, never arbitrary exception strings or environment values.
    """
    previous = logging.Logger.handle
    logging.disable(logging.NOTSET)

    def private_handle(logger, record):
        if record.name != "gunicorn" and not record.name.startswith("gunicorn."):
            return
        if record.exc_info:
            record = copy.copy(record)
            record.msg = "Engine worker error; exception_type=%s"
            record.args = (record.exc_info[0].__name__,)
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return previous(logger, record)

    logging.Logger.handle = private_handle


def startup_failed(stage, error):
    """Emit useful failure locations without exception bodies or local values."""
    frames = traceback.extract_tb(error.__traceback__)[-8:]
    record = {
        "event": "engine_startup_failed", "stage": stage,
        "error_type": type(error).__name__,
        "frames": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames],
    }
    if isinstance(error, EngineConfigurationError):
        record["missing_keys"] = list(error.missing)
        record["unsupported_keys"] = list(error.unsupported)
    if isinstance(error, ModuleNotFoundError) and re.fullmatch(r"[A-Za-z0-9_.]{1,120}", error.name or ""):
        record["missing_module"] = error.name
    sys.stderr.write(json.dumps(record, ensure_ascii=True) + "\n")
    sys.stderr.flush()
    raise RuntimeError("Branchline engine startup failed; inspect the engine_startup_failed diagnostic") from None
