# Launch status and remaining work

Prepared 3 November 2026. The full application is deployed at [branchline-app.onrender.com](https://branchline-app.onrender.com), with a private MiroFish engine on Render. The [Sites address](https://branchline-studio.misty-jelly-1931.chatgpt.site) remains a separate static demonstration. The deployed application is an **owner-only email pilot**, with registration restricted through an operator-configured allowlist and subscription checkout paused.

A real SMTP test was delivered to the owner, and signup, email verification and sign-in have been exercised. A real one-round job completed automatically and returned a report; the engine recorded two actions and a completed round. The owner's separate run also completed. This deployment is not a public paid launch. Sender-domain verification, wider onboarding, live cleanup verification and Stripe activation remain separate steps in [SETUP.md](SETUP.md). Allowed email addresses stay in private hosting settings, not the public repository.

## Implemented in source

- A guided brief, local email/phone-pattern redaction, exact submission preview, workload-credit quote, live status, report rendering/export, and visibly labelled illustrative samples.
- Same-origin email/password accounts with email verification, password reset, server-side sessions in HttpOnly cookies, CSRF protection, sign-out, account export, and password-confirmed account deletion. Registration requires configured verification mail by default.
- A workspace-scoped gateway with encrypted request/report fields, request and active-job limits, server-enforced round/entity limits, credit reservations, and a persisted SQLite job queue managed by one application process.
- A private MiroFish adapter for the real graph/preparation/simulation/report flow. The hardened wrapper suppresses standard Python request logging and adds authenticated, bounded simulation-directory cleanup.
- Optional server-configured Stripe hosted Checkout and customer portal, raw-body signed webhooks, current-resource reconciliation, event/invoice/period deduplication, monthly non-rollover allocations, expiry, and cancellation handling.
- An encrypted ledger for unresolved upstream cleanup, automatic retry, and operator inspection/reconciliation.
- Docker services and a Render Blueprint that keep the engine private and preserve application and engine data on separate disks.

This list describes implemented code paths. The Render application, private engine, provider configuration and owner-pilot email path are now deployed; Stripe payment collection is not active. The static demonstration continues to offer local samples. A feature appearing in source does not by itself establish its end-to-end live verification.

## Verification boundary

The remote Linux engine validation exercises the real dependency stack, OASIS/CPU PyTorch imports, both local and Render port binding, the structured Twitter entrypoint, container health and response hardening without paid inference. See the [runtime workflow](https://github.com/2johnou-create/branchline/actions/runs/41630429808) and [98-test source checks](https://github.com/2johnou-create/branchline/actions/runs/41630430032). A separate real one-round hosted test completed automatically with structured actions and a stored report; its receipt is retained privately at `/data/live-verification-automatic.json`. Live email delivery and account verification have also been observed. Live deletion acknowledgements, account recovery/deletion and payment settlement remain to be exercised; their automated tests use controlled fixtures.

The pinned report API requires a terminal simulation. This pilot therefore reports from recorded output after the environment closes; live follow-up interviews are unavailable. Missing interview evidence must remain unverified, as explained in the report viewer. Generated output is synthetic rehearsal material, not observed customer research or a validated prediction.

Refer to the current CI run and build owner's results for the exact revision and count of passing checks. Later changes require their own checks; do not infer that a previous container run covers all subsequent edits.

## Remaining operator setup and verification

Use [SETUP.md](SETUP.md) for the guided setup and [DEPLOYMENT.md](DEPLOYMENT.md) for the complete host configuration.

1. Confirm report/account export, recovery, deletion receipts and live upstream cleanup. The hosted inference path and persistence across deployment have been exercised; deletion acknowledgements still need live verification.
2. Verify a sender domain and the public verification/recovery mail flows before wider onboarding. Keep the owner allowlist active until public registration is intended.
3. Review provider budgets, permitted processing, persistent storage, backup expiry, secret recovery and the operational contact for the deployed services.
4. After those checks, configure Stripe test mode, matching AUD monthly Prices, the pinned-version signed webhook and customer portal, then verify the billing lifecycle. Live keys and checkout activation remain a deliberate later operator action.

A source repository does not create these accounts, grant paid quotas, or pay provider invoices. Keep all secrets in the selected host's secret settings, never browser code or GitHub source.

## Subscription activation gate

The implemented plans use Solo A$49/month for 30 workload credits, Studio A$199/month for 150, and Agency A$599/month for 500. A run consumes `1 + rounds`; this is a disclosed workload quota, not a precise provider-cost meter. The broader multi-seat/client-management features in [BUSINESS.md](BUSINESS.md) remain product proposals; this release gives an individual account one workspace, without team invitations or role administration.

Checkout requires complete Stripe configuration plus `BRANCHLINE_BILLING_ENABLED=true` and an enabled engine. The launch flag is off by default. It is a manual attestation that setup and tests are complete, not an automatic live-engine certification. Existing configured webhooks and the customer portal remain usable when new checkout is paused.

Before setting live keys and enabling checkout, verify test signup/mail/reset, checkout, invoice-paid allocation, duplicate delivery, renewal, failed payment, end-of-period cancellation, immediate cancellation, credit expiry, and account deletion after billing ends. Keep portal plan-switching/prorations disabled until a supported migration policy is implemented; update/proration invoices do not refill the allowance.

Finish business identity, supported territories, tax presentation/collection, terms, cancellation/refund policy, support contact, and truthful processor/retention information. The module does not automatically collect tax, refund failed simulations, or measure every provider dollar. Credits are reserved on acceptance; failed/interrupted attempts can already have incurred upstream cost and require operator review/adjustment. Never sell unlimited simulation compute.

## Operating model and limits

The app uses one instance and one process. SQLite persists queued jobs; a restart can resume unclaimed work, while already claimed work becomes interrupted and is not replayed automatically. This avoids a blind second paid engine call but requires operator review of partial upstream work. The queue is not a multi-host high-availability system.

Entity limits apply after graph building, so a rejected graph can have consumed resources. Timeouts and stop requests cannot guarantee cancellation of every upstream preparation/report operation. Set provider budgets, alerts, bounded initial workloads, and an operator procedure for incomplete runs. Benchmark actual costs, memory, duration, and failure rates before widening the initial limits or promising completion times.

Run deletion attempts gateway, report, project/graph, and simulation-directory cleanup. If the engine is busy or a remote deletion fails, minimal encrypted resource references remain in the cleanup ledger. The hardened simulation cleanup route requires the shared secret and refuses active producers and unsafe identifiers. Neither its acknowledgement nor account deletion erases remote provider backups or downloaded report copies.

## Final release checks

Check desktop/mobile layout, keyboard navigation, focus handling, sample labels, safe handling of generated Markdown, redaction limits, report export, account states, and useful disconnected/error messages. In the static demo, do not imply that signup, checkout, or submitted-brief analysis is running.

For the application, verify unauthenticated access denial; one workspace cannot access another's runs; user-supplied IDs cannot change the billing customer or price; replayed invoices cannot refill spent credits; expired/deleted accounts cannot resume computation; malformed inputs avoid confidential echoes; secrets remain out of static assets and Git history; and account deletion is serialized against new checkout.

Use known non-sensitive resource IDs to verify remote cleanup, deletion retry, expiry, account export, and backup/recovery procedures. Confirm actual provider regions and retention before publishing claims. Keep the AGPL source link working for the exact served version and preserve upstream notices.

## First commercial milestone

Start with five design partners and one recurring agency workflow. Measure useful decision briefs, real-world validation, repeat usage, successful-job rate, duration, actual job cost, support time, and retention. Sell clearer decisions and dependable managed infrastructure. Synthetic participants and simulated percentages are not actual survey respondents, population estimates, or guaranteed forecasts.
