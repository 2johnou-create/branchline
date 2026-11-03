"""Route upstream's Twitter entrypoint through its structured action logger.

The pinned legacy Twitter script never writes the completion/action events
consumed by the runner and report tools. The parallel script supports the same
CLI plus --twitter-only, so use that maintained path without editing the vendor.
"""
from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    target = Path(__file__).with_name("run_parallel_simulation.py")
    sys.argv = [str(target), *sys.argv[1:]]
    if "--twitter-only" not in sys.argv:
        sys.argv.append("--twitter-only")
    runpy.run_path(str(target), run_name="__main__")
