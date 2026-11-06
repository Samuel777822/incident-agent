# How to run and test everything on your laptop

Read this top to bottom once. Every command is meant to be copied exactly. Where Windows and Mac/Linux differ, both are shown.

**Never put an API key in a chat, in GitHub, or in any file except the private `.env` described in step 7b.**
If a key is ever pasted somewhere public (a chat, GitHub, a screenshot), delete it in the provider's console and make a new one.

---

## What you are testing, in four layers

| Layer | What it proves | Costs money? | Needs |
|---|---|---|---|
| 1. Unit and whole-loop tests (`pytest`) | the code logic works, with fake models | no | Python (Node and a JDK make more tests run) |
| 2. Docker images | the sandbox can be built | no | Docker |
| 3. Sandbox abuse check | the sandbox really contains bad code | no | Docker |
| 4. The paid benchmark | the real models really fix real bugs, and what it costs | yes, a few rupees to start | API keys + Docker |

Do them in this order. Do not skip to layer 4.

---

## 1. Install the tools (once)

You need: **Python 3.12 or newer**, **Node 22**, **a JDK 21**, **Git**, **Docker Desktop**.

- Windows: install them with their normal installers. Then install **WSL2** and run *everything below inside an Ubuntu WSL terminal* with Docker Desktop's WSL integration turned on (Docker Desktop → Settings → Resources → WSL integration). This avoids path problems. If you do not want WSL, PowerShell works for steps 2-3 but Docker paths can misbehave.
- Mac: `brew install python node openjdk@21 git` and install Docker Desktop.
- Linux: your package manager (`python3`, `nodejs` 22, `openjdk-21-jdk`, `git`) plus Docker Engine.

Check them:

```
python --version      # 3.12 or higher
node --version        # v22 or higher
javac -version        # 21
docker --version
```

On Mac/Linux use `python3` if `python` is not found.

## 2. Unzip and create a clean Python environment

```
cd incident-agent-main
python -m venv .venv
```

Activate it:

- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- Mac/Linux/WSL: `source .venv/bin/activate`

Then:

```
python -m pip install --upgrade pip
python -m pip install -r requirements-test.txt
```

## 3. Layer 1: run the unit and whole-loop tests

```
python -m pytest -q
```

What you should see:

- Lots of passes. Tests that need a tool you do not have (Node, a JDK) say `skipped`: install the tool and run again.
- To see only the new language tests: `python -m pytest tests/test_fixengine_languages.py -q`

If something fails, copy the **last 30 lines of the output** and send them to me. Common causes:

- `No module named ...` → you forgot to activate the environment (step 2).
- A test about `tsc` skipped → install TypeScript globally once: `npm install -g typescript`.
- Windows line-ending problems → run inside WSL.

## 4. Layer 2: build the three sandbox images

Make sure Docker Desktop is running, then:

```
docker build -f sandbox/Dockerfile.python -t fixengine-sandbox-python:1 sandbox
docker build -f sandbox/Dockerfile.node   -t fixengine-sandbox-node:1   sandbox
docker build -f sandbox/Dockerfile.java   -t fixengine-sandbox-java:1   sandbox
```

The first build downloads a few hundred MB. Check: `docker images` should list all three.

## 5. Layer 3: check that the sandbox contains bad code

```
python bench/sandbox_abuse_check.py
```

It runs eight deliberately nasty scripts inside the sandbox (infinite loop, memory hog, too many processes, internet access, reading keys, writing to system folders, looking for the Docker socket, running as root).

- **Every line must say `PASS`.** The last line should be `All contained.`
- If any line says `FAIL`, **stop**. Send me the output. Do not run other people's code until it is fixed.

## 6. Generate the benchmark projects and run the free check

```
python bench/make_all_cases.py
```

This creates 26 cases in `bench/cases/` (Python, Java, JavaScript, TypeScript, static website). Each case is one clean project with exactly one bug. Open `bench/ANSWER_KEY.md` to see every bug and the correct fix. (The cases that are already in the zip were generated on my side; regenerating them on your laptop makes the error messages come from your own machine.)

Now the **free** run. It runs each project in the real Docker sandbox but calls **no AI model**, so it costs nothing:

```
python fixengine_bench.py --dry-run --sandbox docker --per-language 1
```

What you should see for each case: it runs the sandbox (the first run per image is slow), then reports `needs_human` with `no model calls`. That is correct: the point is to prove each language's project is built and tested in Docker. If a case prints a sandbox or Docker error instead, send it to me.

