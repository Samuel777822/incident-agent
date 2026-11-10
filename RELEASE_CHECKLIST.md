# Release checklist: v3 "Prove it, then push"

Status words: **Passed** (checked) · **Could Not Verify** (needs something the build environment did not have; reason given).

Environment used for checking: Python 3.13, Node.js 22, SQLite. No pytest, no internet, no Docker, no real GitHub, no AI keys, no `segno`.

| Check | Result |
| --- | --- |
| New tests `tests/test_v3.py` (proof loop with the real engine and database, free-model logic, installer, prompts, triage, journeys, site probe, UI pieces) | **30 passed** |
| New tests `tests/test_v3_web.py` (report box, flow diagram, banner, 5-second refresh, csrf, ownership, rate limit) | **4 passed** |
| `tests/browser_monitor_harness.js` (v3 browser monitor against a fake DOM: failed request on any host, retired model, noise ignored, network failure, dead click, error text, normal link) | **9 of 9 passed** (run by `tests/test_v3_browser_monitor.py`) |
| Existing tests | pytest could not be installed here, so they were run with a small stand-in runner on BOTH the original v2 code and v3: **identical pass/fail lists, nothing that passed before fails now** (222 pass on both; the rest fail identically on both for reasons of the stand-in runner, no `segno`, no Docker/Java, no real pytest inside the sandbox). `tests/test_portal_flows.py::_fake_github` now returns a file list because the installer no longer guesses "Python only". `tests/conftest.py` sets `AGENT_DIRECT_PUSH=0`, `MODEL_CATALOG_OFFLINE=1`, `FIX_JOURNEYS_ENABLED=0` for the OLD tests (they expect pull requests); the v3 tests switch direct push on themselves. **Please run the full `python -m pytest -q` on your laptop.** |
| `python -m compileall` and `node --check monitors/browser_monitor.js` | Passed |
| Real GitHub calls in `fixengine/git_ops.py` (test branch, check logs, fast-forward, PR) | **Could Not Verify**: no network. Tested through a fake with the same method names; the HTTP shapes follow GitHub's REST API. |
| Docker browser journey phase (`sandbox/Dockerfile.browser`, `sandbox/journey_runner.py`) | **Could Not Verify**: no Docker or Chromium here. It is skipped automatically if the image is missing. Check the Playwright base image tag when you build. |
| Real OpenRouter test call for the replacement free model | **Could Not Verify**: no key or network. Tested with a stand-in; with no key the live list alone decides. |

First things to try after deploying: (1) connect the Bible app repo and open the project page: the flow diagram, the "Site check" line and the report box should show; (2) type "Isaiah chapter 1 does not load" in the report box and watch the arrows on the incident; (3) break a test on purpose in a copy of a repo to watch "GitHub test failed (round 1 of 3)" go back to the AI.

---

# Release checklist: Monitoring v2

Status words: **Passed** (checked, nothing to change) · **Fixed** (checked, a problem was found and fixed) ·
**Could Not Verify** (needs something this sandbox does not have; the reason is given).

Environment used for checking: Python 3.13, Node.js 22, headless Chromium 153 (Playwright), SQLite. No internet (pip/npm installs
blocked), no Docker daemon, no PostgreSQL, no real GitHub, no AI provider keys.

## Test results

| Check | Result |
| --- | --- |
| Full test suite (`python -m pytest -q`) | **375 passed, 3 failed**. The 3 failures are all the missing `segno` package (QR codes), which is listed in `requirements.txt` but could not be installed here (no network). Expect **378 passed** after `pip install -r requirements-test.txt`. |
| New tests `tests/test_monitoring_v2.py` | **48 passed**, none skipped (the Node.js and real-browser tests ran) |
| `scripts/simulate_monitoring.py` (2-second heartbeats) | PASS: Python + Node monitors checked in every 2.0 s, the retired-model 404 arrived with the provider's full message, one incident, one fix PR |
| `scripts/simulate_monitoring.py --real` (production 30-second heartbeats, 65 s run) | PASS: check-ins at t=0.1 s, 30.1 s, 60.1 s for both Python and Node (+30.0 s each) |
| Python syntax (`compileall`) and JS syntax (`node --check` on all monitor files) | Passed |
| Lint (pyflakes) on every changed file | Fixed: removed unused/duplicate imports and variables in new and touched code. 3 pre-existing cosmetic notices in older `web_app.py` code left as is (no behaviour impact) |

