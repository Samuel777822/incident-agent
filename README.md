# Agent Daemon

An AI on-call engineer for Python apps. Customers connect a GitHub repository, monitoring is added to it
automatically, errors are grouped into incidents, an LLM diagnoses them, and a fix is proposed as a pull request.

## What the portal does

| Page | Who | Purpose |
| --- | --- | --- |
| `/dashboard` | customer | Projects, whether each one is live, incidents and what the agent did, plan and days left |
| `/billing` | customer | Plan and expiry, one-time free-trial request, pay for a plan |
| `/projects/new` | customer | Connect a repository. Monitoring is installed automatically |
| `/admin` | the two admins | Customers, trial requests, UPI payments to confirm, apps and their health, incidents, email status |

Only the emails in `ADMIN_EMAILS` are administrators. They are sent to `/admin` and never see customer pages.
Admin accounts cannot be registered on the public sign-up form.

## Access rules

* **Free trial:** one per customer, ever. The customer requests it, an admin approves it, and one day of access
  starts at that moment.
* **Paid plans:** ₹100 for 30 days, ₹1,000 for 365 days. Renewals extend the current expiry.
* A paid plan is never downgraded to "trial" by a later grant. Revoking pauses the customer's projects and granting
  access again resumes them. A project the customer paused themselves stays paused.

## Payments

**Instant, optional (needs a Razorpay account, not in use).** Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` and the pay buttons open Razorpay Checkout
(UPI apps such as Paytm, PhonePe and Google Pay, plus cards). The amount is created on the server, so a customer can only
pay the plan price. Access starts when Razorpay reports the payment as captured, through `/billing/verify` or through
the signed webhook `/webhooks/razorpay` (set `RAZORPAY_WEBHOOK_SECRET`). Nobody has to approve anything.

**Paytm QR with admin confirmation (the mode in use).** A personal UPI QR cannot tell this site that money arrived, so:
1. The customer pays the QR (the site shows a QR with the exact amount, plus a plain one as a fallback) and enters the UPI reference (UTR).
2. The customer is told to wait 1 to 2 hours and gets an email saying so. Both admins get an email: *customer X says they paid ₹100*.
3. An admin opens Paytm, finds that reference and amount, then presses **I received ₹100 · grant 30 days** on `/admin` (or **Not received**).
4. The customer's access starts, and they get an email. Nothing unlocks without that click.
References must look like a UTR and must be unique across all customers. `UPI_ID` and `UPI_PAYEE_NAME` set the recipient.
On `/admin`, customers needing action are listed first, and each row shows Trial, Paid or No access with the expiry.

## Email

Render's free tier blocks SMTP, so the default provider is an HTTPS API:

| Variable | Purpose |
| --- | --- |
| `BREVO_API_KEY` | Brevo API key (or `RESEND_API_KEY` for Resend) |
| `EMAIL_FROM` | A sender address verified with the provider |
| `ADMIN_EMAILS` | Comma-separated admin emails; each gets every admin alert |
| `PORTAL_BASE_URL` | Public URL used in email links |

Every attempt is stored and shown in **Admin → Email status**, including the provider's error. "Accepted" means the
provider took the message. It does not guarantee inbox delivery. The **Send test email** button checks the setup.
SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`) still works on hosts that allow it.

## Automatic monitoring install

When a project is connected, the portal opens a pull request that adds `incident_agent_monitor.py`, one import line in
the app's entry file (`app.py`, `main.py`, `wsgi.py`, ...), and, for **private** repositories, the project's ingest URL
and key in `incident_agent_config.json`. It then tries to merge the PR. The client reports unhandled exceptions, logged
errors and a heartbeat every 5 minutes, never raises into the app, and uses short timeouts. For **public** repositories the key is
not committed; the customer sets `INCIDENT_AGENT_INGEST_URL` and `INCIDENT_AGENT_INGEST_KEY` instead.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | yes | `production` on Render |
| `DATABASE_URL` | production | PostgreSQL URL (SQLite is used locally) |
| `SESSION_SECRET` | yes | 32+ random characters |
| `TOKEN_ENCRYPTION_KEY` | yes | Fernet key; encrypts GitHub tokens and ingest keys |
| `GROQ_API_KEY` | yes | Diagnosis |
| `ADMIN_EMAILS` | yes | The two admin emails |
| `ADMIN_PASSWORD_<EMAIL>` | one way to sign in | Password for an admin, `<EMAIL>` is the email upper-cased with non-letters/digits as `_` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | optional | Google sign-in |
| `BREVO_API_KEY`, `EMAIL_FROM` | for email | see above |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | optional, gateway payments | see above |
| `PORTAL_RUN_WORKER` | optional | `1` (default) runs the diagnosis worker inside the web service, as the free tier needs |

Generate a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Never commit secrets or runtime logs.

## Tests

```
pip install -r requirements.txt
python -m pytest -q
```

The suite covers sign-up, navigation, the trial rules, atomic approvals, manual and gateway payments, the webhook,
email providers (mocked), the admin page, the zero-touch installer, and an end-to-end run of the monitoring client
against a live local portal. PostgreSQL-specific paths are not covered by automated tests.

## Known limits

* Render's free PostgreSQL database expires after about 30 days. Move `DATABASE_URL` to a durable database before then.
* Free web services sleep when idle. The built-in worker only runs while the service is awake (UptimeRobot pings `/health`).
* Auto-fix only supports Python repositories. Auto-merge happens only when GitHub checks pass.
