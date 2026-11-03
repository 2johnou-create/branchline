# Branchline

**Rehearse your next move.** A public-facing decision rehearsal platform built around [MiroFish](https://github.com/666ghj/MiroFish).

[Live owner pilot](https://branchline-app.onrender.com) · [Static demo](https://branchline-studio.misty-jelly-1931.chatgpt.site) · [Setup and remaining steps](docs/SETUP.md) · [Business plan](docs/BUSINESS.md) · [Privacy](docs/PRIVACY.md)

## Implemented application

- Guided launch, pricing and response scenarios with a local redaction and exact-payload review.
- Same-origin signup, email verification, login, recovery and logout; hashed passwords/sessions, HttpOnly cookies and CSRF protection.
- Separate private workspaces, encrypted brief/report payloads, account export and account deletion.
- Server-quoted workload credits, atomic reservations, persisted single-node job claims/leases, restart handling and bounded MiroFish orchestration.
- Real engine graph/profile/simulation/report flow, including orderly closure after the selected rounds finish.
- Optional Stripe-hosted checkout and portal, signed webhooks, idempotent invoice credits and subscription lifecycle handling.
- Per-run retention, authenticated private simulation-file deletion, encrypted unresolved-cleanup records and automatic retries.
- Responsive browser interface, safe report rendering and clearly labelled optional prewritten examples.

**Deployment status:** the application is deployed at [branchline-app.onrender.com](https://branchline-app.onrender.com), with its MiroFish engine running privately on Render. This is an owner-only email pilot: signup, verification, signed-in accounts and credit balances work. A real one-round test completed automatically through graph building, participant preparation, recorded simulation actions and report generation. Subscription checkout is paused. The Sites address remains a separate static demonstration. Public email delivery needs a verified sending domain; public onboarding, live cleanup verification and Stripe activation remain in [the setup guide](docs/SETUP.md). Reports use recorded output; live follow-up interviews are unavailable after the simulation closes.

## First-time setup

Follow [SETUP.md](docs/SETUP.md) to create the provider accounts and configure their secrets. The Render Blueprint deploys the combined public app/API and a private engine, with persistent disks. Review Render's paid resources before approval. The private engine receives model/Zep keys; the public application receives account/email/payment settings.

Allowed pilot users sign in to the combined application URL; they do not need a gateway URL or workspace token. Advanced operator tokens remain available for pilot provisioning and live verification. Expanding registration beyond the owner requires a verified sender domain and an explicit change to the signup allowlist; keep allowed addresses in hosting settings rather than public source.

For your own Docker host:

```sh
cp .env.example .env
# Replace the generated-secret placeholders and configure providers/SMTP.
docker compose up --build -d
```

Open `http://127.0.0.1:8080` for the local combined app. Set its exact HTTPS public origin before production. Keep the native engine port private. Enable `BRANCHLINE_ENGINE_ENABLED` only after configuring the engine, and enable `BRANCHLINE_BILLING_ENABLED` only after verification. See [the server operating guide](server/README.md) for every setting and route.

To preview only the static interface without accounts/inference:

```sh
python3 -m http.server 8081 --directory dist --bind 127.0.0.1
```

## Verify

Python 3.12+ for the gateway; the engine image pins Python 3.11. The CPU container installer preserves upstream's frozen dependency versions while selecting the matching official CPU PyTorch build instead of unnecessary CUDA packages.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements-dev.txt
.venv/bin/python -m pytest tests -q
node --check dist/app.js
node --check dist/platform.js
```

GitHub Actions also builds both Docker images and imports the real OASIS runtime, then checks the private engine health/CORS/cleanup protections without any network or provider credentials. Account, payment and upstream API tests use fixtures/mocks; passing them does not establish actual provider access, mail delivery or research quality.

Once the operator has configured a deployment, provision a small verification workspace and run:

```sh
python scripts/verify-live.py --api https://YOUR-APP.onrender.com
```

That command performs real one-round work and can incur provider charges. See the [setup guide](docs/SETUP.md#5-verify-real-inference-before-charging-customers) before running it.

## Data and commercial boundaries

Cloud inference processes plaintext. Gateway field encryption does not encrypt every metadata column or the engine volume. Use encrypted disks/backups, protect the master secret, and inspect deletion receipts: provider backups and legally retained payment records have separate lifecycles. [Full data flow and retention details](docs/PRIVACY.md).

Credits are bounded workload allowances (`1 + rounds`), not a measured provider-spend guarantee. Plans are AUD49/199/599 monthly with 30/150/500 credits, with operator-configured Stripe Prices. Configure tax presentation, terms and support before live checkout. This is a single-instance service with a durable SQLite queue, not a horizontally scaled hosted enterprise platform. [Launch and operating requirements](docs/LAUNCH.md).

## Source

| Path | Purpose |
| --- | --- |
| `dist/` | Public interface; no third-party scripts or analytics |
| `server/` | Accounts, workspaces, billing, jobs, storage and engine adapter |
| `tests/` | Isolation, accounts, billing, queue and erasure tests |
| `engine/mirofish/` | Unmodified upstream source pinned at 7657031ac01184afe2cb220f5ee3545573b5e843 |
| `deploy/` | Container startup, CPU dependency installer, private WSGI and erasure extension |
| `render.yaml` | Reviewed-host deployment configuration with private networking and disks |
| `docker-compose.yml` | Local/VPS deployment |
| `docs/` | Setup, privacy, deployment and business plan |

## Licence

GNU AGPL-3.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Original MiroFish notices remain in the vendored source. Branchline adds the interface, SaaS gateway, deployment files and private cleanup extension. Preserve the corresponding-source link and build instructions when serving a modified release. The project is not affiliated with the original MiroFish authors.