## 7. Layer 4: the paid benchmark (start tiny)

### 7a. Before you spend anything

You have two ways to get models. **OpenRouter is the simplest because one key covers everything.**

**Option A: OpenRouter only (one key).** Your $5 of credit is about Rs 450. Claude Haiku, Sonnet and Opus are all available through it, and the free tier uses a free open model.
1. In your OpenRouter dashboard, **delete any key that was ever pasted into a chat** and create a new one.
2. Give the new key a **credit limit of $5** (or less) in the key settings.
3. Know the free-tier limit: free models (`:free`) allow **20 requests per minute and 50 per day** until you have bought $10 of credit in total. The engine treats a rate-limited free model as "free tier unavailable" and moves on to Haiku, so a benchmark run still works.

**Option B: direct keys.** A Claude key from Anthropic and a Groq key. If both are set they are used before OpenRouter.

Either way, set a spend limit with the provider that equals what you put in.

### 7b. Save the key (one command, once)

```
python setup_env.py
```

It asks for your **new** OpenRouter key. Paste it and press Enter. You will not see it as you type; that is normal. It creates the private `.env` file for you.

(Prefer to do it by hand? Copy `.env.example` to `.env` and paste the key after `OPENROUTER_API_KEY=`.)

From now on the program reads `.env` by itself every time it starts. The file is ignored by git and Docker, so it never gets uploaded. Never paste the key anywhere else, and never send it to anyone, including me.

A real environment variable, if you set one, always beats the file, so Render's environment screen keeps working for production.

(For Option B put `ANTHROPIC_API_KEY` and `GROQ_API_KEY` in the same file.) How the engine picks a provider per tier:

- A direct key for that tier is used if it is set.
- Otherwise OpenRouter is used if `OPENROUTER_API_KEY` is set.
- `FIXENGINE_PROVIDER=openrouter` forces OpenRouter for every tier; `FIXENGINE_PROVIDER=direct` never uses it.
- Model ids are in `fixengine/config.py` under `openrouter_models`. **Check them against https://openrouter.ai/models once**, especially `anthropic/claude-opus-5.5`, and override any wrong one without editing code, for example `export FIXENGINE_OPENROUTER_MODEL_OPUS="vendor/exact-id"`.

### 7c. Run one case per language, without Opus

```
python fixengine_bench.py --paid --per-language 1 --budget 150 --credits 400 --sandbox docker
```

