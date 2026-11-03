# Deploying Branchline

The public interface and the compute service have different hosting requirements. The interface is already configured as a static Sites deployment. The engine needs a persistent Docker host and provider credentials; it is not running on the static host.

## Static interface

Serve the contents of `dist/` on HTTPS. No build step, frontend credentials or database are required. The interface starts in sample mode and makes no engine calls until someone connects a workspace. Its source link points to the public repository. Sites uses `.openai/hosting.json` to select `dist/` for this project.

## Connected pilot

1. Clone `https://github.com/2johnou-create/branchline.git` on an operator-controlled Docker host. Choose an encrypted persistent disk and restrict operator access. Do not store customer source material in the Git checkout or source repository.
2. Copy `.env.example` to `.env`. Set LLM/Zep keys on the server, configure the exact browser origin and generate the gateway encryption key. Keep an independently protected backup of the encryption key.
3. Build with `docker compose build`. The first build downloads the upstream Python simulation stack and can be substantial. This build has not been executed in the authoring environment because Docker is unavailable there.
4. Start with `docker compose up -d`. Check `docker compose ps` and `docker compose logs --tail=50 gateway`. The public `/health` checks gateway liveness only. Keep logs restricted and never paste logs containing secrets or customer content into public issues.
5. Put an HTTPS reverse proxy on an API hostname of your choice, forwarding only to `127.0.0.1:8080`. Configure a 100 KB request limit and redact Authorization headers from access logs. Do not publish engine port 5001 or expose Docker's daemon.
6. Provision a workspace with `docker compose exec gateway python scripts/provision-workspace.py --name 'Pilot workspace' --credits 30`. Store the issued token securely. Issue a separate token/workspace for each unrelated customer.
7. Open Branchline Settings and connect the HTTPS API URL and workspace token. Submit an explicitly non-confidential brief with one round. Verify each stage reaches a real report, the usage deduction matches the quote and refresh/restart behavior is understood.
8. Delete that test run, inspect its receipt and complete any pending upstream cleanup. Recheck the private engine volume and processor dashboards rather than assuming a gateway acknowledgement erases every copy.

For local API testing the gateway remains on `http://127.0.0.1:8080`. Serve the interface on another local port, for example `8081`, and allow that exact origin. A public HTTPS page may be unable to call a local HTTP endpoint due to browser mixed-content/private-network rules; use the local interface or an HTTPS API for that test.

## What this deployment does not activate

Deploying containers does not activate checkout, automatic subscription credits, multi-user accounts, SSO, roles, team invitations, dedicated customer infrastructure or a durable distributed job queue. A manually provisioned token grants access to its entire workspace. The pilot charges workload credits on acceptance and has no automatic failure refund; an operator adjusts credits after investigating.

Before taking payments, complete the gates in [LAUNCH.md](LAUNCH.md), including measured provider costs, provider spending caps and a verified small-budget real engine run. Set storage/backup retention and deletion operations that match the privacy policy you publish. The sample app is not a certification of security, privacy compliance or research accuracy.

## Updating the upstream engine

The original source is vendored at a specific Git revision, recorded in `NOTICE`. Compare and review upstream changes before updating it, preserve original notices and rerun gateway contract tests. Publish the corresponding source for every hosted covered release. Do not replace the pinned source with an unreviewed `latest` container tag.
