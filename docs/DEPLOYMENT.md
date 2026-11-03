# Deploying the full Branchline platform

The repository contains a static demonstration and a separate full application. The full application serves the interface and authenticated API from one HTTPS origin, with MiroFish running as a private service. The static demonstration cannot host Python jobs, account sessions, email delivery, or Stripe webhooks.

Start with [SETUP.md](SETUP.md) for account creation and provider setup. This guide explains the deployment architecture and operating requirements. Deploying paid infrastructure or activating live payment collection remains the operator's choice.

## Recommended Render topology

Use the repository-root `render.yaml` Blueprint. It declares the application and engine as separate single-instance Docker services in Singapore:

| Service | Exposure | Proposed resources | Persistent mount |
| --- | --- | --- | --- |
| `branchline-app` | Public HTTPS application/API | `1c-2g` | 1 GB at `/data` |
| `branchline-engine` | Private HTTP service on port 5001 | `2c-4g` | 10 GB at `/app/backend/uploads` |

These allocations are starting assumptions for a small pilot, not measured capacity or a price quote. One live job globally, at most 20 graph entities and 10 rounds, is the Blueprint's initial limit. Measure memory, disk growth, duration, and provider spend before widening limits. Confirm the actual cost in Render before creating services.

Render's `pserv` service has no public URL; same-workspace services in the same region can reach it over the private network. Keep the engine private. The gateway's `MIROFISH_PRIVATE_HOSTPORT` uses a `fromService` reference; Python adds the HTTP scheme because Blueprint YAML does not interpolate environment variables. [Render private services](https://render.com/docs/private-services), [private networking](https://render.com/docs/private-network), [Blueprint specification](https://render.com/docs/blueprint-spec)

## Create and configure the deployment

1. Connect the Branchline GitHub repository to a Render workspace and create a Blueprint from the repository's `render.yaml`. Review both paid services and disks before approving creation. Do not add another public web service for the engine.
2. Supply engine secrets when prompted: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, and `ZEP_API_KEY`. Use your own provider accounts and approved data-processing configuration. These are required for real work; test placeholder values only establish that a container can start.
3. Supply the application SMTP host, port, username, password, and sender address. Verification email is required by default; without a configured mail path, self-service registration stays unavailable. Use a verified sender/domain and TLS-enabled delivery.
4. Preserve the generated `BRANCHLINE_MASTER_SECRET` and shared `BRANCHLINE_ENGINE_CLEANUP_SECRET` securely. The master secret derives the gateway field-encryption key. Do not regenerate it for an existing database without an explicit migration. The shared cleanup secret must match on both services.
5. Deploy the engine and application. Keep one instance and one application process. Open the app's HTTPS URL, inspect `/api/v1/config`, and confirm the interface discovers the same-origin service. `/health` checks liveness, not successful model inference.
6. Register, verify email, sign in, and verify reset/logout behavior. A new self-service account starts with zero credits. For a non-paying pilot, an operator can allocate credits to its existing workspace with the provisioning command in [server/README.md](../server/README.md); do not create an unrelated second workspace and expect it to become that account's workspace.
7. Run a small non-sensitive scenario with operator-allocated credits. Confirm graph creation, participant preparation, a bounded simulation, a readable report, the quoted workload-credit deduction, export, and deletion receipts. Inspect cleanup before repeating a failed or timed-out run.
8. Configure Stripe in test mode only after the real engine path works. The separate billing launch flag remains off until the operator deliberately enables it after testing. See the billing section below.

Render can build the repository's Dockerfiles directly. Keep provider values in Render environment/secret settings; never add secret-bearing build arguments or commit `.env`. [Docker deployment](https://render.com/docs/docker), [environment variables and secrets](https://render.com/docs/configure-environment-variables)

The application uses `BRANCHLINE_PUBLIC_URL`, or Render's supplied external URL, as its account origin. If attaching a custom domain, set the exact new HTTPS origin explicitly, update allowed origins and email links, and redeploy. Same-origin cookie sessions are required for public accounts; an account hosted on the static demo's separate origin cannot be enabled by CORS alone. The optional operator bearer connection remains a separate pilot workflow.

## Enable subscription checkout deliberately

Configure three Stripe recurring monthly Prices: Solo A$49, Studio A$199, and Agency A$599, in AUD, quantity one. Set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_STUDIO`, and `STRIPE_PRICE_AGENCY` on the application. The module verifies each configured Price before creating checkout; browser-supplied customer IDs, prices, or amounts are not accepted.

Create a **snapshot** webhook destination at `https://YOUR_APP_ORIGIN/api/v1/billing/webhook`, using API version **`2025-06-30.basil`**. Subscribe to:

- `checkout.session.completed`
- `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`
- `invoice.paid`, `invoice.payment_failed`

The code verifies the raw request signature, retrieves current provider resources, and grants monthly credits only from matching paid subscription creation/cycle invoices. Checkout redirects grant nothing. Event, invoice, and subscription-period uniqueness prevent replayed grants. Monthly allocations replace unused subscription credits and expire at the paid period end. [Stripe Checkout subscriptions](https://docs.stripe.com/payments/checkout/build-subscriptions), [webhook setup](https://docs.stripe.com/events/set-up-events), [Basil invoice changes](https://docs.stripe.com/changelog/basil/2025-03-31/adds-new-parent-field-to-invoicing-objects)

Configure the customer portal for payment details, invoices, and cancellation. Keep immediate plan switching and prorations disabled for this release: proration/update invoices do not refill a monthly allowance. Decide tax behavior, tax collection, customer terms, refund handling, and support before live keys. This module does not automatically enable Stripe Tax or issue refunds.

Only set `BRANCHLINE_BILLING_ENABLED=true` after the engine, email, test checkout, paid invoice webhook, renewal, cancellation, and duplicate-event paths have been verified. `BRANCHLINE_ENGINE_ENABLED=true` is also required for new checkout. This is an operator-controlled launch gate, not automated proof of provider readiness. Pausing new checkout or the engine leaves configured webhooks and the existing customer portal available, so customers can still manage billing. [Stripe customer portal](https://docs.stripe.com/api/customer_portal/sessions/create)

## Persistence and operations

Render disks and snapshots are encrypted at rest. Only the mounted paths persist; disks are attached to one instance, unavailable to build/pre-deploy/one-off jobs, and disable zero-downtime deploys. Daily snapshots remain available for seven days. Maintain a consistent SQLite backup procedure and separate key backup; do not treat an arbitrary filesystem snapshot as a verified database recovery plan. [Render persistent disks](https://render.com/docs/disks)

Provisioning, cleanup inspection, and database operations must run in the **existing application's** Dashboard Shell/SSH session, not an ephemeral shell or one-off job without its persistent disk. Verify mounted directories are writable by the application user and restrict shell access. [Render shell access](https://render.com/docs/ssh)

Accepted jobs are persisted in SQLite and claimed by the single-process supervisor. Unclaimed queued jobs survive restart; jobs already handed to the engine become interrupted and are not automatically replayed. Do not deploy during an active simulation. Two-hour application timeouts, upstream stopping, and entity/round limits reduce exposure but do not guarantee a provider invoice cap. Set provider-side budgets and alerts.

The gateway stores encrypted request/report fields, while the engine writes plaintext application files on its encrypted host disk. The private cleanup extension removes a completed simulation directory only after validating its identifier and checking active engine producers. Busy/failed cleanup remains in an encrypted remediation ledger and is retried. No local acknowledgement proves erasure of provider logs or backups. See [PRIVACY.md](PRIVACY.md).

## Alternative Docker host

The same application can run on an operator-controlled Linux Docker host using `docker compose`. Copy `.env.example`, configure the exact public application origin and secrets, then build and start the two services. Put a TLS reverse proxy in front of the gateway's localhost port 8080; keep engine port 5001 unpublished. Use encrypted volumes, backup expiry, resource limits, and monitoring. Serve the interface from the gateway for account sessions.

A native install needs Python 3.11 or 3.12, a compatible dependency environment, Cairo/OpenMP libraries, and writable engine storage. The engine Dockerfile uses CPU PyTorch while leaving vendored source/lock unchanged, avoiding unnecessary CUDA wheels. The authoring Mac's default Python 3.9 is incompatible; remote Linux Docker validation is the preferred verification path. Container health/import checks do not run a paid model call. Review the [runtime validation workflow](https://github.com/2johnou-create/branchline/actions/runs/41620745805) and current repository checks for the exact tested revision.

## Release and update discipline

Review vendored upstream changes before replacing the revision in `NOTICE`, rerun adapter and cleanup tests, and publish the Corresponding Source for the served AGPL release. Preserve source and licence notices. Keep runtime databases, uploaded documents, outputs, credentials, and payment secrets out of Git history. See [LAUNCH.md](LAUNCH.md) for the remaining commercial release gates.
