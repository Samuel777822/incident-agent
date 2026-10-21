# Agent Daemon

Agent Daemon is a multi-tenant on-call service. This repository contains the account portal, project storage,
monitoring installer, access control, and a separate portal diagnosis worker. The hosted portal can turn repeated
events into project-scoped diagnosis reports. Repository repair, fix pull requests, auto-merge, health checks,
monitoring verification, and automatic rollback are not yet connected to this worker.

## Web application

The server-rendered site is in `web_app.py`. It provides account sign-in, owner-scoped projects and incidents,
per-project event ingestion, project controls, and administrator-managed access. Local development uses SQLite;
production requires PostgreSQL via `DATABASE_URL` and HTTPS in front of the app.

Set these values before production startup:

| Variable | Purpose |
| --- | --- |
| `SESSION_SECRET` | At least 32 random characters for signed sessions |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting customer GitHub tokens |
| `DATABASE_URL` | PostgreSQL connection URL |
| `ADMIN_EMAIL` | Administrator login email |
| `ADMIN_PASSWORD` | Strong private password for the administrator login; never commit it |

Run locally with `python web_app.py`. For production, use the Gunicorn entry point in `wsgi.py`; the Dockerfile
starts it with multiple worker threads and validates the required session secret and database at startup. The project
creation page requires explicit monitoring-install consent, AI processing consent, and a GitHub token. The **Open monitoring PR** action creates a branch and pull request containing an opt-in Python helper
and setup notes. The PR contains no credentials. After reviewing and merging it, configure `INCIDENT_AGENT_INGEST_URL`
and `INCIDENT_AGENT_INGEST_KEY` in the customer's deployment environment. The ingest key is shown once; only its
hash is stored by the portal.

The `/ingest` endpoint accepts JSON with an `X-Ingest-Key` header. `/heartbeat` uses the same project key. Events are
deduplicated per project, and dashboard queries scope projects and incidents to their owner. New project setup asks
for explicit consent before selected logs, tracebacks, and relevant Python source files are sent to Groq for diagnosis.
Project access is granted only by an administrator and expires at the configured grant date.

## Hosted diagnosis worker

Run one worker process separately from the web service with `python portal_worker.py`. Configure it with the same
`DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, and `APP_ENV=production` as the web service, plus `GROQ_API_KEY`. The worker
polls PostgreSQL for incidents that have at least five events over 30 seconds, whose project is not paused, whose
subscription is active, and whose owner consented to AI diagnosis. It uses the GitHub REST API to read a bounded
set of source files and recent commit summaries; it does not clone repositories or run customer code or tests.
Temporary job failures are retried up to three times and are written to the project audit log.
Report mode stores diagnosis only. Pull request and Auto modes require separate explicit remediation consent and
only attempt a small, high-confidence Python source edit. The worker never executes customer code or tests. It opens
a reviewable fix PR and saves its diff in the incident view. Auto mode merges only an open PR whose unchanged head
has at least one completed GitHub check/status and all checks it can read succeeded. Missing, failed, pending, or
unavailable checks leave the PR open. The defaults can be adjusted with `WORKER_POLL_SECONDS`,
`WORKER_MIN_OCCURRENCES`, `WORKER_MIN_AGE_SECONDS`, `WORKER_LEASE_SECONDS`, `WORKER_MAX_ATTEMPTS`, and
`AUTO_MERGE_POLL_SECONDS`.

The Docker web service starts a small supervisor that runs Gunicorn and the incident worker together, which supports
Render's free web-service plan. Configure `PORTAL_RUN_WORKER=0` only when deploying a separate worker service, as
the paid Blueprint does. Free Render services sleep after inactivity, so the worker only processes jobs while the
web service is awake. Keep `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, `GROQ_API_KEY`,
`ADMIN_EMAIL`, and `ADMIN_PASSWORD` in the hosting provider's secret environment settings.

## Render deployment

The root `render.yaml` defines the web service, a continuously running worker, a private paid Postgres database,
and separate secret groups. Connect the repository to Render and create a Blueprint from this file. Render will
prompt for `GROQ_API_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`; it generates the session and token-encryption
secrets. Verify the generated `TOKEN_ENCRYPTION_KEY` is a valid Fernet key before onboarding customers. Online
checkout is disabled; an administrator grants access after confirming a payment or approving a trial. Paid Postgres is specified
so database recovery is available; on Render's Hobby workspace, its documented recovery window is three days.

The hosted repair path is a supervised pilot. Post-merge health monitoring, automatic rollback, and heartbeat alerts
remain unimplemented. Start with Pull request mode and review its changes. Auto mode is CI-gated and must be enabled
only for repositories with working GitHub checks. Do not treat a passing CI check as proof that a production deployment
is healthy.

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

## Administrator accounts, trial requests, and email

Set `ADMIN_EMAILS` to a comma-separated allowlist of administrator addresses. Each administrator needs a distinct secret password in Render:
- `ADMIN_PASSWORD_NAVEENACHANDRA371_GMAIL_COM`
- `ADMIN_PASSWORD_PRANAVVRAO1_GMAIL_COM`

Each password must contain at least 12 characters. Do not put administrator passwords in Git or send them in chat. The listed addresses are reserved and cannot be registered through public signup. If using this dual-admin setup, configure `ADMIN_EMAILS`; do not rely on the legacy single `ADMIN_EMAIL`.

Trial requests are stored in PostgreSQL and visible in `/admin`. Approval grants one day from the time of approval; rejection and approval send a customer decision email when SMTP is configured. Trial-request notifications are sent to every address in `ADMIN_EMAILS`. The dashboard still stores the request if SMTP is unavailable and shows that delivery could not be confirmed.

Configure SMTP using Render secret environment variables:
- `SMTP_HOST` (for Gmail, `smtp.gmail.com`)
- `SMTP_PORT` (usually `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD` (use a provider app password where required)
- `EMAIL_FROM` (verified sender address)

A message is reported as sent only when the SMTP server accepts it. Check Render application logs for delivery errors; SMTP acceptance alone cannot guarantee inbox placement.

## Subscription plans

The billing page offers ₹100 monthly (30 days) and ₹1,000 yearly (365 days). Amounts are configured in paise using `RAZORPAY_MONTHLY_AMOUNT_PAISE` and `RAZORPAY_YEARLY_AMOUNT_PAISE`; defaults are `10000` and `100000`. The older `RAZORPAY_AMOUNT_PAISE` is retained as a yearly-plan override for backward compatibility. Use `RAZORPAY_MODE=test` and `rzp_test_` credentials for validation first. Live checkout requires `RAZORPAY_MODE=live` with a matching `rzp_live_` key ID and secret; do not enable live mode until test checkout, server-side payment capture verification, and renewal behavior have been validated.

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

