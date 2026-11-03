# Business proposal: a private decision rehearsal service

Prepared 3 November 2026. Product positioning, prices, quotas, and milestones below are proposals to validate, not existing revenue or capabilities. A public interface and demonstration do not establish that paid accounts, live engine hosting, payments, or every proposed privacy control are operational.

## The offer

Help small brand and communications teams explore how different synthetic audiences might respond before they commit to a launch, price change, or public announcement. The product turns a brief into a small set of comparable scenarios, identifies the assumptions that change the result, and recommends questions to test with real customers.

Lead with **“Rehearse the decision before you launch.”** Use a separate product identity with “Powered by MiroFish” attribution. The working name and domain need availability and trademark checks before investment.

The entry user is a solo founder, marketer, creator or small-business owner with a concrete decision to explore. The free personal account lets them try a short rehearsal and return with a better brief. The initial paying customer is a frequent individual user or a boutique marketing/PR practitioner who needs more depth and repeat runs. Agencies are a useful design-partner group, but shared teams and client administration remain future features. A first vertical could be Australian hospitality and consumer brands, where the founder has useful context and can recruit relevant partners.

Three starter workflows:

1. **Launch rehearsal:** compare two messages with the same audience assumptions.
2. **Price change rehearsal:** surface affordability, fairness, loyalty, and communication objections.
3. **Response rehearsal:** compare a draft response with alternative tone and timing.

Each workflow should finish with a short decision brief: scenario comparison, objections, representative synthetic reactions, source links, assumptions, limitations, and a real-world validation plan. Label every generated reaction as synthetic. Avoid presenting simulated percentages as population estimates, calibrated probabilities, or evidence of actual customer sentiment.

