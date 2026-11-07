# Verification report

## Scope and baseline

The supplied `incident-agent-main-monitoring-v2.zip` was compared file-by-file with
`Samuel777822/incident-agent` at `main`, commit `037bf153e166f651993f87f54c123f3e471c89ee`.
Both contained 885 files; every file hash matched, with no missing, extra, or differing files. The repair therefore starts
from the exact GitHub `main` snapshot.

## Changes

- Disabled automated pull-request merges in the installer and remediation worker. Legacy arguments and database helpers
  remain as compatibility shims, but they cannot merge a pull request. Customer-facing text and the setup guide now say
  changes remain open for human review.
- Added Java monitoring for conventional Maven/Gradle modules with a `public static void main` entry point. The generated
  helper reports uncaught exceptions and sends a heartbeat every 30 seconds with project-scoped credentials.
- Added Java detection/wiring coverage and a JDK-gated compile/runtime integration test.
- Updated the release checklist so current test results and environment limits are explicit.

## Checks performed

- Focused regression tests: **129 passed, 2 skipped** across `tests/test_github.py`, `tests/test_portal_flows.py`,
  `tests/test_monitoring_v2.py`, and `tests/test_web_app.py`. The skipped checks require a Java JDK and Playwright/Chromium,
  neither of which is available in this environment.
- Python `compileall`: passed.
- `git diff --check`: passed before packaging.
- Live heartbeat integration: the Python monitor ran for 186 seconds against the local portal and stored seven heartbeat
  records. Intervals were 30, 30, 30, 30, 31, and 30 seconds.
- Credential pattern scan: no high-confidence provider/API token patterns were found in 94 runtime source files.
- The previous full-suite attempt, before later test-expectation and embedded-runtime fixes, reported **354 passed,
  4 skipped, 22 failed**. It was not repeated after those fixes. Local sandbox tests that need a POSIX shell cannot run
  because Git for Windows `sh.exe` exits with access denied in this managed environment. The focused suite above was run
  after the functional fixes.

## Limits

The Java integration test was added but could not execute locally without a JDK. Browser integration was skipped because
Playwright/Chromium was unavailable. Docker, PostgreSQL, and live AI-provider credentials were also unavailable. No claim
of a full-suite pass is made; the repository's GitHub Actions run on the pull request is the next full Linux validation.

## Review branch

Branch: `codex/reviewable-safety-java-monitor` (based on the verified `main` commit above). The change is intended to remain
an open pull request for human review; no pull request is merged automatically.
