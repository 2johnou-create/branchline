# First-time account setup

The application code is implemented. Real hosting, email delivery, model inference and payment processing require accounts owned by the service operator. The public static address remains an interface demonstration until the combined server is deployed. Do not send API keys in chat, put them in GitHub, or enter provider keys in Branchline's browser settings.

## 1. Create the model-provider key

For the initial compatibility configuration, use an OpenAI API account:

1. Sign in to [OpenAI Platform](https://platform.openai.com/) and create a project named **Branchline**.
2. Open [API keys](https://platform.openai.com/api-keys) in that project and create a key for this server. Save the value privately when shown.
3. Check that the project has API access and available credits/billing in its own dashboard. Review current usage and budget controls there; an application workload credit is not a provider spending limit.
4. In the **private engine service's** Render Environment settings, enter:

| Variable | Initial value |
| --- | --- |
| `LLM_API_KEY` | Your private project API key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` |
| `LLM_MODEL_NAME` | `gpt-4o-mini` |

This model is the upstream-compatible initial setting, not a claim that it is the newest model or that your account has already been validated. See the official [API quickstart](https://developers.openai.com/api/docs/quickstart) and [model documentation](https://developers.openai.com/api/docs/models/gpt-4o-mini). Do not change to an untested model merely because it is newer: the pinned simulation framework and request format must support it.

## 2. Create the Zep account

1. Open [Zep](https://app.getzep.com/) and sign up or sign in.
2. Create the API key for this project and save it privately. Zep's [account/key guide](https://help.getzep.com/v2/quickstart#obtain-an-api-key) describes this step; the vendored engine pins its own SDK version.
3. In the private engine service, set `ZEP_API_KEY` to that key.

The original engine requires Zep Cloud. Creating a local Docker volume does not make graph processing local or remove Zep's provider retention rules.

## 3. Configure verification email

Use a transactional email service with SMTP credentials and a sender you control. Verify its sending domain/sender in that provider's dashboard, then copy the provider's SMTP settings into the **public app service**:

| Variable | Meaning |
| --- | --- |
| `BRANCHLINE_SMTP_HOST` | Provider's SMTP hostname |
| `BRANCHLINE_SMTP_PORT` | Usually `587` for STARTTLS, or `465` for implicit TLS |
| `BRANCHLINE_SMTP_USERNAME` | Provider-issued SMTP username |
| `BRANCHLINE_SMTP_PASSWORD` | Provider-issued SMTP password/API credential |
| `BRANCHLINE_SMTP_FROM` | Your verified sender address, e.g. `accounts@your-domain.example` |
| `BRANCHLINE_SMTP_STARTTLS` | `true` for port 587; port 465 uses implicit TLS |

Keep `BRANCHLINE_REQUIRE_EMAIL_VERIFICATION=true` in production. Signup stays unavailable when required email delivery is unconfigured. A configured SMTP hostname is not proof that delivery works: register a test account, verify the received email, and test recovery. Your sender provider may require DNS changes; complete those in the provider's dashboard.

## 4. Deploy on Render

[Review the Branchline deployment on Render](https://render.com/deploy?repo=https://github.com/2johnou-create/branchline)

The Blueprint creates a public app and a private engine in Singapore, with persistent disks. These are **paid resources**. Render displays the current cost and account requirements before deployment; review and approve those yourself. Resource choices are initial sizing assumptions, not measured capacity guarantees. See [Render's Blueprint reference](https://render.com/docs/blueprint-spec) and [disk limitations](https://render.com/docs/disks).

The Blueprint generates the gateway encryption master secret and private cleanup secret; do not replace or regenerate the master secret on an existing database without a planned migration. The app receives the private engine address automatically. Render's generated public URL is used for same-origin accounts and cookies, so the fully working service is opened at that URL. The separate static Sites demo does not gain a Python backend automatically.

Enter the engine and SMTP secrets when prompted, deploy both services, then open the public app's Render URL. If adding a custom domain later, set `BRANCHLINE_PUBLIC_URL` and `BRANCHLINE_ALLOWED_ORIGINS` to that exact HTTPS origin and redeploy the app.

## 5. Verify real inference before charging customers

In the public app's Render **Shell**, run:

```sh
python scripts/provision-workspace.py --name 'Deployment verification' --credits 4
```

Keep the token private. On a machine with this repository and the gateway requirements installed, run:

```sh
python scripts/verify-live.py --api https://YOUR-APP.onrender.com
```

The script prompts for the workspace token without echoing it. It submits one non-confidential, one-round job and consumes two workload credits; model and graph providers may charge real usage. It requires a genuine report and writes a verification receipt under ignored `artifacts/`. The script does not fabricate model output, certify research accuracy, or automatically enable billing. Review the report, delete the test run and inspect cleanup acknowledgements.

Next register a fresh account, receive its verification email, sign in, verify isolation with a second account, and test export, recovery and deletion. Newly registered accounts receive zero inference credits until a payment is verified or an operator grants pilot allowance.

## 6. Configure Stripe in test mode first

1. Connect your Stripe account and use a sandbox/test environment first. Finish business identity, bank and live-account requirements yourself before accepting real payments.
2. Create three AUD monthly recurring Prices: Solo **A$49**, Studio **A$199**, Agency **A$599**. Decide and configure tax treatment, business terms, refunds and the support contact. The server checks these amounts, currency and recurrence before checkout.
3. In the public app service, set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_STUDIO`, and `STRIPE_PRICE_AGENCY`. Use the Price IDs, not Product IDs.
4. Add a snapshot webhook destination at `https://YOUR-APP.onrender.com/api/v1/billing/webhook`, using API version `2025-06-30.basil`, subscribed to `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, and `invoice.payment_failed`. Set its signing secret as `STRIPE_WEBHOOK_SECRET`.
5. Configure Stripe's hosted customer portal for payment updates, invoice history and cancellation. Leave immediate plan switching/proration disabled for this initial release.
6. After real inference and email verification succeed, set `BRANCHLINE_BILLING_ENABLED=true` using **test keys**, redeploy, and complete a test checkout. Confirm the signed paid-invoice event grants the correct credits exactly once, then test renewal, failed payment and cancellation. A browser success redirect alone grants no credits.
7. Switch to live-mode Prices, keys and webhook only after the operator has verified the whole lifecycle and is ready to sell the service. Do not mix sandbox and live IDs.

Pausing new checkout by setting `BRANCHLINE_BILLING_ENABLED=false` preserves existing billing management and webhook handling where configured. Credits are workload allowances (`1 + rounds`), not a hard financial cap on the providers. See [the operating guide](../server/README.md) for the precise renewal and deletion behavior.

## What must be done by the account owner

Account sign-in, account terms, API billing, merchant identity, bank details, sender-domain verification and approving paid hosting are actions for the owner. Connecting the relevant integrations lets the assistant continue supported deployment/configuration work without you copying secret values into chat. Until those accounts are configured, a public demo and passing local/remote tests are not evidence of a live paid inference service.
