from contextlib import nullcontext
import json
from pathlib import Path

import pytest

from deploy.engine_cleanup import CleanupBusy, erase_simulation


SID = "sim_abcdef123456"


class Runner:
    _processes = {}
    _monitor_threads = {}
    _run_states = {}

    @staticmethod
    def _finalization_lock(_):
        return nullcontext()


class Tasks:
    def list_tasks(self):
        return []


def test_cleanup_erases_profiles_logs_and_is_idempotent(tmp_path):
    directory = tmp_path / SID
    directory.mkdir()
    (directory / "state.json").write_text(json.dumps({"status": "completed"}))
    (directory / "private-profiles.json").write_text("CONFIDENTIAL")
    (directory / "simulation.log").write_text("CONFIDENTIAL")
    assert erase_simulation(SID, tmp_path, Runner, Tasks())["simulation_artifacts"] == "deletion_acknowledged"
    assert not directory.exists()
    assert erase_simulation(SID, tmp_path, Runner, Tasks())["simulation_artifacts"] == "deletion_acknowledged"


@pytest.mark.parametrize("identifier", ["../private", "sim_../../etc", "", "sim_ABCDEF123456", "sim_abcdef123456/../../etc"])
def test_cleanup_rejects_paths(tmp_path, identifier):
    with pytest.raises(ValueError):
        erase_simulation(identifier, tmp_path, Runner, Tasks())


def test_cleanup_refuses_symlink_without_touching_target(tmp_path):
    actual = tmp_path / "private-target"
    actual.mkdir()
    marker = actual / "keep.txt"
    marker.write_text("keep")
    (tmp_path / SID).symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        erase_simulation(SID, tmp_path, Runner, Tasks())
    assert marker.read_text() == "keep"


def test_cleanup_refuses_busy_preparation(tmp_path):
    class BusyTasks:
        def list_tasks(self):
            return [{"metadata": {"simulation_id": SID}, "status": "processing"}]
    directory = tmp_path / SID
    directory.mkdir()
    with pytest.raises(CleanupBusy):
        erase_simulation(SID, tmp_path, Runner, BusyTasks())
    assert directory.exists()


def test_cleanup_refuses_live_process(tmp_path):
    class Process:
        def poll(self):
            return None
    class BusyRunner(Runner):
        _processes = {SID: Process()}
    with pytest.raises(CleanupBusy):
        erase_simulation(SID, tmp_path, BusyRunner, Tasks())
