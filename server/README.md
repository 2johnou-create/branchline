# Branchline application server

The server hosts the static interface and account, subscription and simulation APIs on one origin. The separately published static Site remains a public demonstration; normal accounts require this combined server deployment. Real simulations require a private MiroFish engine, an OpenAI-compatible LLM account and Zep Cloud. The server never substitutes demo results for inference.

## Configuration and readiness

Follow the root deployment guide and `.env.example`. Keep secrets on the host, outside frontend JavaScript, source control and command arguments.

| Setting | Purpose |
| --- | --- |
| `BRANCHLINE_ENCRYPTION_KEY` | Persistent Fernet key. Alternatively use a cryptographically random `BRANCHLINE_MASTER_SECRET` of at least 32 characters; SHA-256 is encoded as the Fernet key. Preserve the same secret across deployments. |
| `BRANCHLINE_DATABASE` | SQLite file, default `/data/branchline.sqlite3`; requires persistent private storage. |
| `BRANCHLINE_PUBLIC_URL` | Exact HTTPS app origin. Falls back to platform-supplied `RENDER_EXTERNAL_URL`, then the configured CORS origin. Never derived from request Host headers. HTTP is allowed only on localhost. |
| `BRANCHLINE_SIGNUP_ALLOWED_EMAILS` | Optional comma-separated pilot registration allowlist. Addresses are normalized to lowercase; unlisted addresses are rejected before password hashing, account creation or email delivery. Leave unset for public registration after sender-domain verification. The list is never returned by the public configuration API. |
| `BRANCHLINE_ALLOWED_ORIGINS` | Explicit origins for optional bearer API access; defaults to the app origin. Wildcards/public HTTP origins are rejected. |
| `BRANCHLINE_STATIC_DIRECTORY` | Frontend directory, default `dist`; mounted after API routes. |
| `BRANCHLINE_ENGINE_ENABLED` | Default false for environment-based deployments. Explicitly permits real run reservations; this is an operator declaration, not a successful inference test. |
| `MIROFISH_BASE_URL` | Private server-only engine URL. Alternatively `MIROFISH_PRIVATE_HOSTPORT` is prefixed with `http://` for private platform networking. |
| `BRANCHLINE_ENGINE_CLEANUP_SECRET` | Optional shared secret for hardened engine terminal-artifact deletion; configure identically on engine and gateway. |
| `BRANCHLINE_SMTP_HOST`, `PORT`, `USERNAME`, `PASSWORD`, `FROM`, `STARTTLS` | Genuine email delivery. Defaults: port587, STARTTLS true. Port465 uses implicit TLS. Unencrypted SMTP is allowed only on localhost. |
| `BRANCHLINE_REQUIRE_EMAIL_VERIFICATION` | Default true. Signup is disabled if verification is required but SMTP is absent. False is an explicit operator override for controlled development. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_STUDIO`, `STRIPE_PRICE_AGENCY` | Optional hosted-billing configuration. Keys alone do not enable new checkout. |
| `BRANCHLINE_BILLING_ENABLED` | Default false. Opt in only after real engine, SMTP and Stripe test flows succeed. Checkout also requires engine enabled. Existing customer portal/webhook reconciliation remains available when checkout is paused. |
| `BRANCHLINE_MAX_ACTIVE_GLOBAL` | Default1, maximum2; one active run per workspace. |
| `BRANCHLINE_MAX_ROUNDS`, `BRANCHLINE_MAX_AGENTS`, `BRANCHLINE_JOB_TIMEOUT` | Maximum20 rounds, 40 graph entities, default two-hour run deadline. |

`GET /api/v1/config` returns public auth/email/engine/billing configuration readiness. `engine.verified` remains false: configuration does not prove credentials work. `/health` checks application liveness, not providers. Links/cookies use the fixed public origin; production Host headers are validated against it and loopback health-check hosts.

Local development requires Python3.12+:

```sh
python -m venv .venv
.venv/bin/pip install -r server/requirements-dev.txt
# Supply secrets through secure host environment configuration.
.venv/bin/python -m server
.venv/bin/python -m pytest tests/server -q
```

Run a single app process/instance and one engine with persistent storage. The queue is durable SQLite, not a horizontally scaled job platform. Never expose upstream ports3000/5001 publicly. Encrypt host disks, restrict operator access and bound backup retention.

## Accounts and browser sessions

Requests are JSON. Auth mutations require the exact app `Origin`. Signed-in cookie mutations additionally require `X-CSRF-Token` from the current account response, held in page memory. Requests use same-origin credentials; cross-origin cookie sessions are unsupported.

| Route | Request / behavior |
| --- | --- |
| `POST /api/v1/auth/register` | `{email,password,name}`. Password12–128 chars, email at most254, name1–120. Default202 with `status:verification_required` after SMTP delivery; no session until verified. Explicit verification-disabled configuration returns201 with account/session. |
| `POST /api/v1/auth/login` | `{email,password}`. Account/session on success;401 invalid credentials,403 unverified email. |
| `POST /api/v1/auth/verify` | `{token}` from emailed `/#verify=TOKEN`; single use, one-hour expiry. Establishes session. |
| `GET /api/v1/auth/me` | Current account and session-bound `csrf_token`;401 when signed out. |
| `POST /api/v1/auth/logout` | `{}` with CSRF; revokes server session and clears cookie. |
| `POST /api/v1/auth/forgot-password` | `{email}`; generic202 whether account exists. SMTP absence/failure is reported instead of pretending mail was sent. |
| `POST /api/v1/auth/reset-password` | `{token,password}` from `/#reset=TOKEN`; single use,30-minute expiry. Revokes all sessions and requires signing in again. |
| `GET /api/v1/account/export` | Account, subscription summary and all owned gateway runs/context; excludes credentials and upstream resource IDs. |
| `DELETE /api/v1/account` | `{password}` plus CSRF. Requires password reauthentication, no active runs, no renewable subscription and no pending checkout. Revokes sessions, erases identity/gateway content, and keeps minimal encrypted references for pending remote erasure. Accounting records may remain. |

