# CHANGES: v3.1 "The on-call engineer" (release of 10 November 2026)

Why: the "Tell the agent what's broken" box crashed on PostgreSQL ("Something went wrong on our side"), one broken API became
several paid investigations, one flooding project paused paid AI for everyone, and a typed report was a blind guess: the agent only
read code, could not see the live site, and pushed fixes that nothing had proven. This release makes the agent behave like an
on-call engineer: understand the request, look at the real site, find the cause, fix it, prove it, push it, check the live site
again, and tell the client honestly.

## v5.2: A careful engineer that never overwrites your work (11 November 2026)

* **Your newer changes are never thrown away.** The engineer works on a copy of your code; before anything is written to GitHub
  (a push, a pull request, an earlier run's edits carried over, or "Undo this fix"), its change is merged line by line onto your
  branch AS IT IS NOW. If you edited other lines meanwhile, both are kept. If you edited the very same lines, nothing is written:
  the agent redoes the fix on your latest code (after three such clashes it stops and asks you to press Run again). If you push at
  the exact second of the write, GitHub refuses it and the agent merges again. Undo only takes back the agent's own lines.
* **The engineer tests its own work.** It writes a NEW test that reproduces the problem (or says why a test is impossible), runs
  everything, may not finish while anything is red, and sees its whole diff with a checklist after every green run (is every line
  needed, was anything you built removed, do the callers still work). Our own sandbox then checks that the new test FAILS without
  the fix, so a test that proves nothing is flagged for review.
* **No whole-file rewrites.** Existing files longer than 60 lines may only be changed with exact edits: rewriting a file from
  memory is how code silently disappeared.
* **Memory.** Every run on a project is remembered (what was asked, the cause, the files changed, the tests written, fixes that were
  undone) and shown to every later run, together with the project notes the engineer keeps up to date.
* **Nothing pauses itself.** Budget levels, spending spikes, a fast-spending project, a busy customer and AI key or credit problems
  only email the admins (once an hour or once a day). Only an admin pauses a mode. An older automatic pause is released once.
* **Answer box.** When the agent asks you something, the question and a box to answer it are on the case card and the dashboard.
  The live refresh no longer wipes what you are typing.
* **20 Normal tries for Rs 30**, on Usage, Billing and Pricing, credited when the admin confirms the payment.
* **Ready to host, planned for your app.** The check now finds each part of the repository (front-end, API, Python app, static site,
  Java service, also in sub-folders), its real start command (the actual Flask/FastAPI app object, Django's wsgi, Streamlit), the
  services it uses, and its own pitfalls: page refresh 404s on single-page apps, a front-end without an API address, CORS, SQLite and
  uploads that free hosts wipe, a missing gunicorn/uvicorn, an empty ALLOWED_HOSTS. The plan deploys the API first, then the
  front-end, then lists what to update after (Supabase / Firebase / Google sign-in URLs, Stripe webhook, MongoDB access). "Make it
  host-ready" asks the engineer to read the whole app, correct the first look, fix the code and write the steps for this app.

## v5.0: One look for every page (11 November 2026)

* **Shared design layer (`theme.py`):** a wider page, larger text, calmer headings (Cinzel only for titles), and one style each for
  cards, buttons, pills, tables, forms and messages, on every public, customer and admin page. The background artwork is dimmed
  behind working pages so text stays readable. The header stays at the top while you scroll.
* **Project page:** a section menu (Tell the agent, Bugs and fixes, Push guard, Live monitor, Settings), cases named after the error
  instead of "Incident 4f3a...", roomier case cards, Settings as wide cards, and deleting a project in its own danger zone. The
  explainer diagram is folded away.
* **Connect a project:** the form sits beside the GitHub setup guide, which is now three folds instead of one wall of text.
* **Admin:** a section menu, a ticket form you can read, a clear card when EMAIL_FROM is missing, and the spending page restyled.
* **Billing and Usage:** larger prices, a fine-print box, pack buttons that no longer wrap.
* **Fix:** a push check whose saved stack list is not in the expected shape no longer breaks the dashboard.

## v4.3: Emails that get through, and the How it works / Usage pages redesigned (11 November 2026)

* **Email:** every configured provider is tried in turn (Brevo, then Resend, then SMTP), and a busy or unreachable provider gets one
  retry. EMAIL_FROM may be written as `Name <address>`, and quotes or spaces pasted around keys are ignored. Each email now has a text
  and a plain HTML copy plus a reply-to address (contact@...), which looks less like spam. Every failed row in the admin "Email
  status" table now says in plain words what to change and where (for example Brevo's "unrecognised IP address": Security,
  Authorized IPs; a wrong key; an unapproved sender; an account Brevo has not activated yet).
* **How it works:** the engineer section is interactive. Five clickable steps play a terminal replay of a real-looking case, followed
  by the Normal, High and Extra ladder with what each run may cost, and the "code problem?" and "sure or not sure" outcomes.
* **Usage:** progress rings for each mode and for the whole month, clickable mode tiles, pack cards and a cleaner list of recent bugs.

## v4.1: Haiku first, Auto mode decides "sure or not" (11 November 2026)

* **Haiku 5.5 is the first engineer on every case, at full strength:** the whole code base (up to about 60K tokens, so Haiku stays
  in its cheapest price band), every tool, high reasoning effort, at most about Rs 15 per run (estimated Rs 3-10 for a normal
  case). It stops there when it fixes the problem, writes steps for the owner, or asks a question.
* **Sonnet takes over only when Haiku does not finish** with a fix that passes the checks, starting from what Haiku found
  (about Rs 90 cap per run). **Opus last**, once, and only after asking the owner with the buttons on the case card.
* **No free model in fixing.** Free OpenRouter models allow about 50 requests a day (one engineer run uses 20-40), may log prompts
  (customer code), and their patches were the weakest.
* **Auto mode: sure pushes, not sure asks.** Sure = our sandbox passed the final change, the engineer ran the checks on it, it rated
  the risk low, and nothing is left for the owner. Then the fix goes straight to the branch (GitHub tests first, live check after,
  automatic undo when the site gets worse). Anything else becomes a pull request whose reason starts "the agent is not sure: ...".
  No extra reviewer model is paid on this path.
* **Every page now describes the new system** (copy audit): homepage, /how-it-works (the old router maths and cost calculator are
  replaced by "How the agent fixes a problem"), features, FAQ, privacy, terms, the project flow, the dashboard and Usage (no free
  "Low effort" card or meter any more), the help chat's knowledge, the architecture diagram, the connect form's consent text (it now
  says the repository's source code goes to Claude through OpenRouter), and one FAQ answer that was simply false ("your code is never
  executed": it runs in the sandbox). Economy mode is enforced by the engineer (Normal only). The admin course on the old router is
  kept and labelled as the fallback engine used only without an OpenRouter key.
* **"Not right? Let a stronger AI look"** on "Needs you" cases: the next stronger model (Haiku -> Sonnet -> Opus) reads everything
  again with what was found so far. You decide when to spend more.

## v4: the engineer (11 November 2026)

Why: on Bible-Well the old engine replaced a working Supabase key with `'public-anon-key'` (8 Nov), then pushed seven patches in 36
minutes to repair its own damage (a key moved to a missing env var, a fake Supabase client, a hidden error message) and deleted the NIV
Bible version. It never ran the app, never read its own history, and wrote a JSON patch from a few files in one shot.

* **The engineer (`fixengine/agent.py`).** With `OPENROUTER_API_KEY` set, Claude Sonnet 5.5 works each case with tools on a real copy
  of the repository: the whole code base in the first message when it fits (about 110K tokens, cached), list / read / search / edit /
  write files, run install-build-test-start in the sandbox, open the live site in a real browser (with clicks), read recent commits and
  diffs (Agent Daemon's own fixes are marked), search the web (OpenRouter web plugin, about $0.01 a search), check AI model ids.
  It ends with a proven fix, beginner steps for the owner, one question, or an honest stop. Opus 5.5 gets one run when Sonnet does not
  finish, with what Sonnet found. No more Groq / Haiku ladder for fixes, no 5-file / 120-line limit. Bounds per run: 45 steps,
  25 minutes, about Rs 90, 5 sandbox runs, 5 live-page visits, 6 web searches. `FIX_AGENT_MODE=0` returns to the old loop.
* **Harm rules on every agent change** (`validator.agent_change_problems`), checked before anything leaves the sandbox: no placeholder
  values, no moving a working key into an env var, no stub / fake / mock clients, no removed error reporting, no removed options, no
  edits to the monitor, CI, lock, secret or existing test files. Replaying the Bible-Well commits: every harmful one is rejected.
  Dependency / build-setting changes, "high risk" fixes and fixes that also need the owner always go to a pull request.
* **Our own check of the final change:** the engineer's checks are not trusted; the orchestrator runs the sandbox on the final files.
* **"Needs you" for a beginner:** what is wrong, why, numbered steps with exact sites / menus / values, how to check it worked, and an
  **I did it, check again** button.
* **Pause / Start per case**, **Pause all open cases**, and **auto-start** on/off (off: problems found automatically wait; your own
  reports always start). A running engineer stops at its next step when you pause.
* **Pull requests explained:** each case with a fix shows "what to do now" (open, check Files changed, Merge, Confirm, wait for the
  host) and an **I merged it, check my site** button that starts the live check.
* **Undo this fix** on fixes that went live (direct push or merged pull request): the changed files go back with a new commit.
* **What the engineer did:** a step-by-step timeline on the case page. Project notes it learns are kept for the next case.
* **Noise filter:** rate limits (HTTP 429), analytics / ad scripts, browser extensions and missing favicons no longer become cases.
* Fixed a bug the new tests caught: path cleaning turned `.env` into `env`, so the secret-file guard would not have recognised it.

Tests: `tests/test_v4_agent.py` (18): the Bible-Well replay, the engineer loop (read, search, edit, refused unchecked finish, checks,
finish), a refused harmful finish that ends as owner steps, pause, budget, secret files, the OpenRouter transport (tools, reasoning,
HTTP 402), whole cases through the orchestrator (Sonnet fixes it -> PR; Sonnet gives up -> Opus with Sonnet's findings; not a code
problem -> beginner steps and no Opus; a stub fix is never sent), pause / resume / auto-start, noise, the case buttons, undo.
Full suite: 463 passed; the 5 failures are the same Windows-only ones as before.

Not tested here: real model runs (no OpenRouter key on this laptop). The first real cases are the test.

## v3.2: stop wasting tries, see sign-in problems, audit on connect (10 November 2026, evening)

From the second live test ("Continue with Google sends me back to login": Groq, Haiku, Sonnet and Opus all tried, nothing fixed,
then "Too many tries this hour · retrying in about 15 min").

* **The ladder stops when the cause is outside the code.** Before, a model answering "this is a setting, not code" counted as a
  failed try, so the same question went to the next, more expensive model, up to Opus. Now a strong model's answer ends the case as
  **Needs you** with numbered steps naming the console, the setting and the value ("In Google Cloud Console > Credentials > … add
  https://…/callback to Authorized redirect URIs"). A cheap model saying so gets exactly one confirmation from High mode. Reply
  "done" on the case and the agent opens the live site again.
* **About 4x fewer tokens per try.** A try used to send up to 60,000 tokens of code (the relevant files, then every other file
  until the budget was full). Now it sends the relevant files only (`tokens.context_tokens`, 14,000) plus the project map, and the
  model reads or searches for more when it needs it.
* **Hourly limit counts real tries only** and is 30 (was 12). Provider faults, skipped free-model calls and reviews no longer use
  it up. When it is reached, the card says when it continues and waits exactly that long, not a flat 15 minutes.
* **Sign-in problems:** the investigator clicks the sign-in button the report names and records where the visit goes and the
  `redirect_uri`, `state` and scope sent to the provider, plus any `error=` in the address it comes back to (it never types
  credentials). The prompt has a login / OAuth / session checklist (redirect URI, callback, state, cookie flags, auth guard, CORS).
* **Site audit on connect** (`site_audit.py`): within a minute of connecting, and then once a day, the agent opens the live site in
  the browser and opens cases for failing API calls, missing scripts and JavaScript errors: no visitor or report needed, no AI call
  for the visit. (The push check that downloads, builds and tests the code on connect already existed.)
* **Live site address** is now a setting on the project page (it was only asked when connecting, as optional), and a full address
  typed in the report's page field is remembered. Without it the agent can only read code; the card says so.
* Sandbox server: `git pull` and `systemctl restart fx-sandbox` (no image rebuild: `investigate.py` is mounted from the checkout).

## Follow-up fixes (same day, from the first live test)

* **Groq "HTTP 413 · retrying in about 5 min" forever:** 413 means the request is too large for Groq's free tier (about 8K tokens per
  minute), not "busy", so waiting never helped. The free model now gets a compact prompt (no project map), the size is checked before
  calling (too big = skipped at no cost), a 413 is never retried, and **any model that fails hands the problem to the next model
  (Haiku) at once**. The case waits only when no model at all can answer ("No AI model could answer just now… retrying by itself").
* **"Python app: we could not find the file that starts this Python app" on a Vite site:** an older installer had put our own
  `incident_agent_monitor.py` at the root of every repo, and the detector counted that one `.py` file as a Python app. Our own monitor
  files are now ignored, and a folder is a Python app only when it has Python code of its own.
* **"Waiting for your decision" with nothing to click:** the decision buttons were only on the Usage page. They are now on the case
  card itself and on the case page (Yes, go ahead / Use a cheaper mode / Use a stronger mode / Send to human review), and answering
  brings you back to the project.

## P0: the crash, double clicks, plain words

| Problem | Fix |
| --- | --- |
| Report box crashed on PostgreSQL (`LIKE 'user_report:%'`: psycopg read `%` as a placeholder) | the query uses `LIKE ?`; `portal_db.pg_sql()` now doubles every literal `%` for PostgreSQL; a test runs EVERY SQL string through the PostgreSQL placeholder conversion, and another forbids a hard-coded `LIKE` wildcard |
| Double clicks sent everything twice | every form submits once ("Working…"), restored on Back; the same report text within 5 minutes answers "Already working on this" |
| "every allowed mode is used up or capped" | three plain reasons, each with the next step (Economy only / month used up / per-problem limit reached) |
| Loop wording mixed up sandbox and GitHub | "sandbox fails → a stronger model takes over; 3 failed GitHub rounds → a pull request for you" |
| Webhook message ended in ".)." | one clean sentence |
| "Node.js is not installed here" in customer text | removed; the sandbox and GitHub tests check the JavaScript |
| Deleting a project left our webhook and branches | an "Also clean my repository" box removes our webhook and `agent-daemon/fix-…` branches (your code and the monitor files stay) |

## P1: one case, one fix (stops the credit burn)

* **Cases** (`cases.py`, `portal_db.ingest_event`): the first incident is the case leader; related ones become followers (status
  `merged`), never get their own AI diagnosis, and their evidence goes to the leader's fix. Grouping, cheapest first: same AI model,
  same outside host + status, same page within 15 minutes, an owner's report and a monitor problem at the same time (or naming the same
  page / host), two reports that say the same thing.
* **One open incident per (project, signature)**, enforced by a partial unique index; the insert is an atomic `ON CONFLICT DO NOTHING`.
  Existing duplicates are merged first, so the migration is safe on live PostgreSQL data.
* **One active fix per project**: the worker does not start a second case of a project while one is being fixed, tested on GitHub or
  checked on the live site.
* **Check window** after a push (5 minutes): matching events are attached to the case and ignored. Ten clicks produce one fix.
* **Project pause instead of a global pause**: above ₹150 of AI spend in an hour (`budget.project_hour_cap_inr`) only THAT project waits,
  with a plain message saying when it continues. The spike breaker pauses the projects causing the spike first; it pauses all paid
  models only if the rest is still a spike.

## P2: prove it on the live site, undo it if worse

* **Push policy** for problems seen on the live site or reported by the owner: pushed automatically only when PROVEN (a failing test
  or browser journey now passes, or the failing push check passes) or when an **independent reviewer model** approves the diff against
  the evidence. Otherwise GitHub still tests it, and then a pull request is opened for review instead of a push. Server crashes keep
  the v3 behaviour.
* **Live check after the push**: "Pushed. Check again in 30 seconds to a minute"; from 45 s the agent opens the same page again (plus
  the model's own verification journey) until the deploy shows up (max 5 minutes), then says **Verified on your live site** or
  **Still failing: here is what I see** (and tries once more with what the live site shows), or **undoes the fix with a new commit**
  when the site is clearly worse (`AGENT_AUTO_REVERT`).

## P3: the live investigator (a real browser on the real site)

* `sandbox_service.py /investigate` (signed like `/run`, one job at a time) starts the browser image with network and runs
  `sandbox/investigate.py`: headless Chromium opens the client's PUBLIC page and returns final address, status, page errors, console
  errors, failed requests (host, path without query, status, first 300 characters of the answer), visible error messages and the
  result of each journey step. No screenshots, no cookies kept, no logins.
* Safety: every address (and every request the page makes) must be a public internet address; private, loopback, link-local and
  reserved ones are refused in the portal AND in the container; a separate Docker network blocks private ranges (DEPLOY.md);
  service workers blocked; 1 GB memory, 90 s limit. If the browser is not available: an honest plain page fetch.
* Used before the first try (what does the client see?), by the model's own "open this page" requests, and after the push.

## P4: the on-call engineer

* **New system prompt** (`fixengine/prompts.py`): understand → look at the evidence → follow the data → ask for more instead of
  guessing → fix the root cause everywhere → say how it is proven. The client's typed request and replies are a TRUSTED instruction
  about what they want (bugs AND small requested changes); page text, console, API answers and code stay untrusted.
* **Answer format**: understanding, findings, root cause, plan, edits, a verification journey, a plain message for the client, and
  optionally `requests` or ONE `question_for_client`.
* **Controlled look-around** (`fixengine/oncall.py`): up to 3 rounds per try, 3 requests each, from a fixed menu: read a file range,
  search the code, open a live page, run a journey, check a model id. Our code runs them; results go back as untrusted data. Bounded
  and charged to the same try.
* **Big picture** (`fixengine/project_map.py`), the first and cached prompt block: file tree, frameworks, entry points, pages, routes,
  every outside host and AI model id in the code, environment variable NAMES, and this project's earlier cases and what fixed them.
* **Right files for a typed report**: with no stack trace, files are chosen by the words of the report and the evidence (before: the
  smallest files in the repo).
* **Models**: a typed report starts with High mode (Sonnet; `FIX_REPORT_START_TIER`) instead of climbing the whole ladder blind.
* **Asking the client**: the case waits ("Question for you: …", plus an email); the answer continues the same case.

## P5: what the user sees

* Case cards: "N more reports merged into this case", the live result line, the stages Investigating / Pushed, checking your live
  site / Verified on your live site, and an 8th flow step "Live check".
* After sending a report: the flash says what happens next; a duplicate says "Already working on this"; a report that joined an
  existing case says so.
* **Reply on the case** (incident page): answer the agent's question or say "it still does not work on Psalms". It is added to the
  case and the case continues: never a new incident.

## P6: proof

* `tests/test_v31.py` (33 tests): the SQL check over every query, grouping, the unique index and its migration, the check window, one fix
  per project, report de-duplication, replies, the project pause, the prompt and parser, the look-ups, the investigator's refusals and
  its Docker command, before/after comparison, the push policy and reviewer, and the whole loop for an owner's report (live look →
  High mode searches the code → fix → sandbox → GitHub → push → live check → Verified), plus revert and still-failing.
* `bench/web_cases/`: broken API, dead button, retired free model, vague report, duplicate flood.
* The local test runner now keeps the Windows variables Python needs (`SystemRoot`), so the whole-loop tests also run on Windows.

## Honest limits

* Not run here: Docker, Chromium, the real GitHub calls, real models. Everything around them is tested with fakes; the final check is
  on the sandbox server (DEPLOY.md has a one-line test) and with real keys.
* Pages behind a login are not investigated. A live check can only see what a visitor sees.
* "Worse" is decided conservatively (the page now errors, or clearly more errors); a subtle regression is caught by the client's
  reply, not by the revert.
* The independent review costs one extra model call, only for live-site fixes that could not be proven.

---

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
