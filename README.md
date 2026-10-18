# AI On-Call Engineer (incident-agent)

When a production app starts throwing the same error again and again, this agent finds the cause,
asks an LLM for a fix, tests the fix, and opens a pull request. A human reviews and clicks **Merge**.

The demo patient is [shop-api](https://github.com/pranavvrao1-ai/shop-api), a small store app that can be
broken and repaired on demand.

## How it works

1. **Read the log.** The app writes one JSON line per error (`ts`, `level`, `service`, `message`, `traceback`).
   The agent reads only the new lines since its last pass (a byte bookmark in `log_offsets.json`).
2. **Group into incidents.** Each error gets a signature: the exception type plus the file and line of the last
   application frame in the traceback (for example `KeyError:main.py:81`). Errors with the same signature join the same
   open incident in a SQLite database (`incidents.db`).
3. **Collect evidence.** It pulls the latest commit of the configured branch and gathers the repository files and the
   git history. The amount is capped so the request fits the free Groq tier.
4. **Diagnose.** An LLM (Groq, `openai/gpt-oss-120b`) returns a category, a confidence level, the root cause,
   whether the bug is still present in the current code, whether it is safe to auto-fix, and a plain-language report.
5. **Patch and test.** If every safety rule below passes, the agent asks the model for a minimal find-and-replace
   patch, applies it on a new branch `fix/incident-<id>`, and runs the test suite before and after.
6. **Open a pull request.** If the tests pass after the patch, it pushes the branch and opens a PR with the root cause,
   the fix and the test result. In `pr` mode a human merges it.

## Safety rules

The agent only attempts a fix when **all** of these hold:

- the diagnosis category is `code_bug`
- the bug is confirmed still present in the current code
- the confidence is `high` and the model marked the fix as safe to auto-fix
- the patch touches exactly one `.py` file, never a test file, and changes at most 20 lines
- the tests pass after the patch (a failing suite means no PR)

Other guards:

- At most 2 fix attempts per incident, then the status becomes `needs_human`.
- Tests run in an environment with the API keys removed.
- The GitHub token is masked in error messages.
- Each repository has a mode in `repos.json`:
  - `report`: diagnose only, never change code
  - `pr`: open a pull request and wait for a human to merge (recommended)
  - `auto`: merge by itself, but only if the tests failed before the patch and pass after it

Incident statuses: `diagnosing`, `diagnosed`, `pr_opened`, `resolved`, `needs_human`.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file next to the code (it is git-ignored, never commit it):

```
GROQ_API_KEY=your-groq-key
GITHUB_TOKEN=your-github-token
LOG_PATH_SHOP_API=/absolute/path/to/shop-api/logs/app.log
```

- `GROQ_API_KEY`: a free key from console.groq.com.
- `GITHUB_TOKEN`: a fine-grained token limited to the target repository, with **Contents: read and write** and
  **Pull requests: read and write** (a classic token needs the `repo` scope).
- `LOG_PATH_<SERVICE>` is optional and overrides `log_path` in `repos.json`. The service name is upper-cased with
  dashes turned into underscores.

Register a service in `repos.json` (or run `python add_repo.py`):

```json
{
  "shop-api": {
    "url": "https://github.com/pranavvrao1-ai/shop-api.git",
    "branch": "main",
    "test_command": "pytest",
    "mode": "pr",
    "log_path": "../shop-api/logs/app.log"
  }
}
```

The key must match the `service` field in the app's log lines.

## Run

```bash
python workflows.py --run shop-api      # one full pass: ingest, diagnose, patch, test, PR
python agent_daemon.py shop-api 10      # keep watching, check every 10 seconds
python resolve.py <incident id>         # manual alternative (the daemon resolves merged PRs by itself)```

Run the agent with a Python environment that can also run the target repository's tests (for shop-api:
fastapi, httpx and pytest), because the tests run with the same interpreter.

## Demo with shop-api

1. Start the shop-api server and its traffic generator.
2. Break the app (the demo button, or `break.py`): the bug is committed to the repository and checkout starts failing.
3. The agent sees the errors, diagnoses the cause, patches, tests, and opens a pull request.
4. Review the diff and merge. Restore the demo with `reset.py`.

The shop-api dashboard (`/dashboard`) reads `incidents.db` read-only and shows each incident's status,
root cause and a link to the pull request. Point it at the database with the `INCIDENTS_DB` environment variable.

To reset a demo, stop the agent and delete `incidents.db` and `log_offsets.json` together.

## Files

| File | Purpose |
|---|---|
| `sync_and_tail.py` | pulls the repo, reads new log lines, groups errors into incidents |
| `db.py`, `schema.sql` | SQLite storage for log events, incidents and fixes |
| `evidence.py`, `git_evidence.py`, `repo_sync.py` | clone the repo and collect files and git history |
| `diagnose.py`, `run_diagnosis.py` | LLM diagnosis and the saved report |
| `patcher.py`, `autofix.py` | patch generation, safety checks and the fix workflow |
| `tester.py` | runs the test command with secrets removed |
| `pr.py` | creates the branch, pushes it and opens the pull request |
| `workflows.py`, `agent_daemon.py` | run the pipeline once or continuously |
| `resolve_merged.py` | marks an incident resolved automatically once its pull request is merged |
## Known limitations

An incident is created on the first error that has a signature. The daemon waits for at least 5 errors and 30 seconds before it diagnoses, but there is no sliding "N errors in M seconds" window.- A merge is detected by polling GitHub, so an incident is marked resolved a few seconds after the merge.
- The agent reads the log from a file on the same machine as the agent.
- A diagnosis uses roughly 9,000 Groq tokens, and the free tier has per-minute limits. If a call fails, the incident
  stays `diagnosing` and is retried by the daemon.
- Fixes are limited to a single `.py` file and a small find-and-replace edit.