Account responses contain `user:{id,email,name,email_verified}`, `workspace:{id,name}`, `credits_remaining`, `subscription:null|{plan,status,current_period_end,cancel_at_period_end,checkout_pending}` and `csrf_token`. Each account owns an isolated workspace. Free signup grants zero credits, preventing anonymous provider spending.

Passwords use OpenSSL scrypt with fresh16-byte salts, N131072/r8/p1. At most two password hashes run concurrently. Opaque random sessions are SHA-256 hashed in SQLite, expire after seven days, and use Secure HttpOnly SameSite=Strict `__Host-` cookies. Localhost HTTP uses a separate development cookie name. CSRF values are session-bound HMAC tokens. Password reset/logout revoke server sessions. Rate limits precede hashing; responses do not echo passwords, provider bodies or tracebacks. Add edge rate limiting for distributed abuse; arbitrary forwarded IP headers are not trusted.

## Hosted subscriptions

Server-defined plans: Solo AUD49/month with30 credits, Studio AUD199 with150, Agency AUD599 with500. Credits are workload units, not dollars or unlimited compute. Monthly credits do not roll over. Failed/interrupted attempts retain reservations because upstream work may already cost money.

`POST /api/v1/billing/checkout {plan:solo|studio|agency}` and `POST /api/v1/billing/portal {}` return `{url}` for Stripe-hosted pages. Both require a signed-in verified account, same-origin CSRF and a server-bound customer. Operator bearer tokens cannot manage billing. Checkout validates configured Stripe prices against advertised AUD amounts/monthly intervals. Persistent idempotency keys protect pending checkout; existing subscriptions use the portal.

Configure snapshot webhook `POST /api/v1/billing/webhook`, API version **2025-06-30.basil**, for `checkout.session.completed`, `customer.subscription.created`, `.updated`, `.deleted`, `invoice.paid`, `invoice.payment_failed`. Raw-body HMAC signatures and five-minute timestamps are checked. Canonical Stripe resources are retrieved; one transaction deduplicates event IDs, invoice IDs and subscription periods. Only eligible paid initial/cycle invoices grant credits. Browser values, redirects and subscription-created events never grant them. Expired periods are rejected even if webhooks are delayed; revoked subscriptions cannot be revived by delayed paid snapshots. Account deletion shares the checkout lock and checks canonical billing state, preventing payment through a pending checkout after erasure.

Use Stripe test mode first. Unit tests do not perform live billing/provider calls. Provider spending caps remain necessary: rounds, entities and workload credits cannot impose a hard dollar limit on earlier ontology/graph work.

## Simulation API and durable queue

Account browsers use cookie+CSRF; operator workspaces may use `Authorization: Bearer <workspace token>`. Provision/rotate operator tokens:

