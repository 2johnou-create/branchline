# Branchline privacy and data handling

This guide describes the source implementation as of 3 November 2026. It is an architecture guide, not a completed legal privacy notice or a certification. Before accepting live customer data, the operator must publish its identity/contact, actual providers, configured regions, retention/backup periods, and customer terms.

## Static demonstration and full application

The static demonstration uses sample scenarios and prewritten illustrative reports. A demo report does not analyse a submitted brief or run MiroFish. By default, drafts and imported text stay in the browser tab's memory; closing or reloading ends that in-memory draft. An optional operator workspace token also stays in memory. Downloaded exports, screenshots, browser extensions, and host access records are separate copies or access paths outside that promise.

The redesigned builder has an unchecked **Save this draft on this device** option. Only after that explicit choice, builder text fields, template and round settings can be stored in this browser's localStorage for up to seven days. Passwords, session or operator tokens, and external-processing consent are excluded. Resume and Remove controls are visible. Disabling the option or choosing Remove device copy deletes the stored copy while keeping the current in-memory draft. Clear local removes both after confirmation; signing out or changing account also clears both. A successful real submission removes its matching saved copy, while leaving an unrelated saved device draft unchanged. A shared browser profile can expose an opted-in draft to someone using that profile. The seven-day expiry is checked when the application next runs; it is not a background erasure guarantee for an offline device.

The full application serves its interface and API from one HTTPS origin. It supports individual accounts and a private workspace. Email/name, password hashes, hashed session/mail tokens, workspace metadata, and billing references are stored server-side. The account session uses a Secure, HttpOnly, SameSite=Strict cookie on HTTPS and lasts up to seven days unless expired or revoked sooner. The session-bound CSRF token stays in page memory. Signing out revokes the current session; resetting a password revokes that user's existing sessions.

Provider keys remain server-side. Live simulations require an enabled gateway, private engine, configured model/Zep credentials, and an approved submission. New checkout additionally requires explicit operator activation. Static hosting alone does not activate these services.

## Local redaction and review

The interface masks common email-address and phone-number patterns and shows the reviewed payload before submission. This is not comprehensive anonymisation. Names, locations, rare events, customer stories, unusual identifier formats, and business secrets may remain. Inspect title, question, audience, and context; zero detected matches does not mean a brief is safe to share.

Importing text reads the file in the browser. A later live submission sends the reviewed text. “Read locally” describes the import step, not a promise that an approved cloud brief never leaves the device. Do not include personal information about real people unless you are authorised to process it through the selected providers.

## Data flow

```text
Browser: draft -> local redaction -> reviewed approved brief
  -> HTTPS application gateway: account/session, workspace, encrypted run payload
    -> Private MiroFish engine: source, graph references, personas, simulation files/report
      -> Operator-configured LLM provider
      -> Zep Cloud

Account verification/recovery -> operator-configured SMTP provider
Billing actions -> Stripe-hosted Checkout/portal -> signed webhook -> credit ledger
```

The web host can process connection/access metadata. SMTP processes the account email and a one-time verification or reset link. Stripe processes payment/customer information in its hosted pages; Branchline does not collect card numbers. The billing integration sends opaque user/workspace identifiers as metadata and retains Stripe resource IDs, subscription status/periods, processed event IDs, and credit-grant records. The operator must add actual provider identities and policies to its public notice.

Credit wallets retain free, current-subscription and banked balances, refill/period timestamps and grant/payment identifiers needed for accounting and duplicate protection. These are operational metadata, not encrypted run content. A verified account can receive up to four free credits every 48 hours on any plan; missed periods do not stack. A refill does not share a scenario, submit a job or send a reminder. Purchased/operator banked credits remain separate from the periodically refreshed free allowance and the expiring monthly allowance. Privacy, export and deletion controls do not require a paid plan.

To prevent deletion and recreation with the same verified email from restarting a free window, the gateway retains a short-lived **keyed email marker and refill deadline** for the current 48-hour allowance window. The marker does not contain the raw email, name, brief, report, password or session token. Account deletion can leave this marker until its current window expires, up to 48 hours; the running gateway purges expired markers from the active database. Service downtime can delay that purge, and database journals or operator backups can retain earlier copies until their separate expiry. This is pseudonymous abuse-control metadata, not anonymous data: an operator holding the key and a candidate email can recompute the marker. It does not establish a permanent identity link or prevent every form of multiple-account abuse.

## Implemented controls and boundaries

| Control | Covers | Boundary |
| --- | --- | --- |
| Password hashing | Salted scrypt hashes rather than plaintext passwords | Does not protect against a compromised live application or user device |
| Sessions and CSRF | Hashed session records, HttpOnly secure cookie, same-origin checks and session-bound CSRF for account mutations | No MFA, SSO, team role model, or per-person team administration is provided |
| Workspace authorization | Run queries require the authenticated account/workspace or a valid operator token | An operator bearer token grants its whole workspace's authority; do not share it between unrelated clients |
| Payload encryption | Fernet-encrypted request, report, error, upstream-reference and cleanup payloads in SQLite | Server-side processing can decrypt them; this does not encrypt every metadata column or engine file |
| Request/job controls | Request-size, rate, active-run, entity, round and time limits | These are not a guaranteed provider-invoice cap or a complete abuse-prevention service |
| Logging changes | Gateway safe errors avoid returning raw upstream bodies; wrapper disables standard Python engine logging | Subprocess artifacts, stdout/stderr, infrastructure logs and provider records need separate handling |
| Private engine | No public engine service in the recommended deployment; shared secret for cleanup extension | Trusted host/network operators can still access data; the native engine API is not a public tenant boundary |
| Billing integrity | Server-selected prices/customers, signed raw-body webhooks, current-resource checks and atomic grant ledger | Accounting/provider records have a separate retention lifecycle; financial disputes/refunds need operator handling |

