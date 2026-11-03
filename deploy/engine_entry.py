"""Private engine WSGI entrypoint; upstream source is kept unmodified.

The gateway is the public boundary. This server must stay on the private
container network. Engine artifacts still need encrypted operator storage.
"""
import logging
import os

# Upstream's default DEBUG file logger includes raw request bodies. Disable
# Python logging before importing it rather than retaining customer prompts.
# Engine subprocess artifacts are separate and are disclosed in PRIVACY.md.
logging.disable(logging.CRITICAL)
os.environ["FLASK_DEBUG"] = "False"

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402

if Config.validate():
    raise RuntimeError("MiroFish provider configuration is incomplete.")

application = create_app()
application.config.update(DEBUG=False, TESTING=False, MAX_CONTENT_LENGTH=131072)

from engine_cleanup import register_cleanup  # noqa: E402
from app.models.task import TaskManager  # noqa: E402
from app.services.simulation_runner import SimulationRunner  # noqa: E402

register_cleanup(application, SimulationRunner.RUN_STATE_DIR, SimulationRunner,
                 TaskManager(), os.environ.get("BRANCHLINE_ENGINE_CLEANUP_SECRET", ""))

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