## Phase 7: what the tests prove

| Requirement | Status | Evidence |
| --- | --- | --- |
| Auto-install picks the right monitor per language, incl. mixed repos | Passed | `test_auto_install_picks_the_right_monitor_for_each_part` (11 repo shapes: Flask, FastAPI package, Django, Express, ESM Node, compiled TypeScript, plain HTML, React+Vite, React CRA, Next.js, mixed Python+Vite+Express), `test_mixed_repo_gets_one_monitor_per_part_in_the_right_place` |
| Heartbeats arrive every 30 seconds | Passed | default 30 s in all three monitors (test), interval honoured by a real process (test), 30.0 s gaps in the `--real` simulation |
| An error gets reported and triggers the fix pipeline | Passed | real Python / Node / Chromium monitors report the 404 retired-model answer; `test_a_reported_retired_model_error_is_fixed_end_to_end` (ingest → worker → PR → incident record) |
| Public repo blocks install, private repo allows it | Passed | `test_public_repo_blocks_install_and_shows_simple_steps`, `test_private_repo_installs_immediately_on_connect`, `test_installer_itself_refuses_a_public_repo_before_writing_anything` |
| "Install now" re-checks and proceeds correctly | Passed | `test_install_now_rechecks_and_repeats_the_steps_while_still_public`, `test_install_now_proceeds_once_private_and_runs_the_first_scan` |
| Initial push-guard scan triggers on connect | Passed | same test (one `connect` check queued, no push needed) + `test_the_first_scan_finds_a_retired_model_without_a_push_and_without_a_sandbox` |

## A. UI and interaction audit

| Item | Status | Notes |
| --- | --- | --- |
| Every page, link, form, tab, play button, diagram node, details toggle | Passed | Headless Chromium crawled 65 page loads as visitor, customer (projects in Live / Waiting-for-private / Never-checked-in states) and admin, at 1366 px and 390 px; followed every same-origin link; sent a request to every form's target (none 404); clicked 97 interactive elements. Only non-200: `/auth/google` → 503 with a friendly "Google sign-in is not configured yet" message, which is the intended behaviour until `GOOGLE_CLIENT_ID/SECRET` are set |
| Console errors | Passed | none on any page (apart from the expected 503 above) |
| Every route: methods, auth, no crashes | Fixed | probed 69 routes × GET/POST/OPTIONS/PUT anonymously: no 500s, no customer/admin page reachable without sign-in. Added a catch-all so an unexpected exception returns a plain 500 page and is logged instead of escaping the server |
| Admin vs normal user | Passed | `/admin`, `/admin/fix`, `/admin/architecture` are 404/redirect for customers (tests); the model-adapter diagram appears only on the admin page (test) |
| Loading / success / error states of the new flows | Passed | connect (private: per-part install result; public: gate screen), recheck (still public: 409 + steps again; private: success screen), install failure (plain message, nothing changed), reinstall, replace key (auto re-commit), monitor states with fix-it steps |
| Mobile responsiveness | Passed | no horizontal overflow on any crawled page at 390 px; diagrams switch to a phone layout; gate screen shows the phone steps first on phones (screenshots checked) |
| Diagram rendering | Passed | screenshots checked on desktop and phone for both diagrams; text fits; animation off with reduced motion |

## B. Backend and integration audit

