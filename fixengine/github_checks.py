"""v6: GitHub Actions as the test sandbox.

Instead of our own sandbox server (Rs 500-600 a month, one job at a time, a disk that filled up), the customer's code is installed,
built and tested on GitHub's own machines, in the customer's repository, by a small workflow we generate from the stack we detect.
Measured on Bible-Well: about 30 seconds from push to results. Our servers never run customer code in this mode.

* The workflow (`.github/workflows/agent-daemon-check.yml`, first line `# agent-daemon-check v3`) runs ONLY on Agent Daemon's
  branches (`agent-daemon/**`), with read-only permissions and no secrets. Every step keeps going after a failure, so one run
  reports everything at once.
* Each step writes its exit code and log; a last step turns them into `results.json` (uploaded as artifact "agent-daemon-facts"):
  which steps ran, passed or failed, how long they took, the end of their output, and whether any test really ran.
* Lint is reported but never fails a check (projects often have old lint problems; Bible-Well had 29).
"""
from __future__ import annotations

import io
import json
import re
import shlex
import zipfile

WORKFLOW_PATH = ".github/workflows/agent-daemon-check.yml"
WORKFLOW_NAME = "agent-daemon check"
ARTIFACT = "agent-daemon-facts"
VERSION = 3
HEADER = f"# agent-daemon-check v{VERSION}"
CHECK_BRANCH_PREFIX = "agent-daemon/check-"

FACTS_SCRIPT = r'''
import glob, json, os
steps = []
for rc_path in sorted(glob.glob("ad-facts/*.rc"), key=lambda p: (os.path.getmtime(p), p)):   # the order the steps ran
    key = os.path.basename(rc_path)[:-3]
    stack, _, name = key.partition("__")
    rc = int((open(rc_path).read().strip() or "1"))
    secs = 0
    try:
        secs = int(open(f"ad-facts/{key}.secs").read().strip() or 0)
    except OSError:
        pass
    try:
        tail = open(f"ad-facts/{key}.log", errors="replace").read()[-6000:]
    except OSError:
        tail = ""
    steps.append({"stack": stack, "name": name, "rc": rc, "seconds": secs, "tail": tail})
json.dump({"version": 3, "steps": steps}, open("ad-facts/results.json", "w"))
print(json.dumps([(s["stack"], s["name"], s["rc"]) for s in steps]))
'''


def _q(s: str) -> str:
    return shlex.quote(s)


def _stack_steps(part, index: int) -> list[str]:
    """YAML step blocks (as text) for one stack: setup, then install / build / lint / test, each recorded."""
    lang = getattr(part, "language", "none")
    wd = getattr(part, "workdir", "") or "."
    key = f"s{index}-{lang}"
    blocks: list[str] = []
    if lang == "node":
        blocks.append(f"""      - uses: actions/setup-node@v4
        with:
          node-version: "20"
""")
        install = "if [ -f package-lock.json ]; then npm ci --no-audit --no-fund || npm install --no-audit --no-fund; else npm install --no-audit --no-fund; fi"
        cmds = [("install", install), ("build", part.build or ""),
                ("lint", "if node -e \"process.exit(((require('./package.json').scripts||{}).lint)?0:1)\"; then npm run lint --silent; else exit 0; fi"),
                ("test", part.test or "")]
    elif lang == "python":
        blocks.append(f"""      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
""")
        install = "python -m pip install --upgrade pip && if [ -f requirements.txt ]; then pip install -r requirements.txt; fi && pip install pytest"
        test = (part.test or "").replace(" -p no:cacheprovider", "")
        cmds = [("install", install), ("build", "python -m compileall -q -x '(\\.venv|venv|node_modules)' ."), ("test", test)]
    elif lang == "java":
        blocks.append(f"""      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
""")
        build = part.build or ""
        test = part.test or ""
        if "mvn" in build:
            build, test = "mvn -q -B -DskipTests compile", ("mvn -B test" if test else "")
        elif "gradlew" in build:
            build, test = "sh gradlew --no-daemon -q classes", ("sh gradlew --no-daemon -q test" if test else "")
        cmds = [("build", build), ("test", test)]
    else:
        return []                      # a static site has no build or tests here: the browser check looks at it
    for name, cmd in cmds:
        if not cmd:
            continue
        rec = f"ad-facts/{key}__{name}"
        blocks.append(f"""      - name: "{key} {name}"
        continue-on-error: true
        shell: bash
        run: |
          set +e
          mkdir -p "$GITHUB_WORKSPACE/ad-facts"
          cd {_q(wd)}
          start=$(date +%s)
          bash -c {_q(cmd)} > "$GITHUB_WORKSPACE/{rec}.log" 2>&1
          echo $? > "$GITHUB_WORKSPACE/{rec}.rc"
          echo $(( $(date +%s) - start )) > "$GITHUB_WORKSPACE/{rec}.secs"
          tail -40 "$GITHUB_WORKSPACE/{rec}.log"
""")
    return blocks


