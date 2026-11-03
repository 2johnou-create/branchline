"""Operator cleanup ledger. Never prints briefs or tokens; refs require host access."""
import argparse
import asyncio
import json

from .config import Settings
from .engine import Engine
from .store import Store


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="List pending cleanup tasks and private resource references")
    action.add_argument("--retry", action="store_true", help="Retry supported project/report/cloud graph deletion APIs")
    action.add_argument("--resolve", metavar="TASK_ID", help="Remove ledger task only after manually verifying all engine artifacts and supported upstream deletions are complete")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.database, settings.encryption_key)
    engine = Engine(settings)
    if args.resolve:
        print(json.dumps({"id": args.resolve, "resolved": store.resolve_cleanup(args.resolve)}))
        return
    for task in store.cleanup_tasks():
        if args.retry:
            receipt = await engine.cleanup(task["private"]["upstream"])
            store.update_cleanup(task["id"], receipt)
            print(json.dumps({"id": task["id"], "receipt": receipt}))
        else:
            print(json.dumps({"id": task["id"], "run_id": task["run_id"], "created_at": task["created_at"], **task["private"]}))


if __name__ == "__main__":
    asyncio.run(main())
