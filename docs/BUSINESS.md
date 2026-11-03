# Business proposal: a private decision rehearsal service

Prepared 3 November 2026. Product positioning, prices, quotas, and milestones below are proposals to validate, not existing revenue or capabilities. A public interface and demonstration do not establish that paid accounts, live engine hosting, payments, or every proposed privacy control are operational.

## The offer

Help small brand and communications teams explore how different synthetic audiences might respond before they commit to a launch, price change, or public announcement. The product turns a brief into a small set of comparable scenarios, identifies the assumptions that change the result, and recommends questions to test with real customers.

Lead with **“Rehearse the decision before you launch.”** Use a separate product identity with “Powered by MiroFish” attribution. The working name and domain need availability and trademark checks before investment.

The initial customer is a boutique marketing or PR agency serving several clients. Its recurring job is to assess a proposal, show alternatives, and explain the recommendation. Agencies can reuse templates across clients, giving a clearer retention mechanism than a broad consumer “predict anything” subscription. A first vertical could be Australian hospitality and consumer brands, where the founder has useful context and can recruit relevant design partners.

Three starter workflows:

1. **Launch rehearsal:** compare two messages with the same audience assumptions.
2. **Price change rehearsal:** surface affordability, fairness, loyalty, and communication objections.
3. **Response rehearsal:** compare a draft response with alternative tone and timing.

Each workflow should finish with a short decision brief: scenario comparison, objections, representative synthetic reactions, source links, assumptions, limitations, and a real-world validation plan. Label every generated reaction as synthetic. Avoid presenting simulated percentages as population estimates, calibrated probabilities, or evidence of actual customer sentiment.