| Item | Status | Notes |
| --- | --- | --- |
| `/ingest`, `/heartbeat`: methods, validation, auth, errors | Fixed | CORS + preflight, `text/plain` JSON, key in header or body, a key can no longer speak for another project id, rejected keys logged, heartbeat recorded per monitor with a 10 s write throttle |
| Frontend ↔ backend calls | Passed | monitors' payloads verified by real-process tests; page scripts (live refresh, chat, visitor tracking) produced no console errors in the crawl |
| Database schema and migrations | Fixed | new table `monitor_heartbeats` and 7 new columns are created automatically on start; one `CASE WHEN ?` that PostgreSQL would reject was rewritten. All new SQL reviewed for PostgreSQL syntax (`ON CONFLICT … DO UPDATE`, composite primary key) |
| PostgreSQL run | Could Not Verify | no PostgreSQL server here; tests run on SQLite. First deploy runs the migrations: watch the Render log for `init_db` errors |
| GitHub integration (visibility, tree listing, install PR, fix PR, merges) | Could Not Verify (live) | every call path is covered with offline stand-ins; needs a real token and repo (DEPLOY.md step 6) |
| AI providers and adapters | Passed (code) / Could Not Verify (live) | no keys here. Model ids are configurable (`GROQ_MODEL`, `GROQ_FALLBACK_MODEL`, `CHATBOT_MODEL`, `FIXENGINE_MODEL_<MODE>`). Live model-list lookups (`fixengine/model_catalog.py`) are mocked in tests |
| No deprecated / discontinued model names in our code | Passed | test scans every source/config file (except the registry and test fixtures). Our defaults: `openai/gpt-oss-120b`/`-20b` (Groq), `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`. The OpenRouter id for Opus was already marked "verify" in RUN_TESTS.md |
| Retired-model registry accuracy | Could Not Verify (fully) | `model_registry.json` was built on 7 Nov 2026 from Anthropic's official deprecation page and public summaries of the OpenAI, Google and Groq pages (the OpenAI page itself was not reachable from here). Each replacement is double-checked against the provider's live model list before a fix is pushed; unverified swaps are never auto-merged. Review the file monthly |
| Email | Could Not Verify | no `BREVO_API_KEY` here; new emails ("make your repo private", "monitor offline") use the existing queue and were recorded in `notification_log` in tests |
| Sandbox server | Could Not Verify | no Docker daemon; the code paths with and without a sandbox are tested with fakes (the first scan works without it) |

## C. Config and deployment audit

| Item | Status | Notes |
| --- | --- | --- |
| Every environment variable listed in `.env.example`, no real secrets | Fixed | rewritten and grouped; a test checks the new variables are listed and every key/secret value is empty |
| Clear failure when a required variable is missing | Fixed | `config_check.py`: web and worker stop at start-up with one message listing what to set (`DATABASE_URL`, `TOKEN_ENCRYPTION_KEY` as a valid Fernet key, `SESSION_SECRET` for the web service). Test added |
| No hard-coded secrets, `.gitignore` | Passed | regex scan for API keys, tokens, private keys found none; `.env`, `.env.*`, `*.db` are ignored (`.env.example` kept) |
| Dependencies complete | Passed | no new Python packages were added; monitors have no dependencies. `requirements.txt` unchanged |
| Installs from scratch | Could Not Verify | pip/npm have no network here |
| Docker build | Could Not Verify | no Docker daemon. Dockerfile change: `nodejs` added to the apt line (used only for `node --check`) |
| Start commands, ports, health check vs DEPLOY.md | Passed | `run_portal.py` (gunicorn `wsgi:application`, `PORT`), worker `python portal_worker.py`, `/health` unchanged for Render; `wsgi` imports cleanly with the settings in place. `/health?deep=1` added (database + worker last seen) |
| DEPLOY.md updated | Fixed | new monitor install flow, public-repo gate, new optional variables, start-up check, first-test steps, troubleshooting rows, what happens to existing customers |
| Dead code, debug logs, blocking TODOs, broken imports | Passed / Fixed | no TODO/FIXME in app code; prints only in CLI scripts; unused imports removed; all modules import |

