# CHANGES: v3 "Prove it, then push" (release of 8 November 2026)

Why: the v2 monitor still missed website errors (a failing outside API, a dead button, a retired OpenRouter free model), a plain
HTML/JS site could not check in every 30 seconds, JavaScript repos got "Python" errors, and every fix ended in a pull request.

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Fix pipeline (Auto mode) | sandbox test, then a pull request | sandbox test, then **GitHub tests on a test branch**. Red: the GitHub error goes back to the AI model, new sandbox run, try again (**3 rounds**). Green: the tested commit is **pushed straight to your branch, no pull request**. After 3 red rounds a pull request is opened and the dashboard says **Needs human review**. A protected branch falls back to pull request + auto-merge. A branch that moved while testing is re-tested once. (`fixengine/orchestrator.py`, `fixengine/git_ops.py`) |
| Retired free model | scanner knew only a hand-written list; OpenRouter list was empty; replacement could be a paid model | every model id in the code is checked against **OpenRouter's live list**; a free model is replaced by a **free** one (ranked by family, newest, context), confirmed with one real test call; a paid model is never chosen for a free one. "No endpoints found for ..." is recognised. (`fixengine/model_fix.py`, `model_catalog.py`) |
| Fix prompt | written for Python crashes; forbade fallbacks; gave up on outside services | rewritten for web problems (failed requests, dead buttons, pages that never fill, retired models, owner reports); up to 5 files / 120 lines; receives live-site evidence and the failed patch. (`fixengine/prompts.py`, `triage.py`, `validator.py`) |
| Browser monitor | AI-host and 5xx errors only | **v3**: any 4xx/5xx or network failure from any site, slow calls, **dead clicks** (a button clicked twice, nothing happens), **error text** appearing on the page. No screen recording, no keystrokes, no form values. (`monitors/browser_monitor.js`) |
| Every 30 seconds | only while a visitor had the page open | the worker checks the **site address** every 30 s (`site_probe.py`), finds it from the GitHub repo's website field if not set, refuses private/internal addresses, opens an incident after 2 bad answers, never for host outages. Dashboard shows "Site check". |
| Proof for UI fixes | build, tests, start-up | optional **browser journeys** (a headless browser opens pages and clicks buttons, no network) for static sites. Skipped automatically when the image is not built. (`fixengine/journeys.py`, `sandbox/journey_runner.py`, `sandbox/Dockerfile.browser`) |
| "Tell the agent what's broken" | none | box on the project page; the agent downloads the code, investigates, fixes, tests, pushes. Rate limited to 5 per hour per project. Announced with a "New" banner on the dashboard and project page. |
| Installer | put a Node `require(...)` line into browser files named app.js / index.js / server.js; guessed "Python only" when GitHub's file list failed; installed through a pull request that could stay unmerged | files loaded by `<script src>` are never treated as Node; **serverless functions** (`api/`, `netlify/functions`) are monitored; no Python guess (it stops and says so); monitoring is **committed directly** (pull request only on protected branches) |
| "Python" wording | shown for every language | removed from the legacy fixer and fallbacks |
| UI | plain step lists | arrow-connected flow on every incident, a "How Agent Daemon looks after your site" diagram, a live loop display (`GitHub test failed (round 2 of 3) · sending what failed back to the AI model`), and **auto-refresh every 5 seconds** |

## Instructions users see (copy audit)

Every place that told users "fixes never go straight to your branch" or "every fix is a pull request" was rewritten to match Auto mode (connect form and its consent boxes, token explanation, FAQ, homepage, architecture pages, diagrams, install messages). The FAQ line that said the installer "currently adds a Python error reporter" is gone. Pull request mode still opens pull requests and never touches the branch.

## New settings (all optional; defaults are right)

`AGENT_DIRECT_PUSH=1` (set `0` to go back to pull requests) · `FIX_GITHUB_ROUNDS=3` · `FIX_GITHUB_WAIT_SECONDS=1200` ·
`FIX_GITHUB_NO_CHECKS_GRACE=150` · `PROOF_POLL_SECONDS=20` · `SITE_PROBE_SECONDS=30` · `FIX_JOURNEYS_ENABLED=1`.
`OPENROUTER_API_KEY` is also used for the one test call that confirms a replacement free model answers.

