# Agent Daemon

**Push your code. Agent Daemon catches what broke, fixes it, and pushes the fix back to GitHub, before you deploy.**

Built for vibe coders, students and hackathon teams. Works with Python, JavaScript, TypeScript (React, Next.js, Node, Vite),
Java (Maven, Gradle, plain `javac`) and plain HTML/CSS/JS sites, including repositories that mix several of them.

| Doc | What is in it |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Both architectures (push guard and live error watch), components, data model, stages, algorithms |
| [DEPLOY.md](DEPLOY.md) | Step by step, for beginners: Render, the sandbox server, GitHub, email, domain, first test |
| [FIXENGINE.md](FIXENGINE.md) | The fix engine: router, quotas, sandbox, languages, budget |
| [RUN_TESTS.md](RUN_TESTS.md) | Running the tests, the Docker images, the sandbox abuse check and the paid benchmark on your laptop |
| [CHANGELOG.md](CHANGELOG.md) | What changed and why |

## Two ways to catch bugs (a project can use one or both)

1. **Push guard (new, recommended).** Connecting a repository adds a GitHub webhook. Every push to the tracked branch is
   downloaded into a fresh sandbox; every project inside the repo is installed, built (and type-checked), tested and started.
   The commit gets an `Agent Daemon / push check` status on GitHub. If it is red, an incident opens and the fix engine starts.
   If the webhook cannot be added, the worker polls the branch every few minutes instead.
2. **Live error watch.** A small monitor inside the running app, installed automatically for every part of the repo (Python,
   Node.js/TypeScript, web pages; mixed repos get one per part). It checks in every 30 seconds and reports crashes, unhandled
   promise rejections, console errors and failed API calls (e.g. a retired AI model) to `/ingest`; the project page always shows
   "Last check-in at …", "Never checked in" or "Monitor offline".

**Public-repo gate.** Nothing is ever committed to a public repository. Connecting a public repo shows simple steps to make it
private and an "I've made it private, install now" button; visibility is re-checked before every commit Agent Daemon makes.
Right after connecting, the existing code is scanned once (no push needed), and retired AI model ids are fixed without AI tries.

The fix engine: free first look → cost-aware router (expected-cost dynamic program) picks Normal / High / Extra → the model returns a
small patch as text → policy check → **the same sandbox check must pass** → branch `agent-daemon/fix-…` + pull request → in Auto mode
it is merged once proven, so the fixed version is on GitHub. Everything is shown live on the dashboard.

## Pages

| Page | Who | What |
| --- | --- | --- |
| `/` `/how-it-works` `/pricing` `/features` `/faq` `/help` | everyone | Product, the interactive diagram, how the agent chooses an AI (with a calculator), plans |
| `/dashboard` | customer | Tries left per mode, "Agent right now" (live stage + mode + tries left), projects |
| `/projects/new` | customer | Connect a repo (1 included, ₹30 per extra project) |
| `/projects/<id>` | customer | Live monitor status (last check-in), push checks (per stack), bugs and fixes, settings |
| `/projects/<id>/make-private` | customer | The public-repo screen: step-by-step instructions and the "install now" re-check |
| `/usage` | customer | Tries per mode, Auto / Ask me / Economy, decisions, buy packs |
| `/billing` | customer | Plans (30 Normal / 6 High / 3 Extra a month), add-ons, UPI payments |
| `/admin` | admins | Customers, trials, UPI payments to confirm (plans, slots, packs), apps, incidents, tickets, email |
| `/admin/fix` | admins | Spending at a glance, protections explained, approvals, mode switches, per-mode and per-customer spend, history |
| `/admin/architecture` | admins | Animated general + model-adapter architecture diagrams, a 10-lesson course on the router, router simulator |

## Plans

* ₹200 / 30 days or ₹1,500 / 365 days. Every month: **30 Normal, 6 High, 3 Extra** tries plus Low effort on fair use. No rollover.
* **1 project included; each extra project is a one-time ₹30** (the slot stays on the account). Tries are per account.
* Add-ons: ₹100 = 5 High tries or 3 Extra tries for the current month.
* Payment: UPI QR + UTR, confirmed by an admin (one button, which says exactly what it grants).
* One place for every number: `plans.py` (prices, products) and `fixengine/config.py` (quotas, caps, model prices).

## Admins and support

Admins are `pranavvrao@agentdaemon.xyz` and `abhaysamuel@agentdaemon.xyz` (default; `ADMIN_EMAILS` overrides).
Support address: `contact@agentdaemon.xyz` (default; `SUPPORT_EMAIL` overrides). Admin addresses cannot sign up on the public form.

## Run it locally

```
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
export SESSION_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(40))")
python web_app.py                                         # http://127.0.0.1:8080  (SQLite, no worker)
python portal_worker.py                                   # second terminal: checks, fixes, polling
```

## Tests

```
python -m pip install -r requirements-test.txt
python -m pytest -q          # 378 tests, offline; Node / a JDK / Playwright make a few extra tests run
python scripts/simulate_monitoring.py   # monitors -> check-ins -> error -> fix PR, locally, in ~15 seconds
```

## Environment variables

See [DEPLOY.md](DEPLOY.md) for where each one goes. Most important:

| Variable | Purpose |
| --- | --- |
| `APP_ENV`, `DATABASE_URL`, `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY` | core (PostgreSQL in production, Fernet key for tokens) |
| `PORTAL_BASE_URL` | public URL; used for webhook URLs, email links and commit-status links |
| `ADMIN_EMAILS`, `SUPPORT_EMAIL`, `ADMIN_PASSWORD_<EMAIL>` | admins, support address, admin password sign-in |
| `BREVO_API_KEY`, `EMAIL_FROM` | email over HTTPS |
| `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `FIXENGINE_PROVIDER` | AI providers |
| `FIXENGINE_ENABLED` | `1` turns on the multi-language fix engine |
| `FIXENGINE_SANDBOX_MODE=remote`, `FIXENGINE_SANDBOX_URL`, `FIXENGINE_SANDBOX_SECRET` | the sandbox server (Render cannot run Docker) |
| `PUSH_CHECKS_ENABLED` (default `1`), `PUSH_POLL_SECONDS` (180), `PUSH_MAX_CHECKS_PER_HOUR` (12) | push guard |
| `MONITOR_OFFLINE_SECONDS` (120), `MONITOR_FIRST_CHECKIN_GRACE_SECONDS` (1800), `VISIBILITY_CHECK_SECONDS` (600) | monitor status and the public-repo re-check |
| `MODEL_REGISTRY_JSON`, `GROQ_MODEL`, `FIXENGINE_MODEL_<MODE>` | AI model ids and the retired-model list, without a code change |
| `FIXENGINE_BUDGET_INR`, `FIXENGINE_CREDITS_INR` | global budget B and prepaid credits |
| `PLAN_PRICE_MONTHLY_INR`, `PLAN_PRICE_YEARLY_INR`, `PROJECT_SLOT_PRICE_INR` | change prices without a code change |
| `UPI_ID`, `UPI_PAYEE_NAME` | UPI recipient |

Never commit secrets. Keys go only into Render's Environment screen (or a local `.env`, which git ignores).

## Legacy files

`server.py`, `agent_daemon.py`, `db.py`, `sync_and_tail.py`, `workflows.py`, `autofix.py`, `pr.py`, `repos.json` and friends are the
original single-repo daemon (coffee-shop demo, runs as its own Render service). They are kept so that service keeps working.
