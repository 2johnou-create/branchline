"""Install the pinned upstream stack with CPU PyTorch for API-based inference.

The upstream lock and source remain unchanged. GPU wheels are unnecessary on
the CPU container hosts targeted here; every other dependency stays frozen.
"""
from pathlib import Path
import subprocess
import tomllib

lock = tomllib.loads(Path("uv.lock").read_text())
excluded = [p["name"] for p in lock["package"]
            if p["name"] in {"torch", "triton"} or p["name"].startswith("nvidia-")]
command = ["uv", "sync", "--frozen", "--no-dev"]
for package in excluded:
    command.extend(["--no-install-package", package])
subprocess.run(command, check=True)
torch_version = next(p["version"] for p in lock["package"] if p["name"] == "torch")
subprocess.run(["uv", "pip", "install", "--python", ".venv/bin/python", "--no-deps",
                "--index-url", "https://download.pytorch.org/whl/cpu",
                f"torch=={torch_version}+cpu"], check=True)
subprocess.run(["uv", "pip", "install", "--python", ".venv/bin/python", "gunicorn==23.0.0"], check=True)
subprocess.run(["uv", "pip", "check", "--python", ".venv/bin/python"], check=True)