## Known limits (honest)

* "Every error" cannot be promised. Dead-click detection can give a false alarm; browser journeys cannot log in; journeys run with no
  network, so a journey that needs a live outside API cannot prove that part (GitHub tests and your report cover it).
* GitHub tests only run on the test branch if your workflow has a `push` trigger (the one we add does). Without any GitHub test the
  fix is pushed only when the sandbox proved it; otherwise it goes to human review.
* Not run in the build environment (no Docker, no network, no real GitHub): the Docker browser phase, the live GitHub calls in
  `git_ops.py`, the real OpenRouter test call. Everything around them was tested with fakes. See RELEASE_CHECKLIST.md.


---

# CHANGES: Monitoring v2 (release of 7 November 2026)

Why: a customer connected an HTML + JavaScript chatbot whose AI model had been retired. The monitor "connected" but never checked
in once, nothing was detected and nothing was fixed. This release fixes the cause, installs monitoring for every language,
refuses to put anything into public repositories, scans new projects at once, fixes retired AI models automatically, and
replaces the box-style architecture pages with animated diagrams.

## Phase 1: why the monitor never checked in (root cause) and what changed

The full path was traced: connect form → `_install_monitoring` → `open_monitoring_pr` → `agent_monitor_client.py` → `/heartbeat`.
Five problems, all fixed:

1. **Only Python apps could ever start the monitor.** The installer committed `incident_agent_monitor.py` and patched only
   Python entry files (`app.py`, `main.py`, …). In a JS/HTML repo nothing imports a Python file, so the monitor never ran,
   and the page still said "Nothing else to configure". → New multi-language installer (Phase 2).
2. **Browsers could not reach the backend at all.** `/ingest` and `/heartbeat` had no CORS headers and no `OPTIONS`
   handling, and rejected anything but `application/json` (which forces a preflight). → Both endpoints answer preflights,
   send `Access-Control-Allow-Origin: *`, and accept `text/plain` JSON with the key in the body (a "simple" request).
3. **The connect form's default was "On every push" (no monitor).** Runtime errors such as a retired model never show up in
   build/tests, so they were invisible. → The form no longer asks; every project gets push checks AND live monitoring.
4. **Failures were silent everywhere.** The Python client swallowed every error, did nothing visible when the config was
   missing, and the backend showed "Connected" with no notion of "never checked in". → Monitors print one `[agent-daemon]`
   line to the app log on first check-in and on any failure (missing config, 401, no network). The backend logs rejected keys,
   stores every check-in per monitor (`monitor_heartbeats`), and the project page / dashboard / admin show "Last check-in at …",
   **Never checked in** or **Monitor offline** with steps to fix it. The worker emails the owner once.
5. **Heartbeat every 5 minutes, and refused (403) when the plan was paused.** → Every 30 seconds; check-ins are always recorded
   (fixing stays paused with the plan) so "is my monitor working?" always has an honest answer.

Files: `agent_monitor_client.py` (rewritten), `web_app.py` (`_page_ingest`, `_page_heartbeat`, `_authorized_ingest_project`,
`_project_state`, `_monitor_status_html`), `portal_db.py` (`record_heartbeat`, `monitor_state`, …), `portal_worker.py` (`monitor_sweep`).

## Phase 2: automatic monitor install for every language

* `monitoring_installer.detect_targets()` reads the repo's file list (one GitHub API call) and finds every part:
  Python (Flask, FastAPI, Django, plain), Node.js (Express, Fastify, NestJS, plain, compiled TypeScript), Next.js (server +
  browser), front-ends (plain HTML/JS, React with Vite or Create React App, Flask templates) and mixed repos.