Gateway workspace names/IDs, account email/name, password hashes, run status/timestamps, credits, and financial references are not all protected by private-run-payload encryption. Use encrypted host disks, restrictive permissions, TLS, secret management, and protected backups. Keep the encryption/master secret separately recoverable; losing it makes encrypted content unreadable. Rotating a master secret without a migration is not supported.

MiroFish source files, generated personas and simulation artifacts are plaintext at the application filesystem level. An encrypted host volume protects storage media, not data from an authorised engine process or operator. The system does not provide end-to-end encrypted inference: the application, engine and external inference/graph services process readable content.

## Run retention and deletion

A run can choose a gateway retention period of 1–30 days. Its deadline starts at creation. The running gateway periodically scans expired terminal runs; ongoing jobs, service downtime, upstream busy responses, or failures can delay cleanup. Do not promise an exact deletion instant.

A terminal-run deletion attempts to stop remaining simulation work, delete its report, and delete its project/referenced cloud graph. With the hardened engine and matching cleanup secret, it also requests removal of the simulation directory. The extension validates a bounded simulation identifier and refuses deletion while relevant tasks, processes, or monitor threads remain active. A generic missing route is not treated as evidence that files were erased.

Receipts distinguish acknowledged operations, resources not created, and operations needing attention. Pending remote cleanup retains only encrypted resource references and acknowledgements in a separate ledger, without the customer's brief or generated report. The running gateway retries supported operations. Operators can list/retry tasks with `python -m server.cleanup`; manual resolution is an operator attestation after inspection, not independent proof of remote erasure.

The upstream engine itself has no complete simulation-artifact deletion API; Branchline adds a narrow private extension around the vendored source. Older engines without that extension, busy resources, paths outside its supported directory, and orphaned work without a recorded ID need operator review. Keep backups, volume lifecycle and incident procedures consistent with the public notice.

Gateway row removal does not revoke exports or screenshots. Database WAL pages, snapshots and backups may retain earlier encrypted data until expiry. Provider logs, model-service retention and Zep backups have separate policies. Current Zep documentation describes internal copies surviving context deletion, including disaster-recovery backups up to 365 days and graph write logs up to 90 days; verify the deployed API/account and contractual terms rather than treating those as Branchline-enforced limits. [Zep retention documentation](https://help.getzep.com/context-retention)

## Account export and deletion

A signed-in account can export its current account details and runs, including stored context. Deletion requires its password and no active simulations. The checkout/deletion lock prevents starting a new checkout while the account is being frozen. Existing active subscriptions must be cancelled before deletion; unexpired pending checkout also blocks deletion to avoid a later charge on an erased account.

Account deletion disables the user, clears account email/name/password data, revokes sessions and mail tokens, blocks its workspace and credits, and removes gateway run content into the cleanup workflow. Minimal anonymized account/workspace identifiers, encrypted pending-cleanup references, financial event/grant records, and the short-lived keyed free-allowance marker described above can remain under their separate lifecycles. Stripe, SMTP, hosting and other providers retain their own copies under their policies. A cancelled subscription is not automatically a deleted Stripe customer or erased accounting history.

## Claims this build does not establish

Do not advertise zero retention, immediate complete erasure, Australian-only processing, automatic model-training exclusion, end-to-end encrypted computation, or a compliance certification. Singapore hosting is not Australian residency; a host region also does not constrain model and graph processing. Customer-provided API keys do not by themselves alter provider terms.

The processing receipt describes gateway retention and processor categories. The operator must publish exact provider names, regions, policy links and backup periods. Keep unavailable checks visibly unresolved rather than converting them into a success badge.

Synthetic participants are fictional. Their statements and percentages are not evidence of actual people's views or calibrated forecasts. Keep that limitation with reports and validate decisions through real customer research.

An animated network or particle field is an illustration of the computation journey. It is not evidence that the service is executing millions of agents, surveying real people or producing a finding at every animation frame. Only separately labelled observed telemetry establishes the active run's actual agent, round and action counts; unavailable measurements remain unavailable.

## Before live use

Configure HTTPS origins, host restrictions, a private engine, strong application and cleanup secrets, encrypted storage, protected backups and expiry, provider budgets, SMTP, accurate notices, and a responsible operator. Disable prompt/body/token capture in proxies and monitoring. Verify a non-sensitive live run, cross-workspace denials, recovery, expiry, deletion receipts, automatic retries, and account/billing deletion boundaries before onboarding customers.
