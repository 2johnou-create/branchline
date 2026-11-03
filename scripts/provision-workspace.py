#!/usr/bin/env python3
"""Provision or rotate a pilot workspace key. Output the token only once."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.store import Store
from server.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Workspace display name")
    parser.add_argument("--credits", type=int, default=30, help="Total available pilot credits, not a recurring subscription")
    parser.add_argument("--workspace-id", help="Existing workspace to rotate token and replace available credits")
    parser.add_argument("--database", default=os.environ.get("BRANCHLINE_DATABASE", "/data/branchline.sqlite3"))
    args = parser.parse_args()
    if not 0 <= args.credits <= 1_000_000 or not 1 <= len(args.name.strip()) <= 120:
        parser.error("Provide a name of 1–120 characters and credits between 0 and 1000000")
    try:
        key = Settings.from_env().encryption_key
    except (RuntimeError, ValueError):
        parser.error("Set BRANCHLINE_ENCRYPTION_KEY or BRANCHLINE_MASTER_SECRET and valid application settings in the process environment")
    os.umask(0o077)
    store = Store(args.database, key)
    wid, token = store.provision(args.name.strip(), args.credits, args.workspace_id)
    print("Workspace ID:", wid)
    print("Workspace token (shown once; store securely):", token)
    print("Available pilot credits:", args.credits)


if __name__ == "__main__":
    main()

