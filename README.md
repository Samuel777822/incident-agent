# Agent Daemon

Agent Daemon is a multi-tenant on-call service. This repository contains the account portal, project storage,
monitoring installer, payment flow, and an older single-repository daemon. The hosted portal's incident ingest is
not yet connected to an isolated multi-tenant diagnosis and repair worker, so hosted diagnosis and repair are not
operational yet.

## Web application

The server-rendered site is in `web_app.py`. It provides account sign-in, owner-scoped projects and incidents,
per-project event ingestion, project controls, and Razorpay test-mode checkout. Local development uses SQLite;
production requires PostgreSQL via `DATABASE_URL` and HTTPS in front of the app.

Set these values before production startup:

| Variable | Purpose |
| --- | --- |
| `SESSION_SECRET` | At least 32 random characters for signed sessions |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting customer GitHub tokens |
| `DATABASE_URL` | PostgreSQL connection URL |
| `RAZORPAY_MODE` | Must be `test`; live payments are disabled |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay test credentials |
| `RAZORPAY_WEBHOOK_SECRET` | Secret for the captured-payment webhook |
| `RAZORPAY_AMOUNT_PAISE` | Product owner's test subscription amount |

Run locally with `python web_app.py`. The project creation page requires explicit monitoring-install consent and a
GitHub token. The **Open monitoring PR** action creates a branch and pull request containing an opt-in Python helper
and setup notes. The PR contains no credentials. After reviewing and merging it, configure `INCIDENT_AGENT_INGEST_URL`
and `INCIDENT_AGENT_INGEST_KEY` in the customer's deployment environment. The ingest key is shown once; only its
hash is stored by the portal.

The `/ingest` endpoint accepts JSON with an `X-Ingest-Key` header. `/heartbeat` uses the same project key. Events are
deduplicated per project, and dashboard queries scope projects and incidents to their owner. Razorpay checkout
activates a subscription only after verifying the checkout signature and confirming the payment is captured.

## Existing single-repository daemon

The older `agent_daemon.py` pipeline reads a local log file, groups errors, gathers repository evidence, diagnoses
an incident, and can open a fix pull request. It is not the portal worker and uses its own `repos.json` settings.
Run it only against a repository that you explicitly configure:

```bash
python agent_daemon.py customer-app 60
```

Customer code and customer tests must never run on the agent host. Fixes are limited to a small Python change and
are saved as diffs. The daemon opens a PR; auto mode waits for the customer's GitHub checks and merges only when
they pass. With no checks, failed checks, or unavailable CI, the PR stays open for human review. No code is pushed
directly to the default branch.

The old daemon reads logs from a file on its machine, waits for at least five occurrences and thirty seconds, and
has no multi-tenant scheduling. It is not currently connected to the portal's PostgreSQL project data.

## Development

Install dependencies with `pip install -r requirements.txt`. Portal local development can use SQLite. For production,
set `APP_ENV=production` and provide PostgreSQL through `DATABASE_URL`; the app refuses to start in production
without it. Never commit `.env`, customer tokens, database files, or runtime logs.

Useful modules:

| File | Purpose |
| --- | --- |
| `web_app.py`, `portal_db.py` | Portal routes, sessions, tenant-scoped data and billing |
| `monitoring_installer.py` | Opens the customer's opt-in monitoring pull request |
| `diagnose.py`, `run_diagnosis.py` | Legacy single-repository diagnosis flow |
| `patcher.py`, `autofix.py`, `pr.py` | Constrained patch and CI-gated pull request workflow |
| `agent_daemon.py`, `workflows.py` | Legacy local daemon and one-shot pipeline |
