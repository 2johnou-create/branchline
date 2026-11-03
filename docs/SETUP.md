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

Resend is the initial email-provider choice. The SMTP integration is implemented; account configuration and delivery tests are still required before launch.

1. Create or sign in to your own [Resend account](https://resend.com/signup) and start on its Free transactional plan. As checked on 3 November 2026, it includes 3,000 emails per month with a 100-email daily limit. Check [current pricing and limits](https://resend.com/pricing) before launch; domain registration is separate.
2. Choose a domain you own and can edit in DNS. If you do not own one yet, register one through a registrar before public signup. The app can still use its Render web address, but you cannot verify sending ownership of `onrender.com` or `chatgpt.site`.
3. In Resend **Domains**, add a dedicated sending subdomain such as `auth.your-domain.example`. Copy the exact DNS records Resend generates into your DNS provider, then wait until Resend shows the domain as verified. Follow its [domain verification guide](https://resend.com/docs/dashboard/domains/introduction); do not replace existing website or mailbox records with guessed values.
4. In that domain's configuration, leave open and click tracking disabled for account verification and recovery links. Select [Enforced TLS](https://resend.com/docs/dashboard/domains/tls) for these authentication emails. With enforced delivery TLS, a recipient server that cannot accept TLS will not receive the message.
5. Create a dedicated Resend API key named **Branchline authentication**, with sending access restricted to the verified sending domain where available. Save it privately when shown. Enter it directly into Render's secret/environment field below; do not send it in chat or commit it to the repository.
6. In the **public `branchline-app` service's** Render Environment settings, configure these [Resend SMTP settings](https://resend.com/docs/send-with-smtp):

| Variable | Resend value |
| --- | --- |
| `BRANCHLINE_SMTP_HOST` | `smtp.resend.com` |
| `BRANCHLINE_SMTP_PORT` | `587` |
| `BRANCHLINE_SMTP_USERNAME` | `resend` |
| `BRANCHLINE_SMTP_PASSWORD` | Your private Resend API key |
| `BRANCHLINE_SMTP_FROM` | `Branchline <accounts@auth.your-domain.example>` — replace with your verified sending domain |
| `BRANCHLINE_SMTP_STARTTLS` | `true` |

The Blueprint already supplies port `587` and STARTTLS; its four email prompts are host, username, password, and sender. Another transactional SMTP provider can use the same variables with its own credentials.

For an owner-only test before your domain is ready, Resend's `onboarding@resend.dev` sender can send only to the email associated with your Resend account. This does not support public signup. Replace it with the verified-domain sender before inviting anyone else. See [Resend's testing restriction](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain).

For this owner-only pilot, set `BRANCHLINE_SIGNUP_ALLOWED_EMAILS` on the public app to the email associated with your Resend account. The server rejects other registrations before storing an account or sending mail, and the interface labels registration as a private pilot. After verifying your own sender domain, remove the allowlist only when public registration is intended. Keep the allowlist in hosting settings rather than public source.

Keep `BRANCHLINE_REQUIRE_EMAIL_VERIFICATION=true` in production. Signup stays unavailable when required email delivery is unconfigured. After saving settings and deploying the app, register a test account, receive and follow its verification link, then test password recovery. Once your sending domain is verified, repeat with a second address to confirm public delivery. Confirm that email links use the deployed application's exact HTTPS origin. A configured SMTP hostname or a successful container health check is not proof of delivery.

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

Next register a fresh account, receive its verification email, sign in, verify isolation with a second account, and test export, recovery and deletion. Verified accounts receive 4 free credits with a rolling 48-hour refill and a 4-credit cap. Check the countdown, rollover boundary and preservation of banked credits before public onboarding. Unverified accounts and standalone operator workspaces receive no free allowance.

## 6. Configure Stripe in test mode first

1. Connect your Stripe account and use a sandbox/test environment first. Finish business identity, bank and live-account requirements yourself before accepting real payments.
2. Create three AUD monthly recurring Prices: Plus **A$9 / 90 credits**, Studio **A$19 / 240 credits**, Pro **A$49 / 700 credits**. Their stable internal IDs remain `solo`, `studio`, `agency`. Decide and configure tax treatment, business terms, refunds and the support contact. The server checks amounts, currency and recurrence before checkout; old expensive Price IDs are rejected.
3. In the public app service, set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_SOLO`, `STRIPE_PRICE_STUDIO`, and `STRIPE_PRICE_AGENCY`. Use the Price IDs, not Product IDs.
4. For optional top-ups, create AUD one-time Prices: Spark **A$4 / 24 credits**, Boost **A$9 / 60 credits**, Reserve **A$19 / 150 credits**. Set `STRIPE_PRICE_PACK_SPARK`, `STRIPE_PRICE_PACK_BOOST`, `STRIPE_PRICE_PACK_RESERVE`. Top-ups enter the banked wallet; monthly price IDs cannot be reused for packs.
5. Add a snapshot webhook destination at `https://YOUR-APP.onrender.com/api/v1/billing/webhook`, using API version `2025-06-30.basil`, subscribed to `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, and `invoice.payment_failed`. Set its signing secret as `STRIPE_WEBHOOK_SECRET`. Failed or unsettled delayed payments require operator reconciliation; they do not automatically release deletion holds.
6. Configure Stripe's hosted customer portal for payment updates, invoice history and cancellation. Leave immediate plan switching/proration disabled for this initial release.
7. After real inference and email verification succeed, set `BRANCHLINE_BILLING_ENABLED=true` using **test keys**, redeploy, and complete test checkouts. Confirm the signed paid-invoice event grants monthly credits exactly once, and a canonical paid pack session grants banked credits exactly once. Test renewal, delayed/failed payments, repeated events, account deletion guards and cancellation. A browser success redirect alone grants no credits. Refunds and disputes require operator reconciliation before live sales.
8. Switch to live-mode Prices, keys and webhook only after the operator has verified the whole lifecycle and is ready to sell the service. Do not mix sandbox and live IDs.

Pausing new checkout by setting `BRANCHLINE_BILLING_ENABLED=false` preserves existing billing management and webhook handling where configured. Credits are workload allowances (`1 + rounds`), not a hard financial cap on the providers. See [the operating guide](../server/README.md) for the precise renewal and deletion behavior.

## What must be done by the account owner

Account sign-in, account terms, API billing, merchant identity, bank details, sender-domain verification and approving paid hosting are actions for the owner. Connecting the relevant integrations lets the assistant continue supported deployment/configuration work without you copying secret values into chat. Until those accounts are configured, a public demo and passing local/remote tests are not evidence of a live paid inference service.