The run stops by itself if it spends Rs 150, and each bug stops at Rs 60. Typical cost for five easy cases is a few rupees. (`--credits 400` just tells the program how much money you have in total, about $4.50 after OpenRouter's purchase fee.)

### 7d. Read the result

For every case it prints one block:

```
[java_easy_typo_variable] pr_opened  Rs 0.4  21.3s  tokens in/out 14200/310
   tries: groq:unusable -> groq:fail -> groq:fail -> haiku:pass
```

- `pr_opened` = the model proposed a fix and the sandbox proved it (tests passed). Nothing is pushed anywhere; the PR is only printed.
- `needs_human` = every allowed attempt failed or a cap stopped it.
- `tries` = which model attempted, in order. `groq` is the free tier, `haiku` is Normal mode, `sonnet` is High mode, `opus` is Extra mode.
- **tokens in/out** are the real numbers. Compare them with the estimates in `fixengine/config.py`. This is the most valuable output of the whole test.

At the end, a summary table shows spend by model, and `bench_report.json` has the full detail.

### 7e. Widen the test, one language at a time

```
python fixengine_bench.py --paid --language java   --budget 200 --credits 300 --sandbox docker
python fixengine_bench.py --paid --language js     --budget 200 --credits 300 --sandbox docker
python fixengine_bench.py --paid --language ts     --budget 200 --credits 300 --sandbox docker
python fixengine_bench.py --paid --language static --budget 200 --credits 300 --sandbox docker
python fixengine_bench.py --paid --language python --budget 200 --credits 300 --sandbox docker
```

Run them one at a time, and look at the cost after each. A single case can also be run by name: `--only java_hard_stale_price_cache`. Then, only after the cheap models have been judged, try Opus by removing `--no-opus`.

### 7f. What "good" looks like (decide your own bar, this is a suggestion)

- Easy bugs fixed by the free model or Haiku, most of the time.
- Hard bugs (`*_hard_*`) allowed to need Sonnet or to end as `needs_human`.
- Nothing ever costing more than the per-bug cap.
- `py_no_tests_nameerror` ends with a PR that clearly says the fix is **not verified**, because that project has no tests.

## 8. Rules for local_unsafe (do not use it with real customers)

`--sandbox local_unsafe` runs the project on your computer with **no isolation**. It exists so the tests can run without Docker. Use it **only** on the sample cases in `bench/cases/`, never on real customer code. Real work always goes through Docker.

## 9. If something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| `Docker is not available on this machine` | Docker Desktop is not running. Start it and retry. |
| The first Docker run is very slow | It is downloading images and packages. Later runs are faster. |
| TypeScript case fails in `install` | No internet during install, or a corporate proxy. Try another network. |
| Java case fails in `build` with a Maven error | The Java image could not reach Maven Central during the install phase. Check your connection. |
| `No AI model is configured yet` | The keys are not set in **this** terminal window. Repeat step 7b. |
| A case stops with a budget message | Working as designed. Raise `--budget` and `--credits` only after the cheap run looked healthy. |
| Windows path errors from Docker | Run everything inside WSL2 (step 1). |

## 10. What I could not check for you

Be honest about the limits before you trust any of this:

- I could not run Docker, so the three images and the abuse check were **never run for real**. Steps 4 and 5 are the first time.
- I had no internet, so npm and Maven downloads (TypeScript install, Maven projects) were never exercised.
- I ran real Node, `tsc` and `javac` outside Docker to prove each sample project passes when clean and fails with its bug, and the existing test suite plus the new tests pass on my side (see the summary I sent with this zip). But no real AI model has seen any of it.
- All prices, success rates and token counts are still estimates until step 7 produces real ones.

## 11. Before real customers use it (the honest checklist)

"Production ready" is not something a zip can promise. These are the things that must be true first:

1. All of layers 1-3 pass on your laptop (tests, images, abuse check).
2. The paid benchmark shows real fix rates and real token counts, and the numbers in `fixengine/config.py` are updated from it.
3. The sandbox runs on a **separate throw-away machine** (a small VPS), never on the machine that holds your keys or database. Render itself cannot run Docker.
4. In the Render environment screen: `FIXENGINE_ENABLED=1`, `FIXENGINE_SANDBOX_MODE=remote`, the sandbox URL and secret, and your provider key(s). **Without `FIXENGINE_ENABLED=1` the older Python-only flow still runs**, and the new pages would promise more than the product does.
5. Provider spend limits are set, the global budget (`FIXENGINE_BUDGET_INR`) is set, and you get the alert emails (send yourself a test).
6. Terms of service and privacy policy say: customer code is sent to AI providers (including OpenRouter and the model vendors), and fixes are attempts, not guarantees.
7. A small private beta (5-10 people) runs for a few weeks before you sell anything, and you read every pull request the agent opens.


---

## Provider diagnostics, dry runs and paid-run safety (added after the first dry run)

**Check the AI providers first (free):** `python -m fixengine.provider_check`
It shows, per mode, which provider and model id the engine would really use, whether the key is accepted, whether the model id exists, and,
for the free Low-effort route only, sends one tiny real request. It never prints a key. Paid routes get no prompt unless you add `--include-paid`.

**`--dry-run` is now genuinely dry.** It sets `FIXENGINE_DRY_RUN=1` before anything loads, so every adapter refuses to make a network call, whatever is in your shell or in
`.env`. Each case still runs the real sandbox baseline in Docker and stops where the model would have been called. Expect `dry_run` for every case.
(Before, the dry run removed keys from the environment and then `.env` put them back, so it could call a provider.)

**`--paid` is required for real calls.** `python fixengine_bench.py` with neither flag does nothing. In a paid run: Opus (Extra) is off unless `--allow-opus`;
the run pauses at `--pause-at` (default Rs 300) so you can decide; `--spent-before N` makes budget and pause apply across several runs; and it stops by itself if the provider
fails every attempt in two cases in a row.

**When something faults,** the run prints a `FAULT:` line per attempt with the provider, model, HTTP status, a safe error category, whether retrying can help, and
the provider's own message (keys are redacted). The run's private database is kept and its path printed, because it is deleted otherwise.

**Do not paste a bare `python -m pytest`:** a `pytest.ini` now limits it to `tests/`.

**OpenRouter free models:** a 404 saying *"No endpoints found matching your data policy"* means your OpenRouter privacy settings block free models that may publish prompts.
Enabling that setting is fine for the synthetic benchmark repos, but do NOT enable it for real customer code. Use a paid model for the Low-effort tier instead
(`FIXENGINE_OPENROUTER_MODEL_GROQ`), or use a Groq key directly.
