"""Bounded private cleanup for Branchline-owned simulation artifacts.

Only the authenticated private gateway calls this route. Never accept paths
from callers, and never erase data while an engine producer can rewrite it.
"""
from pathlib import Path
import json
import re
import secrets
import shutil


class CleanupBusy(Exception):
    pass


def erase_simulation(simulation_id, root, runner, tasks):
    if not isinstance(simulation_id, str) or not re.fullmatch(r"sim_[a-f0-9]{12}", simulation_id):
        raise ValueError("Invalid simulation identifier")
    root = Path(root).resolve()
    target = root / simulation_id
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError("Invalid simulation directory")
    with runner._finalization_lock(simulation_id):
        process = runner._processes.get(simulation_id)
        monitor = runner._monitor_threads.get(simulation_id)
        if (process is not None and process.poll() is None) or (monitor is not None and monitor.is_alive()):
            raise CleanupBusy("Simulation is still active")
        for task in tasks.list_tasks():
            if task.get("metadata", {}).get("simulation_id") == simulation_id and task.get("status") in {"pending", "processing"}:
                raise CleanupBusy("Simulation preparation is still active")
        if not target.exists():
            return {"deleted": True, "simulation_artifacts": "deletion_acknowledged"}
        state_file = target / "state.json"
        if state_file.exists():
            try:
                status = json.loads(state_file.read_text()).get("status")
            except (ValueError, OSError):
                raise CleanupBusy("Simulation state needs operator review") from None
            if status in {"preparing", "running", "paused", "stopping"}:
                raise CleanupBusy("Simulation state is not terminal")
        shutil.rmtree(target)
        runner._run_states.pop(simulation_id, None)
        runner._processes.pop(simulation_id, None)
        runner._monitor_threads.pop(simulation_id, None)
    return {"deleted": True, "simulation_artifacts": "deletion_acknowledged"}


def register_cleanup(application, root, runner, tasks, secret):
    from flask import jsonify, request

    @application.delete("/internal/branchline/simulations/<simulation_id>")
    def cleanup_simulation(simulation_id):
        supplied = request.headers.get("X-Branchline-Cleanup-Key", "")
        if len(secret) < 32 or not supplied or not secrets.compare_digest(supplied, secret):
            return jsonify(success=False, error="Private cleanup authorization required"), 403
        try:
            result = erase_simulation(simulation_id, root, runner, tasks)
        except ValueError:
            return jsonify(success=False, error="Invalid simulation identifier"), 400
        except CleanupBusy:
            return jsonify(success=False, error="Cleanup pending: engine resources are busy"), 409
        except OSError:
            return jsonify(success=False, error="Cleanup requires operator attention"), 503
        return jsonify(success=True, data=result)
