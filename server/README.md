# Branchline gateway: operator-managed pilot

The public static interface works without this service in clearly labelled demo mode. Real runs need this private gateway, a private MiroFish engine, an OpenAI-compatible LLM account, and a Zep Cloud account. This is a single-node, single-worker pilot implementation, not a self-service billing service. Public visitors cannot create accounts or incur compute charges without an operator-provisioned workspace token.

## Start

From the repository root, copy `.env.example` to `.env`, replace all placeholders and generate `BRANCHLINE_ENCRYPTION_KEY` with `cryptography.fernet.Fernet.generate_key()`. Keep that key in a secret manager; losing it makes stored content unreadable. Set `BRANCHLINE_ALLOWED_ORIGINS` to the exact HTTPS origin of the published UI.

```sh
docker compose up --build -d
docker compose exec gateway python scripts/provision-workspace.py --name 'My pilot workspace' --credits 30
```

The token is shown once, with only its SHA-256 digest stored in SQLite. Give each customer a separate workspace token securely. It grants all data in that workspace, so do not share one between unrelated customers. The interface retains tokens in page memory. Use the same command with `--workspace-id <id>` to rotate the key and replace available credits; this revokes the old key immediately. Credits are manually provisioned pilot allowance, not automatic renewals. Each accepted run consumes `1 + rounds` credits. Failed/interrupted attempts retain the reservation because upstream work may already have incurred cost; operator adjustments use the provisioning command.

The gateway binds to `127.0.0.1:8080`. Put a TLS reverse proxy in front of it; see the root deployment guide. MiroFish has **no host-published ports**. Do not expose its unauthenticated native API or frontend. Its Docker network must be limited to trusted operators/services. Use encrypted host storage, backups and restricted administrative access. Both services run without root privileges. Do not change the gateway to multiple workers: restart handling and the in-process job supervisor assume a single process.

Local development (Python 3.12+):

```sh
python -m venv .venv
.venv/bin/pip install -r server/requirements-dev.txt
# Set the same environment variables securely; use a writable BRANCHLINE_DATABASE path.
.venv/bin/python -m server
.venv/bin/python -m pytest tests/server -q
```

## Browser API contract

All `/api/v1/*` requests require `Authorization: Bearer <workspace token>`. CORS allows exact configured origins, never `*`, and no cookies. API responses use `Cache-Control: no-store`. `/health` is public and checks gateway liveness, not provider readiness. `/api/v1/capabilities` validates a token and returns workspace, quota and processing information; it does not test live provider credentials.

`POST /api/v1/runs` accepts JSON and responds `202` with a run:

```json
{
  "title": "New pricing message",
  "question": "How might members react to a 10% price increase?",
  "context": "Our current membership is $40. The new price would be $44. We plan to explain the additional benefits.",
  "audience": "Existing members of an independent community gym",
  "rounds": 5,
  "template": "pricing",
  "privacy": {"retention_days": 7},
  "consent_external_processing": true
}
```

Limits: title 1–120 characters, question 10–4,000, context 20–30,000, audience 1–1,000, rounds 1–20, retention 1–30 days, maximum request body 100 KB. Extra fields are rejected. True consent is mandatory. Each workspace has one active run; the gateway has two in total. Reservations and quotas use an SQLite immediate transaction. At most 40 graph entities may proceed to preparation, with two concurrent profile generations; graph/ontology work occurs before the entity cap can be checked. Provider spending limits remain necessary: internal credits are workload controls, not a currency or hard upstream dollar cap.

`GET /api/v1/runs` returns `{ "runs": [...] }` (100 most recent). `GET /api/v1/runs/{id}` returns the same object shape:

```json
{
  "id": "uuid",
  "title": "New pricing message",
  "question": "How might members react to a 10% price increase?",
  "audience": "Existing gym members",
  "rounds": 5,
  "status": "completed",
  "stage": "Report ready",
  "progress": 100,
  "created_at": "2026-11-03T00:00:00+00:00",
  "updated_at": "2026-11-03T00:10:00+00:00",
  "expires_at": "2026-11-10T00:00:00+00:00",
  "credits_reserved": 6,
  "result": {"markdown": "# Scenario report\n..."},
  "error": null,
  "privacy_receipt": {"processors": ["Branchline gateway", "Private MiroFish engine", "Operator-configured LLM provider", "Zep Cloud"], "gateway_retention_days": 7, "notes": ["Processing and retention disclosures"]}
}
```

