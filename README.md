# Agent Daemon

Agent Daemon is a multi-tenant on-call service. This repository contains the account portal, project storage,
monitoring installer, payment flow, and a separate portal diagnosis worker. The hosted portal can turn repeated
events into project-scoped diagnosis reports. Repository repair, fix pull requests, auto-merge, health checks,
monitoring verification, and automatic rollback are not yet connected to this worker.

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
deduplicated per project, and dashboard queries scope projects and incidents to their owner. New project setup asks
for explicit consent before selected logs, tracebacks, and relevant Python source files are sent to Groq for diagnosis.
Razorpay checkout activates a subscription only after verifying the checkout signature and confirming the payment is captured.

## Hosted diagnosis worker

Run one worker process separately from the web service with `python portal_worker.py`. Configure it with the same
`DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, and `APP_ENV=production` as the web service, plus `GROQ_API_KEY`. The worker
polls PostgreSQL for incidents that have at least five events over 30 seconds, whose project is not paused, whose
subscription is active, and whose owner consented to AI diagnosis. It uses the GitHub REST API to read a bounded
set of source files and recent commit summaries; it does not clone repositories or run customer code or tests.
Temporary job failures are retried up to three times and are written to the project audit log. The worker stores a
diagnosis report and does not yet create a patch or pull request. The defaults can be adjusted with
`WORKER_POLL_SECONDS`, `WORKER_MIN_OCCURRENCES`, `WORKER_MIN_AGE_SECONDS`, `WORKER_LEASE_SECONDS`, and
`WORKER_MAX_ATTEMPTS`.

Deploy the portal, this worker, and PostgreSQL as separate services. Do not mount a persistent local database or
store customer source on the worker. Keep `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, and
`GROQ_API_KEY` in the hosting provider's secret environment settings.

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
| `portal_worker.py` | Subscription-gated, consent-gated hosted diagnosis worker |
| `monitoring_installer.py` | Opens the customer's opt-in monitoring pull request |
| `diagnose.py`, `run_diagnosis.py` | Legacy single-repository diagnosis flow |
| `patcher.py`, `autofix.py`, `pr.py` | Constrained patch and CI-gated pull request workflow |
| `agent_daemon.py`, `workflows.py` | Legacy local daemon and one-shot pipeline |

