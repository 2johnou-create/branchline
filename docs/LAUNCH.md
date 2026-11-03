# Launch status and remaining work

Prepared 3 November 2026. This is a launch guide for the actual pilot architecture, not a claim that every item below has been completed. Native hosting and GitHub results reported by the build owner determine the current public URL and repository state.

## What this build is

Branchline is a new interface around a pinned, vendored copy of MiroFish. The public interface can be used as a browser demonstration without provider credentials. It provides a guided brief, local common-pattern redaction, a submission preview, illustrative reports, export, privacy explanations, and proposed plans.

The separate FastAPI gateway provides operator-provisioned workspace authentication, workspace-scoped runs, encrypted request/report fields in SQLite, workload quotas, live job orchestration through a private engine, status polling, and best-effort cleanup receipts. The backend is a **single-process pilot**: run one gateway worker. SQLite persists state, but job execution uses in-process tasks. A restart marks unfinished runs interrupted rather than replaying them silently.

The private engine wrapper disables standard Python logging and removes engine browser CORS headers without modifying the vendored engine. Engine simulation artifacts still require encrypted host volumes and an operator cleanup procedure.

## Public demo versus live service

| Capability | Public browser demo | Connected pilot |
| --- | --- | --- |
| Open the interface and examples | Available once the static interface is deployed | Same interface |
| Analyse a supplied brief | No; sample reports are prewritten | Requires reachable configured gateway, private engine, and provider credentials |
| Save server-side runs | No | Workspace-scoped encrypted content in SQLite |
| User signup and identity management | Not implemented | Operator-provisioned shared workspace bearer token |
| Self-service checkout or subscription renewal | Not implemented | Not implemented |
| Automatic complete deletion of all copies | Not provided | Gateway deletion plus best-effort upstream requests; operator/provider copies have separate handling |
| Measured provider-cost billing | Not implemented | Pilot formula is one plus the selected round count |
| High-availability, durable distributed jobs | Not implemented | Single-process pilot only |

Do not open paid subscriptions on the strength of a working public demo alone.

## Connect a live pilot