MiroFish supplies document-seeded graph construction, persona and environment preparation, social simulation, reporting, and interaction with simulated agents. Its source setup requires an OpenAI-compatible model provider and Zep credentials; it warns that simulations can consume substantial resources. These are a useful engine foundation, rather than a complete subscription service. [Upstream README](https://github.com/666ghj/MiroFish#readme)

## Affordable free plan, subscriptions and top-ups

The launch pricing below is approved for the redesigned source release. It is not evidence that checkout is live: the deployed service remains an owner-only pilot until a sending domain, Stripe configuration and the release checks are complete. All figures are Australian dollars. Final checkout must show applicable tax and the complete charge before purchase.

| Plan | Monthly price | Compute allowance | Useful starting point |
| --- | ---: | ---: | --- |
| Personal | Free | 4 free credits every 48 hours, capped at 4 | Two quick one-round runs, or one three-round run, per refill window |
| Plus | A$9 | 90 | 15 five-round runs from the monthly allocation |
| Studio | A$19 | 240 | 40 five-round runs from the monthly allocation |
| Pro | A$49 | 700 | 116 five-round runs, with 4 credits left, from the monthly allocation |
| Private deployment | Quote | Contracted allocation | Separate infrastructure and an agreed processing/support configuration; a future offer |

Every verified account, including paid accounts, receives the same 4-credit free refill. Monthly allocations are additional. These are individual accounts and workspaces; plan names do not imply team seats, client administration, report branding, dedicated resources or faster queues that have not been implemented. Baseline privacy, exports and account controls are available on the free plan too.

One accepted run reserves **`1 + rounds`** workload credits. A one-round quick check costs 2; a three-round exploration costs 4; a five-round standard run costs 6. The server quotes the exact reservation before submission. A platform credit is a workload allowance, not a Zep credit, currency balance, token budget, estimate of real people represented, or guaranteed provider-invoice cap. Agent count, source length, tool calls, retries and report generation still change underlying costs. Do not sell unlimited computation.

### Wallet rules that users can understand

- The free wallet fills to **4 credits every rolling 48 hours** after verification. The next server-calculated refill time is visible. Missed windows do not accumulate; the free wallet can never exceed 4 through refills. No card, purchase or daily check-in is needed to receive a due refill.
- Monthly subscription credits are granted once for a verified paid billing period. They do not roll over beyond that period. Renewal replaces that period's subscription allowance; it does not erase banked or free credits.
- Purchased top-ups and operator grants are banked separately. They do not expire in this release. Existing banked balances remain banked; a free refill does not reduce or replace them.
- Runs spend the free wallet first, then the current subscription allowance, then banked credits. The total balance and its breakdown should be visible together.
- Refills are tied to verified accounts, not anonymous browser visits or token-only operator workspaces without a verified account. Rate, entity, round, active-run and time limits remain enforced. Deleting and recreating an account with the same verified email does not restart its current free window; a short-lived keyed marker enforces that cooldown, as disclosed in [PRIVACY.md](PRIVACY.md).
- Checkout is opt-in. There is no automatic credit purchase or customer overage charge. Keep account access, existing reports, export and deletion available when the compute balance is empty.

### Small one-time purchases

| Pack | One-time price | Banked credits | Five-round runs it can fund |
| --- | ---: | ---: | ---: |
| Spark | A$4 | 24 | 4 |
| Boost | A$9 | 60 | 10 |
| Reserve | A$19 | 150 | 25 |

The pack discount improves with size, while subscriptions provide more credits per dollar than a similarly priced one-time purchase. A top-up suits an occasional project; a monthly plan suits regular work. Present both choices without preselecting an add-on, hiding the free refill, or implying a purchase is necessary to retrieve an existing report. Grant a pack only after server-side verification of the paid Checkout resource, with duplicate delivery protected by a persistent ledger.

Cancellation, failed payments, refunds and platform-failure adjustments need clear published terms. The source does not automatically measure every provider dollar or refund every failed job. A failed or interrupted run can already have consumed provider resources; any restoration policy must match the implemented operator process.

## Repeat use through useful work

The repeat-use loop is **ask → rehearse → review → change one assumption → test with people → return with new evidence**. A two-day free refill creates an affordable opportunity to return; the product's value must supply the reason.

1. **A first useful scenario:** offer focused templates, an example beside each field, and a local brief check for a clear question, named fictional audience, relevant context and a decision the user can act on. Describe this check as completeness guidance, not an AI assessment of research quality.
2. **A visible next step:** finish a report with assumptions to challenge and suggested real-world questions. Make “Duplicate and change one assumption” easy. Re-review redaction, processors, cost and consent for every new live submission.
3. **An honest credit home:** show free, monthly and banked balances, next free refill, exact run quote and an optional shorter-depth choice. A free user should be able to choose a useful run that fits the current allowance.
4. **Progress worth watching:** use a responsive animated network, a stage timeline and real round/action counts. Clearly separate illustrative particles from measured agents. The current deployment does not execute millions of agents: it supports a bounded small simulation and one active engine run. Unknown telemetry stays unknown; partial milestones are not invented findings.
5. **Control over drafts:** keep work in the tab by default. An unchecked “Save this draft on this device” option can support a return visit, with a clear expiry and removal control. Do not save credentials, consent or private work silently.
6. **Experiments after launch:** evaluate opt-in refill reminders, scenario comparison and scheduled research prompts only when those features are implemented and the user chooses them. Do not send reminders merely because a free allowance refreshed.

Avoid fake live counters, invented participant quotes, false scarcity, forced streaks, hidden credit expiry, or countdowns that reset to pressure a purchase. Reward clarity and repeatable decisions. Do not use time spent waiting for computation as the main engagement metric.

## Unit economics and capacity validation

These low prices are a launch hypothesis, not a proven margin. Keep a per-job cost ledger:

`variable cost = model input + model output + graph ingestion + worker time + storage/egress + retry allowance`

Measure tokens, ingestion bytes, duration and provider charges for small and large supported runs. Record model/version, provider region and currency conversion used. A round count is easy to explain but is not a precise cost meter; input limits and operational controls still matter.

The configured Render baseline is approximately **US$112.75/month** before tax and overages for the existing app, private engine and disks. This is an operator-approved deployment estimate, not a new purchase or an automatic scaling budget. [Render pricing](https://render.com/pricing)

As checked on 3 November 2026, Zep publishes a prototype allowance of 10,000 provider credits per month. Its monthly Flex plan is **US$125 for 50,000 credits**, then **US$25 per 10,000**, with automatic top-ups at the 20% threshold. A Zep Episode costs one credit for each 350 bytes or part thereof; Branchline's workload credits are a different unit. If the operator chooses Flex, the illustrative shared Render-plus-Zep fixed floor becomes **US$237.75/month**, before model calls, email, tax, FX, fees, support and free-user acquisition costs. This is not a statement about the operator's current Zep invoice or an instruction to upgrade. [Zep pricing](https://www.getzep.com/pricing/)

Official OpenAI documentation lists the current compatibility model, `gpt-4o-mini`, at **US$0.15 per million input tokens** and **US$0.60 per million output tokens**. Use the account's actual model, usage and pricing when measuring jobs; do not infer a typical scenario price from these token rates alone. Verify model availability before commercial launch rather than silently migrating the pinned simulation framework. [Official GPT-4o mini documentation](https://developers.openai.com/api/docs/models/gpt-4o-mini)

For a 70% gross-margin target, the following arithmetic shows the maximum cost space before allocating hosting, payment fees, support and the free tier. It is a planning ceiling, not a measured variable cost or a hard enforcement mechanism.

| Plan | Revenue per included credit | 30% of revenue per included credit, before overhead |
| --- | ---: | ---: |
| Plus | A$0.1000 | A$0.0300 |
| Studio | A$0.0792 | A$0.0238 |
| Pro | A$0.0700 | A$0.0210 |

Do not subtract USD costs directly from AUD sales. Use the actual settlement exchange rate and payment fees. Publish final prices only when measured p95 workload costs, failure rates, support time and the free-user subsidy fit the chosen margin. Paid plan and pack amounts can be revised before public checkout; a source-code price change must not silently change an existing customer's Stripe contract.

Free use also consumes capacity. A fully used 4-credit refill every 48 hours supplies about 60 credits per 30 days, or up to 30 one-round jobs. In a purely illustrative four-minute-per-job model, one continuously available worker could finish at most 10,800 jobs in 30 days before overhead; 1,000 fully engaged free accounts could ask for 30,000 quick jobs. This is not a measured runtime or service level. Start with a bounded verified cohort, measure demand, then choose a funded capacity plan. The present global admission limit can reject an additional run while one is active; it is not a promise of an unlimited waiting queue.

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

**Weeks 5–6:** after the release gates are met, offer affordable Plus/Studio pilots at the launch prices. Require a real decision and two scenarios per pilot. Publish permissioned case studies around saved time and discovered objections, with the limitations visible. Add annual billing only when retention is demonstrated.

**Weeks 7–12:** prioritise scenario comparison, client workspace management, and repeatable reports. Introduce the private deployment offer only after demonstrating the whole data path and calculating its support cost. Defer a general consumer marketplace until one recurring professional workflow retains customers.

## Success measures and release gates

Track first usable report within 15 minutes for the bounded starter configuration; successful job rate above 95%; per-job cost and p95 duration; time to first decision brief; repeat use within 30 days; paid workspace retention; support minutes per account; and realised gross margin. These are initial targets to validate, not promised service levels.

For research quality, track assumptions changed, alternative scenarios compared, and disagreement with real-world follow-up. Do not use an unvalidated “prediction accuracy” number as the primary marketing metric.

A public demonstration can launch before the paid service. Charging customers requires verified account isolation, provider credentials and budget controls, live worker hosting, payments, truthful privacy notices, operational deletion, and a clear refund/cancellation policy. Keep live submission disabled or clearly unavailable until these controls are connected and tested.
