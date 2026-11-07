# Auto-fix engine — what was built and how to run it

> **Architecture v3 (Nov 2026):** bugs now also come from the **push guard** (`push_watch.py`): a failing sandbox check on a pushed
> commit opens an incident with `source=push`. For those, the engine resolves the incident with no tries if the branch is already green,
> proves a fix with the identical check (`check_fixed`), sets a ✓ status on the fix commit, and records live stages for the dashboard.
> **Mixed-language repos** are now fully supported: every stack is built and tested (see `detect_profiles` / `run_profile`).
> See ARCHITECTURE.md for the full picture and DEPLOY.md for the sandbox server.


> **Plan v3 adds** HTML/CSS (static sites), JavaScript, TypeScript and Java support, 23 new benchmark cases with an answer key, a sandbox abuse check,
> and fixes to triage and stack-trace reading. **To run and test everything on your laptop, follow `RUN_TESTS.md`.**

Everything lives in `fixengine/` and is **off by default**. The old flow (`diagnose.py` / `patcher.py`) is untouched and still
handles alert-only projects. Turn the engine on with `FIXENGINE_ENABLED=1` on the **worker**.

## How a bug flows

`/ingest` → incident job → `portal_worker` → `Engine.handle_incident`:

1. **Download** the repo tarball into a scratch folder (token decrypted in memory only).
2. **Fingerprint + triage** (free, rules only): class easy / medium / hard.
3. **Baseline run** in the sandbox: do the tests fail today? (Costs no tokens. Tells us if a later pass proves anything.)
4. **Loop** (rebuilt from the ledger every pass, so it survives restarts):
   router picks a mode → guard checks quota/budget/rate → warning if at a warning point → ONE model call (diagnosis + patch as JSON)
   → policy check → apply patch to a scratch copy → sandbox (install → build → tests → smoke) → ledger row.
5. **Pass** → multi-file PR on a new branch (never main). **Stop** → human-review report + email. Never silent.

| File | Plan section | Job |
|---|---|---|
| `config.py` | 5, 6.8 | every price, quota, cap, probability (override with `FIXENGINE_CONFIG_JSON` or `fixengine_config.json`) |
| `router.py` | 6 | expected-cost optimizer + hard rules (free first, Haiku floor, drop-back, caps, user pick, no repeat) |
| `guard.py` | 9 | quotas, packs, global budget B, kill-switch levels, spike breaker, per-user ceiling, rate limits |
| `store.py` | 4.9 | tables: bugs, attempts (the cost ledger), router decisions, grants, admin actions, flags, choices, holds |
| `adapters.py` | 4.5 | Groq + Anthropic adapters (text in, text out, **no tools**), fake adapter for tests |
| `prompts.py`, `repo_context.py` | 6.7, 12 | relevant files only, secret redaction, injection-aware prompt, strict JSON parsing |
| `validator.py` | 4.7 | patch policy (≤3 files, ≤40 lines, no tests/CI/deps/billing/secrets) + verification level |
| `sandbox.py`, `sandbox_service.py`, `sandbox/` | 11 | hardened Docker runs, remote host service, images |
| `orchestrator.py`, `api.py`, `admin_tools.py`, `review.py`, `notify.py`, `ui.py` | 4, 8, 10 | the loop, user choices, admin analysis/approvals, reports, emails, pages |
| `sim.py`, `fixengine_bench.py`, `bench/` | 6.10, 14 | free router simulation; paid test runner with sample 1,250-line repos |

Pages: customers `/usage` (tries left, mode Auto/Ask/Economy, decisions, bug list, request more), admins `/admin/fix`
(spend vs B, kill switches, held requests, pack credit, admin log).

## Environment variables (Render → worker)

| Variable | Meaning |
|---|---|
| `FIXENGINE_ENABLED` | `1` to use the engine for projects in `pr`/`auto` mode |
| `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | model keys. Missing key = that mode is simply unavailable (never an error) |
| `FIXENGINE_BUDGET_INR` / `FIXENGINE_CREDITS_INR` | global budget B and credits you deposited. Test values: 400 / 500 |
| `FIXENGINE_USD_INR` | exchange rate used for cost estimates (default 90) |
| `OPENROUTER_API_KEY` | one key for Claude (Haiku/Sonnet/Opus) and a free open model through OpenRouter. Used for any tier whose direct key (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`) is not set |
| `FIXENGINE_DRY_RUN` | `1` makes every model adapter refuse to call any provider (used by `fixengine_bench.py --dry-run`). Never set it in production |
| `FIXENGINE_PROVIDER` | `auto` (default), `openrouter` (force it for every tier) or `direct` (never use it). Model ids: `openrouter_models` in `fixengine/config.py`, or `FIXENGINE_OPENROUTER_MODEL_<TIER>` |
| `FIXENGINE_SANDBOX_MODE` | `docker` (Docker on this machine), `remote` (recommended on Render), `local_unsafe` (tests only) |
| `FIXENGINE_SANDBOX_URL`, `FIXENGINE_SANDBOX_SECRET` | the sandbox host and the shared signing secret |

**Keys go only in Render's environment screen (or your own shell for the benchmark). Never in code, chat, GitHub or `.env` files you commit.**

## Languages the engine can fix (v3)