## Known limitations (decided, documented)

* A browser monitor's key is visible to visitors of the site (that is how browser reporting works for every vendor). It can only
  send events for that one project, is rate-limited, and can be replaced in one click.
* Browser-only sites check in only while someone has the site open; they show "No visitors right now", not "offline".
* Next.js 13/14 needs `experimental.instrumentationHook` for the server monitor, and Next.js 15.3+ for the browser part; the
  install result says so when it applies. An app with its own `instrumentation` file is not edited (the result explains the one line to add).

## v3.1 "on-call engineer": checks for you (10 November 2026)

Here (Windows laptop, no Docker, fake models): `python -m pytest -q` → `tests/test_v31.py` 33 passed. The other failures that remain
were already failing on this laptop before the release (Windows paths in the static checker, the `edit7-lines` policy test, a
monitor-install case); the full list and the comparison are at the end of the release message.

After deploying, in this order:
1. **Report box** (the crash in your screenshot): on a project, type "the home page title is wrong" and send. Expect the green
   "Sent. The agent is opening your site…" message, never "Something went wrong". Send the same text again within 5 minutes:
   "Already working on this".
2. **Double click:** click "Send to the agent" twice quickly: one case only, the button says "Working…".
3. **Sandbox server:** DEPLOY.md "Upgrading to the on-call engineer" step 2, then the one-line `run_in_docker` test.
4. **Live investigator from the portal:** send a report on a project with a site address. The case shows "Looking at your live site
   and code" and the report on the incident page lists what the browser saw. If it says "plain page fetch", the browser image or
   `/investigate` is not reachable (check `systemctl status fx-sandbox`).
5. **One case:** break one API call on a test site and reload the page 5 times: ONE case card with "N more reports merged".
6. **After a push:** the card says "Pushed · check again in 30 seconds…", then "Verified on your live site" (or "Still failing…").
7. **Reply:** on the incident page, send "it still does not work on Psalms": the same case goes back to work (no new card).
8. **Delete with clean-up** (a throw-away project): tick "Also clean my repository": the webhook and `agent-daemon/fix-…` branches
   are gone on GitHub; your code and the monitor files are untouched.
9. **Cost:** with real keys, run `bench/web_cases` with a small budget (RUN_TESTS.md layer 4) before turning it on for customers.

## Manual steps for you (before / after deploying)

1. **Before pushing:** `pip install -r requirements-test.txt` and `python -m pytest -q` on your laptop (expect 378 passed).
2. **Render environment:** make sure `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `SESSION_SECRET` (web) and **`PORTAL_BASE_URL`** are set.
   `PORTAL_BASE_URL` must be the real public https address: every monitor installed in customer apps sends its check-ins there.
   The new variables in DEPLOY.md step 2 are optional.
3. **GitHub token permissions (customers):** unchanged: a classic token with `repo` + `workflow`. `repo` already lets us read
   whether a repository is private and add the webhook (the token's owner must be an admin of the repo for the webhook).
   Fine-grained tokens are still not supported. No GitHub App is needed.
4. **Webhooks:** nothing new. After a domain change, press **Reconnect webhook** on each project (as before).
5. **After deploying:** open `/health?deep=1` (should say `"ok": true` and show when the worker was last seen). Within ~10 minutes
   the worker re-checks every existing project's visibility; public ones move to "Waiting for private repo" and their owners
   get an email. Tell customers whose monitors were Python-only to press **Reinstall monitoring** to get the new monitors.
6. **Run the first real test** in DEPLOY.md step 6 with a private repo (and once with a public one to see the gate).
7. **Monthly:** look over `model_registry.json` against the provider deprecation pages listed at its top.
