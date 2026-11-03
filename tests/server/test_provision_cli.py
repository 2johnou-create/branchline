import os
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

from cryptography.fernet import Fernet
import pytest

from server.config import Settings
from server.store import Store


@pytest.mark.parametrize("secret_kind", ["master", "explicit"])
def test_workspace_cli_uses_application_secret_and_database_override(tmp_path, secret_kind):
    root = Path(__file__).resolve().parents[2]
    selected_db = tmp_path / "selected.sqlite3"
    unused_db = tmp_path / "environment-default.sqlite3"
    environment = {
        "BRANCHLINE_DATABASE": str(unused_db),
        "BRANCHLINE_PUBLIC_URL": "https://branchline.example",
    }
    if secret_kind == "master":
        environment["BRANCHLINE_MASTER_SECRET"] = "test-only-randomly-generated-master-secret-long-enough-12345"
    else:
        environment["BRANCHLINE_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    command = [sys.executable, str(root / "scripts/provision-workspace.py"),
               "--name", "CLI integration", "--credits", "17", "--database", str(selected_db)]
    result = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True)
    succeeded = result.returncode == 0
    assert succeeded
    # Tokens are deliberately captured, never printed or used as assertion messages.
    found = re.search(r"^Workspace token \(shown once; store securely\): (bl_[A-Za-z0-9_-]+)$", result.stdout, re.MULTILINE)
    assert found is not None
    token = found.group(1)
    with patch.dict(os.environ, environment, clear=True):
        settings = Settings.from_env()
    store = Store(str(selected_db), settings.encryption_key)
    workspace = store.workspace(token)
    authenticated = workspace is not None
    assert authenticated
    assert workspace["credits"] == 17
    assert workspace["name"] == "CLI integration"
    assert not unused_db.exists()
    with store.connection() as db:
        stored_hash = db.execute("SELECT token_hash FROM workspaces").fetchone()[0]
    hash_only = stored_hash != token
    assert hash_only
    rotation = subprocess.run([*command, "--workspace-id", workspace["id"]], cwd=root,
                              env=environment, text=True, capture_output=True)
    rotated = rotation.returncode == 0
    assert rotated
    old_token_revoked = store.workspace(token) is None
    assert old_token_revoked
