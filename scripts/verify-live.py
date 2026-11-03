#!/usr/bin/env python3
"""Run one non-confidential, one-round verification through a deployed gateway.

Requires a provisioned operator workspace with at least two credits. This
performs real provider work and can incur provider charges. No key is written.
"""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="Combined application origin, e.g. https://your-app.onrender.com")
    parser.add_argument("--timeout-minutes", type=int, default=30, choices=range(1, 61))
    parser.add_argument("--receipt", default="artifacts/live-verification.json")
    args = parser.parse_args()
    origin = args.api.rstrip("/")
    parsed = urlparse(origin)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.netloc:
        parser.error("Use an origin without credentials, path, query or fragment")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS for a deployed service")
    token = os.environ.get("BRANCHLINE_WORKSPACE_TOKEN") or getpass.getpass("Provisioned verification workspace token: ")
    if not token:
        parser.error("A workspace token is required")
    with httpx.Client(base_url=origin, headers={"Authorization": "Bearer " + token},
                      timeout=45, follow_redirects=False) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if not response.is_success:
                raise SystemExit(f"Gateway returned HTTP {response.status_code} at {path}. Check service readiness and workspace allowance.")
            return response.json()
        config = call("GET", "/api/v1/config")
        if not config.get("engine", {}).get("configured"):
            raise SystemExit("The engine is disabled. Configure and enable it before live verification.")
        quote = call("POST", "/api/v1/runs/quote", json={"rounds": 1})
        if not quote.get("sufficient"):
            raise SystemExit("This workspace needs at least two pilot credits.")
        print("Starting a one-round live verification. Real model and graph usage can incur charges.", flush=True)
        run = call("POST", "/api/v1/runs", json={
            "title": "Non-confidential deployment verification",
            "question": "What objections might two fictional buyers raise about a clearly explained coffee price change?",
            "context": "This is a fictional shop and a deployment test. Alex is a repeat buyer who prioritises price. Sam is a repeat buyer who prioritises convenience. The fictional shop plans to change a bag of coffee from 40 to 44 currency units, with 30 days of notice. Model these two fictional buyers only; do not add real people or real organisations.",
            "audience": "Two fictional adult buyers, Alex and Sam",
            "rounds": 1, "template": "verification", "privacy": {"retention_days": 1},
            "consent_external_processing": True,
        })
        rid = run["id"]
        deadline = time.monotonic() + args.timeout_minutes * 60
        last = None
        while run["status"] not in {"completed", "failed", "interrupted", "cancelled"}:
            label = (run["status"], run.get("stage"))
            if label != last:
                print(f"{run['status']}: {run.get('stage', '')}", flush=True)
                last = label
            if time.monotonic() > deadline:
                raise SystemExit("Verification is still pending. Reopen My scenarios; do not blindly resubmit a paid job.")
            time.sleep(5)
            run = call("GET", "/api/v1/runs/" + rid)
        if run["status"] != "completed" or not run.get("result", {}).get("markdown", "").strip():
            raise SystemExit("The live job did not return a report. Review its safe error in My scenarios before enabling billing.")
        receipt = {"verified_at": datetime.now(timezone.utc).isoformat(), "api_origin": origin,
                   "run_id": rid, "status": run["status"], "rounds": 1,
                   "credits_reserved": run["credits_reserved"], "report_received": True,
                   "processing_receipt": run.get("privacy_receipt")}
        destination = Path(args.receipt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, indent=2))
        print(f"Live report received. Verification receipt: {destination}", flush=True)
        print("Review the report and delete the test run through Branchline; inspect the cleanup receipt.")


if __name__ == "__main__":
    main()
