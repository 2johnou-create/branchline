from pathlib import Path
import runpy
import sys

import pytest


@pytest.mark.parametrize("extra", [[], ["--twitter-only"]])
def test_twitter_entrypoint_uses_structured_runner_and_preserves_round_cap(monkeypatch, extra):
    entry = Path(__file__).parents[2] / "deploy/run_twitter_simulation.py"
    execute = runpy.run_path
    calls = []
    monkeypatch.setattr(sys, "argv", [str(entry), "--config", "private-config.json", "--max-rounds", "1", *extra])
    monkeypatch.setattr(runpy, "run_path", lambda path, run_name: calls.append((path, run_name, list(sys.argv))))
    execute(str(entry), run_name="__main__")
    path, name, arguments = calls[0]
    assert Path(path).name == "run_parallel_simulation.py" and name == "__main__"
    assert arguments[1:5] == ["--config", "private-config.json", "--max-rounds", "1"]
    assert arguments.count("--twitter-only") == 1
    assert "--reddit-only" not in arguments