MiroFish supplies document-seeded graph construction, persona and environment preparation, social simulation, reporting, and interaction with simulated agents. Its source setup requires an OpenAI-compatible model provider and Zep credentials; it warns that simulations can consume substantial resources. These are a useful engine foundation, rather than a complete subscription service. [Upstream README](https://github.com/666ghj/MiroFish#readme)

## Subscription proposal

Prices are proposed Australian dollars per month, excluding GST where applicable. Decide tax presentation and billing terms before checkout goes live. Live computation is metered; do not sell unlimited simulations.

| Plan | Proposed price | Included monthly credits | Commercial purpose |
| --- | ---: | ---: | --- |
| Explorer | Free | Public examples only | Learn the workflow without open-ended compute costs |
| Solo | A$49 | 30 | One person testing focused decisions |
| Studio | A$199 | 150 | Three seats, shared projects, scenario comparison |
| Agency | A$599 | 500 | Ten seats, separate client workspaces, report branding |
| Private | Quote | Contracted budget | Dedicated hosting, agreed providers and retention, support |

The paid seats and features in this table are a product plan, not claims about this build. Baseline security, deletion requests, and transparent processor disclosures should be available to every paid customer; charge more for the cost of dedicated infrastructure and advanced administration.

Proposed top-up: A$25 for 20 credits, explicit opt-in only. Monthly credits expire after the billing period; purchased credits expire after 12 months, subject to final terms and applicable requirements. No automatic overage billing by default. Keep account access, exports, and deletion available after compute credits run out. Cancellation stops renewal and keeps access through the paid period.

Define a credit in the billing service, separately from Zep's credit unit: initially, **one platform credit purchases a workload with up to A$0.20 of budgeted variable infrastructure and provider cost**. Quote an integer reservation before starting; stop safely at the approved budget and reconcile actual usage afterward. Reserve conservatively, return unused reserved credits, and make platform failures refundable. Separate a user cancellation from a platform failure in the published policy. Finalise credit conversion only after benchmark runs.

Do not equate one credit with one simulation. Agent count, rounds, source length, model choice, context growth, tool calls, retries, graph ingestion, and report generation all change costs. Require caps on these inputs, per-workspace concurrency, maximum wall time, and a backend kill switch. A UI slider alone cannot enforce a spending limit.

## Unit economics and pricing validation

Use this cost ledger per job:

`variable cost = model input + model output + graph ingestion + worker time + storage/egress + retry allowance`

Measure provider tokens and bytes rather than estimating cost solely from agent count. Keep exchange rates configurable and record the rate used for the quote. Use pinned model IDs and provider/region-specific rates.

As checked on 3 November 2026, Zep's published monthly Flex price is US$125 for 50,000 credits, with US$25 per additional 10,000; its credits depend on ingestion byte size. Treat this as a shared fixed-cost commitment plus variable ingestion, not free production infrastructure. [Zep pricing](https://www.getzep.com/pricing/)

Alibaba's official schedule varies model prices by region, mode, and context size. Do not base a subscription on a single headline token price or assume the upstream `qwen-plus` alias always selects the same revision. [Model Studio pricing](https://help.aliyun.com/en/model-studio/model-pricing)

With the illustrative A$0.20 maximum variable cost per credit, full included-credit use implies A$6 cost on Solo, A$30 on Studio, and A$100 on Agency. These are budget assumptions, not measured margins: add hosting minimums, payment fees, support, tax, FX, failed jobs, and acquisition costs before assessing profitability. At 20 Studio accounts, monthly revenue would be A$3,980 before tax; this is a planning example, not a forecast. Aim for at least 70% gross margin after actual service costs, and reduce included compute or increase prices if the benchmark does not support it.

## Privacy as a visible product feature

Build a **privacy receipt** for each run. Before submission, show exactly what content leaves the browser, which providers process it, which regions are configured, and how long each copy is kept. Afterward, let customers export the receipt alongside the result. This is more useful than a generic “your data is safe” badge.

| Feature | Achievable implementation | Honest boundary |
| --- | --- | --- |
| Local redaction preview | Detect common email/phone patterns in the browser; let the user inspect and replace names and identifiers before submission | Pattern matching misses some personal or confidential data; inspection is still required |
| Private sources, separate reports | Keep uploads and agent logs private; create a separately reviewed, redacted report artifact for sharing | Summaries can still reveal secrets; never assume summarisation anonymises data |
| Retention per run | Set a deadline for uploads, graph IDs, worker files, logs, and reports; enqueue deletion and record each processor's response | A local deletion button does not prove remote erasure or remove backups |
| Private client spaces | Enforce workspace ownership in every server query and object lookup; short-lived report links, revocation, and audit events | A hidden URL or frontend-only filter is not tenant isolation |
| Customer-selected providers | Approved provider list, server-side key storage, explicit region and processing disclosures | Bringing an API key does not by itself change a provider's training or retention terms |
| Dedicated private deployment | Separate worker, storage, graph service, and model endpoints for one customer; controlled network egress | Requires an independently verified complete processing path and an enterprise service agreement |
| Exportable project bundle | Export source references, assumptions, outputs, settings, and model versions before deletion | Re-running a stochastic model may produce a different result |

Use a clear status for every setting: **active**, **requires setup**, or **planned**. Never render an active-looking switch for a promise the backend cannot enforce. Make ephemeral browser-only drafting distinct from submitting a live job.

The default cloud engine should not promise end-to-end encrypted computation, immediate total erasure, local-only processing, Australian-only processing, or zero retention. A processing service needs access to plaintext unless a different computation architecture is implemented. Zep's current retention documentation also describes retained internal copies, including backups up to 365 days and graph write logs up to 90 days. Its latest documentation may differ from the SDK version used upstream, so verify the deployed version and contractual policy before setting exact deletion claims. [Zep context retention](https://help.getzep.com/context-retention)

For launch, publish an accurate processor list and data-flow diagram. Do not claim model-training exclusion, GDPR compliance, SOC 2 certification, or guaranteed residency based only on a supplier's marketing page. Establish the actual provider configuration and contracts first. Keep error telemetry free of documents, prompts, credentials, and raw agent conversations.

## Licence and commercial structure

The checked upstream licence is **GNU AGPL version 3**. Charging for a hosted service is compatible with the licence's commercial model, but a modified network-accessible covered program has source-availability obligations. Preserve notices, include the licence, identify modifications, and provide a prominent, functioning Corresponding Source link for the version being served. Obtain appropriate review of the combined application's obligations; putting an API between components is not an automatic exemption. Customer documents and business outputs are not automatically open sourced merely because the application uses AGPL; keep customer records out of the source repository. [Upstream licence](https://github.com/666ghj/MiroFish/blob/main/LICENSE)

Build the business around dependable hosting, templates, evidence handling, workflow quality, support, and private deployment. Avoid making exclusive ownership of the underlying engine the moat. Review dependency licences and brand use as part of release preparation.

## Launch sequence

**Weeks 1–2:** recruit five design partners through existing relationships. Run focused, explicitly synthetic rehearsals using material they are allowed to process. Record the decision made, usefulness of objections, time to usable report, and whether a real customer test confirms or challenges the simulation.

**Weeks 3–4:** benchmark at least 30 bounded jobs across the three workflows. Implement server-side authentication and workspace permissions, durable job queue, usage ledger, safe retries, cost cap, deletion workflow, and complete receipts. Test cross-account access and cancellation. Configure payment checkout and signed, idempotent webhooks in test mode before taking payment.

**Weeks 5–6:** offer ten paid Studio pilots at the proposed price. Require a real decision and two scenarios per pilot. Publish permissioned case studies around saved time and discovered objections, with the limitations visible. Add annual billing only when retention is demonstrated.

**Weeks 7–12:** prioritise scenario comparison, client workspace management, and repeatable reports. Introduce the private deployment offer only after demonstrating the whole data path and calculating its support cost. Defer a general consumer marketplace until one recurring professional workflow retains customers.

## Success measures and release gates

Track first usable report within 15 minutes for the bounded starter configuration; successful job rate above 95%; per-job cost and p95 duration; time to first decision brief; repeat use within 30 days; paid workspace retention; support minutes per account; and realised gross margin. These are initial targets to validate, not promised service levels.

For research quality, track assumptions changed, alternative scenarios compared, and disagreement with real-world follow-up. Do not use an unvalidated “prediction accuracy” number as the primary marketing metric.

A public demonstration can launch before the paid service. Charging customers requires verified account isolation, provider credentials and budget controls, live worker hosting, payments, truthful privacy notices, operational deletion, and a clear refund/cancellation policy. Keep live submission disabled or clearly unavailable until these controls are connected and tested.