```sh
docker compose exec gateway python scripts/provision-workspace.py --name 'Operator workspace' --credits 30
# Add --workspace-id UUID to rotate its token and replace the available allowance.
```

The token grants that workspace's entire data set; do not share it between unrelated customers. Only its SHA-256 digest is stored. It is not an individual login or billing identity.

`POST /api/v1/runs/quote {rounds:5}` returns `{credits_required:6,credits_remaining,sufficient}`. Authoritative reservation and job insertion share an SQLite transaction. `POST /api/v1/runs` responds202 and accepts:

```json
{
  "title": "New pricing message",
  "question": "How might members react to a 10% price increase?",
  "context": "Current membership is $40. Proposed price is $44 with additional benefits.",
  "audience": "Existing members of a community gym",
  "rounds": 5,
  "template": "pricing",
  "privacy": {"retention_days": 7},
  "consent_external_processing": true
}
```

Limits: title1–120 chars, question10–4000, context20–30000, audience1–1000, rounds1–20, retention1–30 days, body100KB. Extra fields are rejected and explicit external-processing consent is required. Graph entity count is checked before profiles. Ontology/graph costs occur before that check.

`GET /api/v1/runs` returns `{runs:[...]}` for the100 most recent. `GET /api/v1/runs/{id}` returns `id,title,question,audience,rounds,template,status,stage,progress,created_at,updated_at,expires_at,credits_reserved,result,error,privacy_receipt`. Result is null or `{markdown:string}`. Render generated Markdown as escaped/sanitized content. Statuses: queued/building/preparing/running/reporting/completed/failed/interrupted. Cross-workspace IDs return404, including deletes.

Accepted jobs persist in `job_queue` and are atomically claimed. The supervisor heartbeats90-second leases. Unclaimed jobs survive restart without another deduction. Expired claimed jobs are stopped when possible and marked interrupted, **never automatically replayed** because paid work may already have started. New instances respect unexpired leases during deployment overlap. One process/instance remains supported; this is not exactly-once external execution. Operators must inspect interrupted jobs before retries. Private engine requests may continue after an HTTP timeout.

The adapter drives real ontology upload, graph/tasks, entity checks, create/prepare/start, simulation polling and report generation. Upstream keeps its process alive for interviews after `simulation_end`: the adapter closes that environment after `twitter_completed`, then waits for a terminal runner before reporting. It does not infer completion from100% progress. Calls use fixed private origin, English locale, no redirects and bounded timeouts.

## Data protection and erasure

Gateway content/reports/errors/upstream references are Fernet encrypted. Identity fields, statuses, timestamps, credits and financial reconciliation metadata are plaintext operational records. This is server encryption, not end-to-end inference or protection from an operator holding the key. MiroFish processes plaintext and writes its own source/profile/artifact volume, requiring host disk encryption/access control. The LLM provider and Zep Cloud receive context under their contracts and retention policies. No zero-retention, backup-erasure, residency or training-use guarantee is implied.

`DELETE /api/v1/runs/{id}` accepts terminal runs only. Its receipt includes `gateway_deleted`, `upstream_cleanup`, `cleanup_pending`, `cleanup_task_id` and limitations. It attempts project/cloud-graph and report deletion, plus authenticated terminal simulation-artifact deletion when the hardened engine/shared secret are configured. A generic missing endpoint does not prove erasure. Unsupported/failed cleanup keeps a minimal encrypted resource ledger without customer brief/report.

Terminal gateway runs expire1–30 days from creation. A minute sweep attempts deletion, retries up to three pending cleanup tasks per pass, and clears fully acknowledged tasks. The service must be running. Active jobs can exceed retention until terminal. Backups/logs require their own lifecycle; unknown IDs from timed-out upstream creation require operator review.

```sh
docker compose exec gateway python -m server.cleanup --list
docker compose exec gateway python -m server.cleanup --retry
# Only after verifying remaining copies have been handled:
docker compose exec gateway python -m server.cleanup --resolve TASK_ID
```

`--list` exposes private resource IDs only to trusted host operators. `--resolve` is operator attestation, not a remote erase action. Keep encryption keys available until cleanup completes.

Synthetic participants are not representative customer surveys/calibrated probabilities. Validate critical decisions with real people. Automated tests cover auth/CSRF, isolation, encryption, quotas, queue recovery, Stripe signatures/idempotency/entitlements and the engine protocol using mocks. They do not establish provider readiness, certification or production load capacity.