* `plan_install()` commits the right monitor next to each part and wires it in, in the same one-PR, auto-merge pattern as before:
  Python import line (a guarded import for package entry files such as `app/main.py` or Django's `wsgi.py`, which never breaks
  the app), `node -r ./incident-agent-monitor.cjs` in the start script (or one `require`/`import` line), a `<script>` tag as the
  FIRST script of each HTML page, `instrumentation.js` / `instrumentation-client.js` for Next.js.
* New monitors: `monitors/node_monitor.cjs`, `monitors/browser_monitor.js`; Python monitor rewritten. All three: 30-second
  heartbeat (project id, status, timestamp, monitor kind, part), uncaught exceptions, unhandled promise rejections (without changing
  how a Node app crashes), `window.onerror`, console errors, failed `fetch`/XHR/`http`/`https`/`urllib`/`requests`/`httpx` calls
  (5xx anywhere, 4xx from AI providers, any "model not found / retired" answer) with the provider's full message; framework error
  logs (Flask, Django, uvicorn/FastAPI, gunicorn). Rate-limited, de-duplicated, never throw into the app.
* The tests workflow added to repos now also runs `npm install`, the build and the tests for JS/TS parts (Python steps unchanged).
* Install result is shown per part ("Flask app ✅ one import line…", "Front-end (Vite) ✅ …").
* Backend flags a project **Monitor offline** after 2 minutes without a check-in (configurable). Browser-only sites are shown as
  "No visitors right now" instead (they only check in while someone has the page open), so no false alarms.

## Phase 3: public-repo safety gate

* Connect checks visibility with GitHub first. **Public:** the project is saved in `waiting_private`; nothing is committed, no
  webhook, no scan. The customer sees the requested screen ("Your monitoring agent is about to be installed into your code, but we
  noticed your repository is public…"), numbered steps for computer and phone (the GitHub app cannot change visibility, so the phone
  steps use the browser and "Desktop site"), a direct link to the repo's settings, a GitHub Pages warning when the repo hosts a
  Pages site, and the button **I've made it private, install now**, which re-checks with GitHub: private → install + success
  screen; still public → friendly "still public" message and the steps again.
* The project page shows only this screen until it is done; the dashboard shows an "Action needed" banner and the status
  **Waiting for private repo**. The project is not marked connected/protected before the install.
* Visibility is re-checked before EVERY commit Agent Daemon makes: monitor install (`open_monitoring_pr(require_private=True)`
  refuses before writing), fix PRs (`git_ops.open_pr`, `portal_remediation.submit_fix_pr`) and auto-merges. The worker re-checks
  installed projects every ~10 minutes; a repo that became public is paused, its monitor key is revoked, waiting fixes are parked
  (they continue automatically once private), and the owner is emailed the steps (at most once a day). → `repo_guard.py`.
