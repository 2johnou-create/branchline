# Branchline

**Rehearse your next move.** An accessible public interface for [MiroFish](https://github.com/666ghj/MiroFish), with guided briefs, browser-local redaction, explicit processing receipts, and a private engine gateway.

[Public app](https://branchline-studio.misty-jelly-1931.chatgpt.site) · [Business plan](docs/BUSINESS.md) · [Privacy and data flow](docs/PRIVACY.md) · [Deployment](docs/DEPLOYMENT.md) · [Launch requirements](docs/LAUNCH.md)

## What works now

- Public responsive dashboard with three guided scenario templates.
- Browser-local sample reports, editable briefs, identifier redaction preview, report/receipt exports and session data clearing.
- A separate connected mode for a deployed gateway. Connection tokens stay in page memory; model and Zep keys stay on the server.
- Authenticated workspace gateway with isolated run records, encrypted gateway storage, bounded workloads and a real MiroFish API adapter.
- Complete upstream engine source pinned at `7657031ac01184afe2cb220f5ee3545573b5e843`, plus private container configuration.

**The public deployment starts in demo mode.** Its example reports are prewritten illustrations, not live inference, measured customer sentiment or forecasts. Live jobs require your deployed backend and provider credentials. Signup, checkout, recurring billing, team invitations and automatic retention are not enabled. Plan prices describe the proposed business, not products currently available for purchase.

## Try the interface locally

No frontend package installation is required:

```sh
python3 -m http.server 8080 --directory dist --bind 127.0.0.1
```

Open `http://localhost:8080`. Drafts and credentials are lost on refresh unless a feature explicitly offers an opt-in save. Redaction detects common email and telephone patterns; inspect every outgoing field yourself.

## Run the real engine

You need Docker Compose, an OpenAI-compatible LLM account and a Zep Cloud account. Provider usage may incur charges. Start with a small brief and few rounds. No API key is needed to explore the browser demo.

1. Copy `.env.example` to `.env` and configure server secrets, provider keys, permitted browser origin and the gateway database encryption key. Follow [server/README.md](server/README.md) for the exact settings and workspace provisioning command.
2. Build and start with `docker compose up --build -d`.
3. Run `docker compose exec gateway python scripts/provision-workspace.py --name 'Pilot workspace' --credits 30`. Save the issued token securely; the database stores its hash. See the server README for rotation and credit resets.
4. In Branchline **Settings**, enter your gateway URL and workspace token. Inspect the returned capabilities before submitting a job.

The default gateway bind is local. For a public live service, place the gateway behind HTTPS on a server you control and set its exact public browser origin in CORS. Never publish MiroFish port `5001` or its original development UI. The compose configuration keeps the engine on a private container network. Use encrypted host disks for engine files and backups; gateway database encryption does not encrypt upstream simulation artifacts.

The gateway is intentionally a single application process. Background tasks are bounded but not a distributed durable job queue. Review restart recovery, cleanup receipts, token rotation, provider budgets and backup restoration before accepting paying customers. Workload credits are quotas; they are not a measured dollar spending guarantee.

## Source structure

| Path | Purpose |
| --- | --- |
| `dist/` | Standalone public app, with no third-party scripts or analytics |
| `server/` | Private-tenant gateway, storage and upstream adapter |
| `tests/server/` | Authentication, isolation, quota and engine-contract tests |
| `engine/mirofish/` | Unmodified pinned upstream source and notices |
| `deploy/engine_entry.py` | Private WSGI entrypoint; disables upstream Python request logging |
| `engine.Dockerfile` | Backend-only engine image, unprivileged runtime |
| `docker-compose.yml` | Gateway and private engine deployment |
| `docs/` | Business model, data boundaries and launch plan |

The cloud model and graph services process plaintext during inference. Engine files may retain source material and agent logs. The deletion receipt reports what was actually attempted; it does not certify removal from processor backups. See the privacy document before sending confidential material.

## Verify

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt pytest
.venv/bin/python -m pytest tests/server -q
node --check dist/app.js
python3 -m py_compile deploy/engine_entry.py
```

These tests use an HTTP mock for the upstream engine; they do not establish live model quality, provider billing or performance. Run a real small-budget end-to-end job after configuring your deployment.

## Public hosting

The static app is published using Sites. `.openai/hosting.json` identifies that deployment; only `dist/` is served. GitHub contains the corresponding source, including the separate Python engine. Sites' static hosting does not run the Python engine.

You can also serve `dist/` with any static HTTPS host and deploy the gateway on a separate Docker host. Set the gateway's CORS allowlist to the actual browser origin. Review the hosting provider's access logs and privacy terms before adopting a public privacy policy.

## Licence and attribution

GNU AGPL-3.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). MiroFish's original notices remain in the vendored source. Branchline adds a new interface, gateway and deployment files; the upstream engine is not claimed as original work. Keep a prominent source link for the version served and preserve source/build instructions when redistributing or changing the hosted application. This project is not affiliated with the original MiroFish authors.