def workflow_source(profile) -> str:
    """The check workflow for this project's stack(s)."""
    parts = list(getattr(profile, "parts", None) or [profile])
    steps = "".join("".join(_stack_steps(p, i)) for i, p in enumerate(parts))
    facts = FACTS_SCRIPT.strip().replace("\n", "\n          ")
    return f"""{HEADER}
# Added by Agent Daemon. Runs ONLY on Agent Daemon's own branches (agent-daemon/...): it installs, builds and tests your app on
# GitHub's machines so a fix is checked before it reaches your branch. Read-only, no secrets, and it never runs on your own pushes.
name: {WORKFLOW_NAME}
on:
  push:
    branches: ["agent-daemon/**"]
permissions:
  contents: read
concurrency:
  group: agent-daemon-check-${{{{ github.ref }}}}
  cancel-in-progress: true
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1
{steps}      - name: facts
        if: always()
        shell: bash
        run: |
          mkdir -p ad-facts
          python3 - <<'PY'
          {facts}
          PY
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: {ARTIFACT}
          path: ad-facts/results.json
          retention-days: 1
          if-no-files-found: ignore
"""


def is_current(text: str | None) -> bool:
    m = re.match(r"# agent-daemon-check v(\d+)", str(text or ""))
    return bool(m) and int(m.group(1)) >= VERSION


def read_facts(zip_bytes: bytes) -> dict | None:
    """results.json from the artifact zip, or None."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            return json.loads(z.read("results.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None


def to_result(facts: dict):
    """results.json -> SandboxResult. Passed only when every build/test step that ran passed (lint never fails a check); tests_ran
    only when a test step really ran. Nothing ran at all = not passed and not tested (never counted as green)."""
    from . import sandbox
    steps = list((facts or {}).get("steps") or [])
    phases = [sandbox.PhaseResult(f"{s['stack']}: {s['name']}" if len(steps) > 1 else s["name"], int(s["rc"]) == 0, int(s["rc"]),
                                  float(s.get("seconds") or 0), str(s.get("tail") or "")[-6000:]) for s in steps]
    gating = [s for s in steps if s["name"] != "lint"]
    res = sandbox.SandboxResult()
    res.phases = phases
    res.tests_ran = any(s["name"] == "test" for s in steps)
    res.passed = bool(gating) and all(int(s["rc"]) == 0 for s in gating)
    failed = [s for s in gating if int(s["rc"]) != 0]
    res.output = ("\n\n".join(f"[{s['stack']} {s['name']}] exit {s['rc']}\n{str(s.get('tail') or '')[-2500:]}" for s in failed)
                  if failed else ("all checks passed on GitHub" if gating else "nothing could be built or tested on GitHub"))[-6000:]
    test_logs = "\n".join(str(s.get("tail") or "") for s in steps if s["name"] == "test")
    res.failing = sandbox.parse_failing(test_logs) if res.tests_ran else None
    if res.tests_ran and res.passed and res.failing is None:
        res.failing = 0
    if not res.passed and not res.failing:
        res.failing = None             # red because of install/build: never report "0 failing" for a red repo
    return res


def nothing_ran(facts: dict | None) -> bool:
    """True when our facts exist and show no build and no test ran: such a green check proves nothing."""
    if not facts:
        return False
    return not any(s["name"] in ("build", "test") for s in facts.get("steps") or [])