* Secrets hygiene: only a project-scoped key (`adi_…`) is ever written into a repository. It can only send heartbeats and error
  reports for that one project (a key can no longer claim another project's id), it is stored hashed, and **Replace key** revokes it
  and commits the new one for the customer (no copy-paste). A test asserts that our admin/master secrets never appear in any
  planned install.
* Decision: the old behaviour "public repo → install anyway, PR-only mode" was removed, because it published the monitor key.

## Phase 4: auto-fix pipeline end to end

* New deterministic path for the incident class from the report: `fixengine/model_fix.py`. A "model not found / decommissioned /
  deprecated" error (OpenAI, Anthropic, Groq, Google, OpenRouter formats) or a scan finding →
  replacement from `model_registry.json` → double-checked against the provider's live model list (`fixengine/model_catalog.py`;
  OpenRouter's public list needs no key) → the model id is replaced everywhere it is set (never in `.env` files) → validation:
  the sandbox check when the sandbox is online, otherwise parse checks (Python AST, JSON, `node --check`) → normal PR flow via
  `git_ops.open_pr` → incident recorded with error, diagnosis, fix diff, PR link and status. No AI tries are spent.
  If the model id is not in the code (it lives in the host's environment variables) the customer gets exact instructions instead
  of a broken PR. Report-only projects get the diagnosis without a PR.
* Auto-merge only when the replacement was verified on the live list AND validation passed; otherwise the PR waits for review.
* A retired-model error reported by several monitors is grouped into ONE incident and ONE PR.
* JS stack traces now produce stable incident signatures (previously only Python tracebacks did).
* Everything else continues through the existing router → adapter → sandbox engine, which already handled JS/TS/HTML/Python/mixed.
* Fixes: report texts no longer contain literal `\n\n`; incidents waiting for a public repo are parked, not failed.

## Phase 5: push guard initial scan

* Right after connecting (and after the gate is passed) the latest commit is queued with source `connect` and checked at once.
* New `push_watch.static_scan()` runs on that first check and every push: it scans the code for retired AI model ids. It runs
  even while the sandbox server is offline (the sandbox part waits honestly). Findings become `scan` incidents and go through the
  Phase 4 pipeline; findings that disappear are closed. Webhook and poller ignore projects still waiting for a private repo.

## Phase 6: architecture diagrams

* New `arch_diagrams.py`: animated SVG flow diagrams (flowing dashed arrows, glowing nodes, labelled connections, legend,
  click/tap-to-explain nodes, "Play the flow" walkthrough, keyboard accessible, `prefers-reduced-motion` respected), drawn twice:
  a wide layout for desktop and a tall one for phones.
* General architecture (connect → public-repo check → make private loop → install monitor → monitors → 30-second heartbeat →
  backend → monitor-offline alert; push/first scan → push guard → error detected → sandbox → diagnosis → model adapters → fix →
  tests (retry loop) → PR, plus the retired-model shortcut): shown on `/how-it-works` (everyone) and `/admin/architecture`.
* Model adapter architecture (fix pipeline → router → guard → Groq/Anthropic/OpenRouter adapters → providers → normalizer,
  automatic fallback policy, what the router weighs, live model ids from config): admin only.
* Role visibility unchanged: `/admin/architecture` is 404 for non-admins (test added). The old box grids and the "Request flows"
  tab were removed; the code map is kept as a collapsible text list under each diagram.
* Decision: the customer page keeps its existing text section "How the agent decides which AI to use" (pricing education, not a
  diagram); only the general diagram is shown there.

## Phase 7: verification

* `tests/test_monitoring_v2.py` (48 tests): per-language install for 11 repo shapes including mixed; real Python, Node.js and
  headless-Chromium monitors sending heartbeats and reporting a retired-model 404 with the full message; heartbeat interval;
  CORS; project-scoped keys; status states; public repo blocks install; "install now" re-check (still public / now private);
  private installs immediately and queues the first scan; repo turning public pauses commits and revokes the key; error → fix
  PR end to end for JS and Python/mixed repos; hosting-env-only model; no fix pushed to public repos; first scan without a push
  or sandbox; recognition of each provider's error format; live-list verification; no retired model ids in our own code;
  diagram roles; config fail-fast; `.env.example` completeness.
* `scripts/simulate_monitoring.py`: local end-to-end simulation (also with `--real` 30-second timing).

## Phase 8: deployment-readiness fixes

* `config_check.py`: web and worker refuse to start with one clear message if `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY` (must be a
  valid Fernet key) or, for the web service, `SESSION_SECRET` are missing in production; warnings for `PORTAL_BASE_URL`, email, AI keys.
* `/health?deep=1` also checks the database and reports when the worker was last seen (plain `/health` unchanged for Render).
* Unhandled exceptions in a request now return a plain 500 page and are logged, instead of escaping the WSGI app.
* No hard-coded AI model ids left in code paths: `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`, `CHATBOT_MODEL`, `FIXENGINE_MODEL_<MODE>`.
* Dockerfile installs Node.js (used only for `node --check` parse validation of JS fixes; it never runs customer code).
* `.env.example` rewritten: every setting, grouped, no secrets. `DEPLOY.md`, `README.md`, `ARCHITECTURE.md`, help page updated.
* Small cleanups: duplicate/unused imports, "Pr mode" label, "1 check-ins".
