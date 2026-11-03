"""Private engine WSGI entrypoint; upstream source is kept unmodified.

The gateway is the public boundary. This server must stay on the private
container network. Engine artifacts still need encrypted operator storage.
"""
import os
from engine_boot import configure_private_logging, startup_failed, validate_provider_environment

# Upstream DEBUG handlers include request bodies. Preserve supervisor events
# while suppressing app/provider logs; use explicit safe boot diagnostics.
configure_private_logging()
os.environ["FLASK_DEBUG"] = "False"

stage = "provider_configuration"
try:
    # Fail before expensive simulation imports, naming missing keys only.
    validate_provider_environment()
    stage = "application_import"
    from app import create_app  # noqa: E402
    from app.config import Config  # noqa: E402

    stage = "configuration_validation"
    if Config.validate():
        raise RuntimeError("MiroFish provider configuration is incomplete")

    stage = "application_factory"
    application = create_app()
    application.config.update(DEBUG=False, TESTING=False, MAX_CONTENT_LENGTH=131072)

    stage = "cleanup_registration"
    from engine_cleanup import register_cleanup  # noqa: E402
    from app.models.task import TaskManager  # noqa: E402
    from app.services.simulation_runner import SimulationRunner  # noqa: E402

    register_cleanup(application, SimulationRunner.RUN_STATE_DIR, SimulationRunner,
                     TaskManager(), os.environ.get("BRANCHLINE_ENGINE_CLEANUP_SECRET", ""))
except Exception as error:
    startup_failed(stage, error)

# The engine is reached server-to-server, never by a browser. Override the
# upstream wildcard CORS response without altering the vendored project.
def remove_browser_cors(response):
    for name in list(response.headers.keys()):
        if name.lower().startswith("access-control-"):
            del response.headers[name]
    response.headers["Cache-Control"] = "no-store"
    return response


# Flask executes this list in reverse registration order. Run after the
# upstream flask-cors hook so it cannot re-add wildcard browser access.
application.after_request_funcs.setdefault(None, []).insert(0, remove_browser_cors)
