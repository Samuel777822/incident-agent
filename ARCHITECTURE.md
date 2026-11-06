# Architecture (v3, November 2026)

Agent Daemon has **two entry points and one fix engine**. The interactive version of this document is at `/how-it-works`
(customers) and `/admin/architecture` (admins, with live numbers and a router simulator).

```
                    ┌──────────── PUSH GUARD (v3, new) ────────────┐      ┌──────── LIVE ERROR WATCH (classic) ───────┐
 developer ─ git push ─► GitHub ─ signed webhook ─► /webhooks/github/<id>     live app ─ crash ─► runtime adapter ─► /ingest or /ingest/browser
                             └─ (missed?) worker poll every 3 min ─┘                │
                                          │                                         │ dedupe into an incident
                                          ▼                                         │
                              push_checks queue (one row per commit)                │
                                          │  worker: push_watch.run_check()         │
                                          ▼                                         │
                  download THAT commit → detect every stack → sandbox per stack     │
                  (install → build/type-check → tests → start-up)                   │
                       │ green: commit status ✓ (done, free)                        │
                       │ red:   commit status ✗ + incident (source=push) ───────────┤
                                                                                    ▼
                                         FIX ENGINE (fixengine/orchestrator.py)
            download branch → baseline in sandbox (already green? resolve, 0 tries) → loop:
                router (expected-cost DP + hard rules) → guard (quota, budget, kill switch)
                → adapter (Groq | Anthropic | OpenRouter; text in, text out) → policy (≤3 files, ≤40 lines, no tests/CI/deps/secrets)
                → SAME sandbox check on patched code → pass? ─ no ─► back to router with the new error / stronger diagnosis
                                                         └ yes ─► branch agent-daemon/fix-… + PR, title ends with [agent-daemon]
                                                                  proven? set ✓ status on the fix commit
                                                                  Auto mode: worker squash-merges when all checks are green
            stopped (caps, quota, give-up cheaper) → human-review report + email
```

## Components

| Component | File | Runs on |
| --- | --- | --- |
| Web portal (pages, auth, webhooks, ingest, payments) | `web_app.py`, `footer_pages.py`, `homepage.py`, `architecture.py`, `live_status.py`, `incident_board.py` | Render web service (gunicorn) |
| Worker loop | `portal_worker.py` | Render worker (or inside the web service when `PORTAL_RUN_WORKER=1`) |
| Push guard | `push_watch.py` | web (webhook) + worker (checks, polling) |
| Fix engine | `fixengine/` (orchestrator, router, guard, adapters, prompts, validator, sandbox, store, notify, ui) | worker |
| Sandbox host | `sandbox_service.py` + `sandbox/Dockerfile.*` | a small VPS with Docker |
| Database | `portal_db.py` (+ `fixengine/store.py` tables) | PostgreSQL (SQLite locally) |
| Runtime monitoring installer + reporters | `monitoring_installer.py`, `monitoring_adapters.py`, `agent_monitor_client.py` | install PR + customer app |
| Email | `notifications.py` (Brevo/Resend over HTTPS) | web + worker |

## Mixed-language repos

`fixengine/sandbox.detect_profiles()` finds every project by its marker file at the root or one/two folders deep:
`package.json` (JavaScript/TypeScript; `tsc --noEmit` when TypeScript is a dependency), `pom.xml`/`build.gradle` (Java),
`requirements.txt`/`pyproject.toml`/`setup.py` or `.py` files (Python), and loose `.html` files (static site, checked by
`sandbox/static_check.py`, which skips the other stacks' folders and server-side `templates/`). One-language repos behave exactly as
before. A mixed repo becomes a `StackSet`; `run_profile()` runs each stack in its own fresh container and the repo is green only when all
are green. The model may edit files of any of these languages in one fix.

## Live stages (what the dashboard shows)

`incidents.stage` / `stage_detail` / `stage_tier` are written by the engine at each step:
`queued → downloading → reproducing → thinking (mode) → testing_fix → pushing → pr_open | merging → merged`, plus
`waiting_user`, `waiting_retry`, `needs_human`, `resolved`. Push checks have their own stages
(`queued, downloading, detecting, testing, waiting_sandbox, waiting_retry, passed, failed, skipped, error`).
`live_status.py` turns them into a headline, a step tracker, the working mode and "N tries left". The dashboard and project page
refresh by themselves (`/dashboard/live`, `/projects/<id>/incidents/live`) every 3 s while something is running, 15 s otherwise.

## Verification levels

| Level | Meaning | Auto-merge? |
| --- | --- | --- |
| `tests_fixed` | tests failed before, pass now | yes |
| `check_fixed` (v3) | the push check failed on the pushed commit and the identical check passes after the fix | yes |
| `tests_pass_not_reproduced`, `smoke_only`, `build_only` | not proven | no, PR only |

## The router (cost function)

```
V(s) = min_a [ c_eff(a,s) + (1 − p(a,s)) · V(s after a fails) ],   V(fixed) = 0,   V(stop) = G
c_eff = estimated ₹ cost of one try × (1 + λ · share of that mode's monthly quota already used)
p     = success chance per bug class (placeholders, replaced by measured (successes+1)/(tries+2)), × 0.7 per earlier failure
```
A small memoised dynamic program (depth 6): the "cheapest route" idea of Dijkstra adapted to steps that can fail. Hard rules on top:
per-bug caps, the user's pick, free first, Normal floor of 2, drop back to Normal after a strong model, no repeat with the same
information, never past quota. Every decision is logged in `fx_router_decisions`.

## Who sees what

* Customers see modes (Low effort / Normal / High / Extra), tries and plain sentences. Shared wording lives in `plans.py`.
  Router reasons shown on the dashboard are translated by `live_status.customer_reason()`; model names never appear.
* Admins see model ids, rupees, formulas and raw decision data on `/admin/fix` and `/admin/architecture`.
* The ₹30 give-up penalty G is an internal optimisation value only. It is never billed.

## Data model additions in v3

* `push_checks` (one row per checked commit; unique per project + sha; superseded when a newer push arrives before it starts).
* `projects.watch_mode` (`push` | `runtime` | `both`), `webhook_id`, `webhook_secret_ciphertext` (Fernet), `last_checked_sha`,
  `last_check_status`, `last_check_at`.
* `incidents.source` (`runtime` | `push`), `commit_sha`, `stage`, `stage_detail`, `stage_tier`, `stage_at`.
* `users.project_slots` (paid extra projects). `manual_payments.plan` now also takes `project_slot`, `pack_high`, `pack_extra`.
* All added with idempotent migrations in `portal_db.init_db()`; nothing to run by hand.

## Safety

* Customer code runs only in the sandbox: fresh container per run, non-root, read-only root FS, caps dropped, memory/CPU/PID/time
  limits, no network except dependency install, no secrets, Docker socket never mounted.
* Webhooks are verified with a per-project HMAC secret. The webhook only queues a check; it never runs anything.
* Browser monitoring uses a separate write-only, project-scoped token; its endpoint is rate-limited and checks the configured app origin. The full ingest key is never embedded in browser JavaScript.
* Fix loops are impossible by construction: fix branches are ignored by the push guard, and a failing check on a commit whose message
  carries `[agent-daemon]` goes straight to a human.
* Push checks are rate-limited per project (12/hour by default) and cost no AI tries.