1. **Choose infrastructure the operator controls.** Host the gateway and engine as long-running container services with private network connectivity. Static hosting alone cannot execute the Python simulation workload. Use TLS for the public gateway. Keep the MiroFish engine port private.
2. **Set provider configuration securely.** Supply an OpenAI-compatible LLM key, base URL, pinned model revision where supported, and a Zep API key. Check the provider regions, account terms, budgets, and retention. Enter secrets into the host's secret manager or environment; do not commit them or place them in frontend settings.
3. **Set gateway configuration.** Provide `BRANCHLINE_ENCRYPTION_KEY`, a persistent `BRANCHLINE_DATABASE` path, exact `BRANCHLINE_ALLOWED_ORIGINS`, and a server-controlled `MIROFISH_BASE_URL`. Review `BRANCHLINE_MAX_ROUNDS`, `BRANCHLINE_MAX_AGENTS`, and `BRANCHLINE_JOB_TIMEOUT` for the intended pilot. The checked code caps configured rounds at 20 and entities at 40.
4. **Prepare data operations.** Use encrypted volumes for gateway storage and all engine artifacts. Set permissions, backup expiry, recovery, and deletion responsibilities. Gateway field encryption does not cover plaintext engine files or every metadata column. Follow [PRIVACY.md](./PRIVACY.md).
5. **Provision a pilot workspace.** Follow the [gateway operating guide](../server/README.md#start), using `docker compose exec gateway python scripts/provision-workspace.py --name 'My pilot workspace' --credits 30` to create a unique token and bounded credit balance. Share that token through a suitable private channel. Keep different clients in different workspaces. Token rotation replaces workspace access; it does not create a per-person identity system.
6. **Connect the interface.** Configure the HTTPS gateway URL and workspace token in Workspace settings. Confirm capabilities and current limits before enabling a live submission. The connection belongs to the current tab session; users need to protect the token.
7. **Run a non-sensitive end-to-end rehearsal.** Verify graph creation, participant preparation, round limits, report generation, status display, export, and cleanup. The build can be tested against a mocked engine without proving that real provider credentials or the hosted live path work.

Hosting and paid API use can incur costs. The operator must choose and configure the infrastructure and provider accounts; a source repository does not create those accounts or pay their invoices.

## Pilot operating limits

The current credit formula is **1 + rounds**. Credits are deducted when a run is accepted. It is a workload quota, not a financial invoice, exact dollar quote, token meter, or automatic refund ledger. The business proposal's cost-based credit design is future work.

Entity limits are checked after graph construction; a rejected large graph can already have used provider resources. Round and time limits help bound work but do not guarantee a hard provider-spend cap, especially during preparation, reporting, retries, or incomplete upstream stopping. Set provider-side budgets and alerts, monitor job cost, and establish an operator stop/cleanup procedure.

Test restart and timeout behavior before onboarding customers. Interrupted tasks can leave engine work or artifacts requiring review. Do not scale the supplied gateway with multiple workers or instances sharing the same SQLite pilot database and in-process task model.

## Before accepting payment

The proposed business plans are Solo A$49/month, Studio A$199/month, and Agency A$599/month. Prices, included credits, seats, and features in [BUSINESS.md](./BUSINESS.md) are a commercial proposal. The app must clearly label plans as proposed and avoid an active-looking purchase path until checkout is implemented.

Complete these items before charging:

- Select the actual contracting business, supported customers, currency, tax treatment, refund policy, cancellation terms, and support contact.
- Implement user accounts and workspace membership, token revocation, roles where needed, and administrative recovery. Keep tenant authorization enforced on the server.
- Add a durable job queue and worker lifecycle if reliability or scale goes beyond a managed pilot. Specify idempotency, retries, cancellation, reconciliation, and recovery from partial engine failures.
- Record actual provider usage and cost; benchmark realistic workloads; implement explicit credit reservations, reconciliation, failure refunds, and enforceable budget limits before marketing compute allowances.
- Configure payment checkout in test mode, signed and idempotent webhooks, entitlement updates, renewal failures, customer cancellation, and billing history. Verify the full lifecycle before live keys are enabled.
- Publish accurate privacy, processor, retention, export, deletion, and backup information. Implement monitoring and an auditable path for pending cleanup rather than equating a local row deletion with full erasure.
- Complete the release verification below and document the live provider configuration. Keep a rollback and customer incident contact path.

## Release verification

Verify the public interface on desktop and mobile, keyboard navigation, dialog focus, sample labels, safe report rendering, local redaction limits, export, and disconnected/error states. Check that demo mode makes no live-run claim and that subscription controls do not imply billing is enabled.

For the live gateway, verify unauthenticated access denial; workspace A cannot read or delete workspace B's run; malformed inputs do not echo confidential content; quotas apply atomically; non-allowed origins are not granted browser access; a failed or timed-out job produces a safe message; and deletion reports unresolved upstream cleanup truthfully. Confirm provider keys and real customer data are absent from Git history and static assets.

Test live cleanup using known non-sensitive IDs. Verify the project and graph path, report path, manual simulation-artifact removal, gateway retention, and backup-expiry procedure. Check the encrypted pending-cleanup ledger with `python -m server.cleanup --list`, retry supported remote operations, and resolve tasks only after manual verification. Keep the provider's retention boundary visible to customers.

## Open-source release

Retain upstream notices and the AGPL licence, identify the product's modifications, and keep the Source link pointing to the Corresponding Source for the version being served. The repository should contain code and configuration examples, not customer documents, tokens, provider keys, runtime databases, or generated simulation data. Review dependency obligations before a commercial release. The current architecture does not establish an exemption from AGPL obligations through API separation.

## First commercial milestone

Use five design partners and one repeatable agency workflow before adding broad features. Measure useful decision briefs, real-world validation, repeat usage, successful job rate, completion time, actual job cost, support time, and retention. Sell the value of clearer decisions and managed private infrastructure; do not guarantee future outcomes or present synthetic people as actual survey respondents.