| Project | How it is recognised | What the sandbox runs | Counts as "tests prove the fix"? |
|---|---|---|---|
| Python | `.py` files / `requirements.txt` | pip install, compileall, pytest, start-up smoke check | yes, if tests exist |
| JavaScript | `package.json` | `npm install --ignore-scripts` (only if it has dependencies), `npm run build`, `npm test`, `npm start` smoke | yes, if a test script exists |
| TypeScript | `package.json` + `tsconfig.json` + `typescript` dependency | everything above, plus `tsc --noEmit` type-check | yes (type-check + tests) |
| Java (Maven) | `pom.xml` | `mvn compile` (install phase, network), offline compile, `mvn test` | yes, if `src/test` exists |
| Java (Gradle) | `build.gradle(.kts)` **with `gradlew`** | wrapper assemble, offline classes, `gradlew test` | yes, if `src/test` exists |
| Java (plain) | `.java` files, no build file | `javac` everything, then each `*Test.java` that has a `main` | yes, if such tests exist |
| Static site | `.html` files, no other project type | `sandbox/static_check.py` (broken tags, missing files, CSS braces, JS/JSON syntax) and a start-up check | **no**: it is a syntax/structure check only, so the PR says "NOT proven by a test" |

A project inside a sub-folder (for example `frontend/`) is found and run from that folder. When a repo mixes kinds (for example `backend/`
in Python, `frontend/` in TypeScript and a root `index.html`), every kind is found and each one is installed, built and tested in its
own container; the repo is green only when all are green. Known gaps: Gradle without a wrapper, JUnit without a Maven/Gradle build, yarn/pnpm
lock files (npm is used), packages that need install scripts (`--ignore-scripts` is on for safety), and visual or in-browser behaviour.
The model may edit `.py .js .jsx .ts .tsx .mjs .cjs .java .html .htm .css .scss .vue .svelte`; build and check configuration
(`package.json`, `tsconfig.json`, `pom.xml`, `build.gradle`, ESLint/Vite/Webpack configs, lock files, Docker files, CI files) stays off limits so a model can never loosen the checks that judge its own fix.

## Where the sandbox runs

Render web/worker services cannot run Docker containers, so use a small VPS (any ₹300–500/month box with Docker):

```
docker build -f sandbox/Dockerfile.python -t fixengine-sandbox-python:1 sandbox
docker build -f sandbox/Dockerfile.node   -t fixengine-sandbox-node:1   sandbox     # JavaScript, TypeScript and static sites
docker build -f sandbox/Dockerfile.java   -t fixengine-sandbox-java:1   sandbox     # Maven, Gradle wrapper, plain javac
FIXENGINE_SANDBOX_SECRET=<long random> python sandbox_service.py      # behind HTTPS (Caddy/nginx)
```

Each phase runs non-root, read-only root FS, all capabilities dropped, no privilege escalation, 1 GB / 1 CPU / 256 PIDs,
hard timeout, **network only during dependency install**, no secrets, Docker socket never mounted.
Residual risk: dependency install scripts run with network access, so use a throw-away box that holds nothing of value.

## The Rs 500 paid test

1. Buy credits (below). Deposit **exactly Rs 500 worth** and set a provider-side monthly limit to match.
2. `python bench/make_all_cases.py` then `python fixengine_bench.py --dry-run --sandbox local_unsafe` (free wiring check). `bench/ANSWER_KEY.md` lists every planted bug.
3. Real run on a machine with Docker: start small with `python fixengine_bench.py --paid --per-language 1 --budget 150 --credits 200`, then widen (`--language java`, `--language ts`, ...). Full details in `RUN_TESTS.md`.
4. Read the printed **real tokens** per case and compare with `config.py`. Adjust prices/tokens, then add your own real repos to `bench/cases/`.

The run stops by itself at B (Rs 400), each bug stops at its own cap (Rs 60), and credits are prepaid, so Rs 500 is the hard ceiling.

## Not verified (be honest with yourself)

- **Never run against real Docker, the real Anthropic/Groq APIs, real GitHub or PostgreSQL.** Docker argv, HTTP requests/responses, and the
  SQL are unit-tested against fakes and SQLite. Expect small fixes on first contact. The benchmark is how you find them cheaply.
- **Java, TypeScript and static sites are verified only outside Docker** (real Node, tsc and javac runs through the `local_unsafe` runner, plus Docker command plans checked against fakes). The Java image (`Dockerfile.java`, Maven downloads) and the TypeScript install step (`npm install` of `typescript` inside the container) have never run in real Docker.
- The benchmark cases were generated and each was confirmed to fail as intended with its bug and pass without it, but the models' ability to fix them is **unmeasured** until you run the paid test.
- **All prices, success probabilities and token counts are the plan's estimates.** Verify model names/prices on the provider pages.
- Prices follow plan v2 (section 1 and 5.6): Rs 200 a month, Rs 1,500 a year, set once in `plans.py` and used by the billing page, pricing page, terms, chatbot and payment checks. The plan's worst-case provider cost for a full app (about Rs 160 a month) now sits under the monthly price; confirm it with the measured numbers from the paid test.
- Pack payment: admin credits a pack after confirming the Rs 100 UPI payment (existing manual flow). Not instant.

## Deliberate differences from the plan

- One model call per try returns diagnosis **and** patch (the old flow used two calls).
- Router success odds shrink by `repeat_decay` (0.7) for each earlier failure of the same mode (matches the plan's own walk-through).
- If the optimizer decides giving up is cheaper than another try, the bug ends in human review with an email and report.
- Every fix remains an open pull request for human review. The PR shows whether the sandbox reproduced and fixed the failure and whether GitHub checks passed.
- Dependency manifests (`requirements.txt`, `package.json`, lock files) cannot be edited by the model (supply-chain risk).
- Three pre-existing problems found, not changed: `render.yaml` assumes a separate worker while `CODEX_INSTRUCTIONS.md` says free-tier built-in worker;
  the old flow already sends code to Groq (consent is recorded in `ai_consent_at`; the consent text and the privacy policy now name all AI providers).
- Plan sections 11 and 15 (several projects per account, limits per account) were followed over section 14 (one project for now); the quota guard already counts per user, so more projects cannot multiply cost.