Statuses are `queued`, `building`, `preparing`, `running`, `reporting`, `completed`, `failed`, `interrupted`. Render reports as escaped text or sanitised Markdown: provider output is untrusted. Synthetic outputs are scenario evidence, not calibrated probabilities, representative customer surveys or investment/medical/legal advice.

`DELETE /api/v1/runs/{id}` allows terminal runs only (`409` while active). It deletes the gateway row and returns a receipt with `gateway_deleted`, individual upstream cleanup acknowledgements and residual-data limitations. Cross-workspace reads and deletes return `404`, including otherwise valid IDs. No upstream IDs or API proxy are exposed. There is no cancellation endpoint because ontology/graph/preparation/report jobs cannot all be reliably cancelled through upstream APIs.

The worker uses the pinned MiroFish APIs: multipart ontology upload, graph build/task polling, graph-entity limit check, simulation create/prepare/status/start/run-status, report generate/status/by-simulation. Only the private server-configured engine origin is callable, with no redirects and no user-supplied hostnames. Polling and job duration are bounded; errors never return upstream bodies or tracebacks. Failure and timeout attempt to stop a known active simulation. An upstream request can continue after an HTTP timeout; operators must review incomplete jobs before retrying. Runs are marked interrupted after gateway restarts rather than silently replayed.

## Privacy scope and deletion

Gateway request fields, upstream references, results and errors are Fernet-encrypted in the database. Metadata (workspace names/IDs, status, timestamps and credit counts) is plaintext. This is server-side encryption, **not end-to-end encrypted inference** or protection against an operator with the key. Tokens are hashed. A shared workspace token is not individual user identity. Use per-user authentication, roles and a durable external job queue before general paid onboarding.

Real processing discloses context to the configured LLM provider and Zep Cloud. The private engine stores source files, generated profiles and simulation artifacts in its own volume; gateway encryption does not encrypt those files. Upstream request logging is suppressed by the hardened engine entrypoint, but simulation artifacts can contain content. Local deletion is not a promise to erase provider backups or provider security logs. Upstream MiroFish currently exposes project/cloud-graph and report deletion APIs but no simulation artifact deletion API. Receipts say `operator_cleanup_required` for those artifacts. Engine-volume purging must be handled by the operator according to an agreed retention policy. Do not promise automatic complete erasure, zero retention, Australian residency or “never used for training” without verified provider contracts and a tested storage lifecycle.

A background sweep removes terminal gateway runs after their chosen retention period (checks every 60 seconds). It attempts upstream project/graph/report deletion. Expiry is calculated from creation time. The service must be running for cleanup to occur. The sweep does not erase simulation artifacts or operator/provider backups, and failed upstream cleanup needs operator attention. Backups need their own expiry policy. Original graph/preparation jobs may still be running after a timeout and can reject deletion; this is surfaced as a cleanup limitation rather than a false erasure guarantee.

Pending upstream deletion is retained in a minimal **encrypted cleanup ledger** containing resource IDs and acknowledgements, without the customer brief or generated report. Delete receipts include `cleanup_pending` and `cleanup_task_id`. Operators must monitor this ledger:

```sh
docker compose exec gateway python -m server.cleanup --list
docker compose exec gateway python -m server.cleanup --retry
# After manually verifying engine profiles/logs and upstream resources are removed:
docker compose exec gateway python -m server.cleanup --resolve TASK_ID
```

The `--list` command shows private resource identifiers to trusted host operators, not to public visitors. `--retry` does not delete simulation files because no upstream API supports it. `--resolve` is an explicit operator attestation; use only after verifying manual cleanup. Deleting a gateway run never discards unresolved upstream references. Keys and cleanup-ledger access must remain available until remediation is complete.

Before paid launch add per-user sign-in/revocation, independently reviewed authorization, queue recovery, alerting, real usage/cost metering, abuse controls, provider spending caps, signed billing webhooks and idempotent credit ledgers, provider agreements, an operator deletion dashboard, and a verified end-to-end run using production credentials. Automated tests use mocked provider/engine responses and do not incur provider charges.
