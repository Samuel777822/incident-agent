"""Sandbox runners (plan section 11). The validator never trusts a model: it runs install, build, tests and a smoke check.

Modes (config sandbox.mode):
  docker       docker CLI on THIS machine (needs Docker; Render web services cannot do this)
  remote       POST the repo to sandbox_service.py running on a small VPS that has Docker
  local_unsafe runs commands directly on this machine. TESTS/DEV ONLY and only with FIXENGINE_ALLOW_UNSAFE_LOCAL=1

Containers: non-root, read-only root filesystem, no capabilities, no privilege escalation, memory/CPU/PID limits,
a hard timeout, and NO network except during the dependency-install phase. No secrets are ever passed in.
The Docker socket is never mounted into anything.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

SMOKE_PORT = 8765
SMOKE_WAIT = 25


@dataclass
class Profile:
    language: str = "python"            # python | node | java | static | none   (TypeScript projects are "node")
    workdir: str = ""                   # sub-folder holding the project when it is not at the repo root (e.g. "frontend")
    install: str | None = None
    build: str | None = None
    test: str | None = None
    smoke: str | None = None
    has_tests: bool = False
    notes: list = field(default_factory=list)


@dataclass
class PhaseResult:
    name: str
    ok: bool
    rc: int
    seconds: float
    output: str


@dataclass
class SandboxResult:
    passed: bool = False
    phases: list = field(default_factory=list)
    tests_ran: bool = False
    smoke_ran: bool = False
    failing: int | None = None
    output: str = ""
    timed_out: bool = False
    system_fault: bool = False
    error: str = ""

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SandboxResult":
        phases = [PhaseResult(**p) for p in d.get("phases", [])]
        known = {k: v for k, v in d.items() if k != "phases" and k in SandboxResult.__dataclass_fields__}
        return SandboxResult(phases=phases, **known)


# ---- profile detection -----------------------------------------------------------------------------------------
def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_SKIP = {"node_modules", ".git", ".fx_deps", ".fx_out", ".fx_m2", ".fx_gradle", "__pycache__", ".venv", "venv", "dist", "build",
         "target", ".next", ".idea", ".gradle", "coverage"}
_PREFERRED_SUBDIRS = ("backend", "server", "api", "app", "src", "web", "frontend", "client", "site", "public")
_SITE_DIRS = ("", "public", "docs", "site", "static", "www", "src", "web", "dist")


def _walk_names(root: Path) -> set[str]:
    names: set[str] = set()
    if not root.is_dir():
        return names
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP]
        for n in filenames:
            names.add((Path(dirpath) / n).relative_to(root).as_posix())
    return names


def _under(names: set[str], base: str) -> set[str]:
    prefix = f"{base}/" if base else ""
    return {n[len(prefix):] for n in names if n.startswith(prefix)}


def _node_profile(root: Path, names: set[str], base: str) -> Profile:
    """names are relative to the project folder `base`."""
    prof = Profile(language="node", workdir=base)
    pkg = _read(root, f"{base}/package.json" if base else "package.json")
    try:
        data = json.loads(pkg) if pkg else {}
    except ValueError:
        data = {}
    scripts = data.get("scripts") or {}
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    lock = "package-lock.json" in names
    if deps:                                  # nothing to download for a dependency-free project (no network is needed then)
        prof.install = ("npm ci" if lock else "npm install") + " --ignore-scripts --no-audit --no-fund"
    if "yarn.lock" in names or "pnpm-lock.yaml" in names:
        prof.notes.append("yarn/pnpm lock files are ignored: dependencies are installed with npm")
    typed = "tsconfig.json" in names and ("typescript" in deps or any(n.endswith((".ts", ".tsx")) for n in names))
    build_script = str(scripts.get("build", ""))
    steps = []
    if typed and "typescript" in deps:
        steps.append("npx --no-install tsc --noEmit")          # type-check even if the project's own build script does not
    elif typed:
        prof.notes.append("tsconfig.json found but typescript is not a dependency: type errors cannot be checked")
    if build_script and not (steps and "tsc" in build_script):
        steps.append("npm run build --silent")
    if steps:
        prof.build = " && ".join(steps)
    test = str(scripts.get("test", ""))
    if test and "no test specified" not in test:
        prof.test, prof.has_tests = "npm test --silent", True
    if "start" in scripts:
        prof.smoke = "npm start"
    return prof


def _java_profile(root: Path, names: set[str], base: str) -> Profile:
    prof = Profile(language="java", workdir=base)
    javas = sorted(n for n in names if n.endswith(".java"))
    if "pom.xml" in names:
        m2 = '-Dmaven.repo.local="$PWD/.fx_m2"'
        prof.install = f"mvn -q -B {m2} -DskipTests compile"          # downloads plugins and dependencies (network phase only)
        prof.build = f"mvn -q -B -o {m2} -DskipTests compile"
        if any("/test/" in f"/{n}" and n.endswith(".java") for n in javas):
            prof.test, prof.has_tests = f"mvn -B -o {m2} test", True
        return prof
    if "build.gradle" in names or "build.gradle.kts" in names:
        env = 'GRADLE_USER_HOME="$PWD/.fx_gradle"'
        if "gradlew" not in names:
            prof.notes.append("Gradle project without gradlew: add the Gradle wrapper so it can be built here")
            return prof
        prof.install = f"{env} sh gradlew --no-daemon -q assemble -x test"
        prof.build = f"{env} sh gradlew --no-daemon --offline -q classes"
        if any("/test/" in f"/{n}" and n.endswith(".java") for n in javas):
            prof.test, prof.has_tests = f"{env} sh gradlew --no-daemon --offline -q test", True
        return prof
    # plain javac project
    prof.build = ("find . -name '*.java' -not -path './.fx_*' > .fx_srcs.txt && mkdir -p .fx_out "
                  "&& javac -encoding UTF-8 -Xlint:none -d .fx_out @.fx_srcs.txt")
    runners = []
    for n in javas:
        if not re.search(r"(?:Tests?\.java$|(?:^|/)Test[A-Z]\w*\.java$)", n):
            continue
        text = _read(root, f"{base}/{n}" if base else n)
        if "org.junit" in text:
            prof.notes.append(f"{n} uses JUnit: add a pom.xml or Gradle build so the JUnit library can be downloaded")
            continue
        if re.search(r"static\s+void\s+main\s*\(", text):
            pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
            cls = (pkg.group(1) + "." if pkg else "") + Path(n).stem
            runners.append(f"java -cp .fx_out {cls}")
    if runners:
        prof.test, prof.has_tests = " && ".join(runners), True
    return prof


def _static_profile(root: Path, names: set[str], base: str, exclude: list[str] | None = None) -> Profile | None:
    exclude = [e for e in (exclude or []) if e]
    if exclude:
        names = {n for n in names if not any(n == e or n.startswith(e + "/") for e in exclude)}
    htmls = sorted(n for n in names if n.lower().endswith((".html", ".htm")))
    if not htmls:
        return None
    site = ""
    for d in _SITE_DIRS:
        key = f"{d}/index.html" if d else "index.html"
        if key in names:
            site = d
            break
    else:
        site = str(Path(htmls[0]).parent.as_posix()).replace(".", "") if "/" in htmls[0] else ""
    prof = Profile(language="static", workdir=base)
    root_arg = f"--site-root {shlex.quote(site)}" if site else ""
    excl = " ".join(f"--exclude {shlex.quote(e)}" for e in exclude)
    prof.build = " ".join(part for part in (f"python3 /opt/static_check.py . {root_arg}".strip(), excl) if part)
    if (f"{site}/index.html" if site else "index.html") in names:
        prof.smoke = (f"cd {shlex.quote(site)} && " if site else "") + "python3 -m http.server $PORT"
    return prof


def detect_profile(root: Path, files: dict[str, str] | None = None) -> Profile:
    """Work out how to install, build, test and start a project. Supports Python, Node (JavaScript and TypeScript),
    Java (Maven, Gradle wrapper or plain javac) and static HTML/CSS/JS sites. A project in a sub-folder is found too."""
    root = Path(root)
    all_names = _walk_names(root) | (set(files) if files else set())
    folders = [""] + [d for d in _PREFERRED_SUBDIRS if any(n.startswith(d + "/") for n in all_names)]
    others = sorted({n.split("/", 1)[0] for n in all_names if "/" in n} - set(folders) - _SKIP)
    for base in folders + others:
        names = _under(all_names, base)
        top = {n for n in names if "/" not in n}
        found: Profile | None = None
        if "pom.xml" in top or "build.gradle" in top or "build.gradle.kts" in top:
            found = _java_profile(root, names, base)
        elif "package.json" in top and not (base == "" and any(n.endswith(".py") for n in top)):
            found = _node_profile(root, names, base)
        elif any(n.endswith(".py") for n in top) or ("requirements.txt" in top) or ("pyproject.toml" in top and any(n.endswith(".py") for n in names)):
            found = _python_profile(root, names, base)
        elif base == "" and any(n.endswith(".java") for n in names):
            found = _java_profile(root, names, base)
        elif base == "" and any(n.endswith((".ts", ".tsx", ".js", ".mjs")) for n in top) and "package.json" not in top:
            found = _static_profile(root, names, base)                 # loose JS files next to HTML
        if found is None and base == "":
            found = _static_profile(root, names, base)
        if found is not None and found.language != "none":
            if base:
                found.notes.append(f"project found in the '{base}' folder")
            other_kinds = sorted({k for k, hit in (("Node", "package.json" in all_names or any(n.endswith("/package.json") for n in all_names)),
                                                   ("Python", any(n.endswith(".py") for n in all_names)),
                                                   ("Java", any(n.endswith(".java") for n in all_names))) if hit}
                                 - {{"node": "Node", "python": "Python", "java": "Java"}.get(found.language, "")})
            if other_kinds:
                found.notes.append("this repo also contains " + ", ".join(other_kinds) + ": only the main project is built and tested")
            return found
    prof = Profile(language="none")
    prof.notes.append("no supported project detected (Python, Node/TypeScript, Java, or a static HTML site)")
    return prof


STACK_LABEL = {"python": "Python", "node": "JavaScript/TypeScript", "java": "Java", "static": "HTML/CSS/JS site"}
MAX_STACKS = 4


def stack_label(profile: Profile) -> str:
    """'Python (backend)' / 'JavaScript/TypeScript (frontend)' / 'HTML/CSS/JS site'."""
    name = STACK_LABEL.get(profile.language, profile.language)
    if profile.language == "node" and "tsc" in (profile.build or ""):
        name = "TypeScript"
    return f"{name} ({profile.workdir})" if profile.workdir else name


@dataclass
class StackSet:
    """Several projects that live in one repository (for example a Python API, a React frontend and a static landing page).

    Every stack is installed, built and tested on its own, in its own fresh container, and the repo only counts as healthy
    when ALL of them pass. It quacks like a Profile where the engine needs it (has_tests, language, notes)."""
    parts: list = field(default_factory=list)

    @property
    def has_tests(self) -> bool:
        return any(p.has_tests for p in self.parts)

    @property
    def language(self) -> str:
        return "+".join(p.language for p in self.parts) or "none"

    @property
    def workdir(self) -> str:
        return ""

    @property
    def notes(self) -> list:
        out = [f"{len(self.parts)} projects found in this repo: " + ", ".join(stack_label(p) for p in self.parts)
               + ". Each one is built and tested; the repo passes only when all of them pass."]
        for p in self.parts:
            out += [n for n in p.notes if "only the main project" not in n]
        return out

    def labels(self) -> list[str]:
        return [stack_label(p) for p in self.parts]


def _covered(claimed: list[str], base: str) -> bool:
    return any(b == "" or base == b or base.startswith(b + "/") for b in claimed)


def detect_profiles(root: Path, files: dict[str, str] | None = None):
    """Every runnable project in the repo, not just the main one.

    Returns a single Profile for an ordinary one-language repo (exactly what detect_profile returns), or a StackSet when the
    repo mixes languages: e.g. backend/ in Python + frontend/ in TypeScript + a root index.html, or a Java service next to a
    Node app. Each stack is found by its own marker file (package.json, pom.xml/build.gradle, requirements.txt/pyproject.toml
    or .py files, .html files) at the repo root or one/two folders deep."""
    root = Path(root)
    all_names = _walk_names(root) | (set(files) if files else set())
    dirs = {""}
    for n in all_names:
        parts = n.split("/")[:-1]
        for depth in range(1, min(len(parts), 2) + 1):
            if not (set(parts[:depth]) & _SKIP):
                dirs.add("/".join(parts[:depth]))
    claimed: dict[str, list[str]] = {"java": [], "node": [], "python": []}
    stacks: list[Profile] = []
    for base in sorted(dirs, key=lambda d: (d.count("/") + (1 if d else 0), d)):
        names = _under(all_names, base)
        top = {n for n in names if "/" not in n}
        if ("pom.xml" in top or "build.gradle" in top or "build.gradle.kts" in top) and not _covered(claimed["java"], base):
            stacks.append(_java_profile(root, names, base)); claimed["java"].append(base)
        if "package.json" in top and not _covered(claimed["node"], base):
            stacks.append(_node_profile(root, names, base)); claimed["node"].append(base)
        py_marker = bool({"requirements.txt", "pyproject.toml", "setup.py"} & top)
        py_files = any(n.endswith(".py") for n in top) and base.count("/") == 0
        if (py_marker or py_files) and not _covered(claimed["python"], base) and not _covered(claimed["java"], base):
            stacks.append(_python_profile(root, names, base)); claimed["python"].append(base)
    if not claimed["java"] and any(n.endswith(".java") for n in all_names):
        stacks.append(_java_profile(root, all_names, "")); claimed["java"].append("")
    # Plain HTML/CSS/JS that is not part of a Node/Java project and is not a server-side template folder.
    code_bases = claimed["node"] + claimed["java"]
    loose = [n for n in all_names if n.lower().endswith((".html", ".htm")) and not _covered(code_bases, n)
             and "templates" not in n.split("/")[:-1]]
    if loose:
        root_taken = "" in claimed["node"] + claimed["java"] + claimed["python"]
        if not root_taken:
            others = sorted({b for b in claimed["node"] + claimed["java"] + claimed["python"] if b})
            prof = _static_profile(root, all_names, "", exclude=others)
            if prof is not None:
                stacks.append(prof)
        else:
            groups = sorted({n.split("/", 1)[0] for n in loose if "/" in n} - set(claimed["python"]) - set(code_bases))
            for g in groups[:1]:
                prof = _static_profile(root, _under(all_names, g), g)
                if prof is not None:
                    stacks.append(prof)
    stacks = [s for s in stacks if s.language != "none" and (s.install or s.build or s.test or s.smoke)]
    if len(stacks) <= 1:
        return detect_profile(root, files)
    return StackSet(parts=stacks[:MAX_STACKS])


def _combine(results: list[tuple[Profile, "SandboxResult"]]) -> "SandboxResult":
    out = SandboxResult()
    for prof, res in results:
        label = stack_label(prof)
        out.phases += [PhaseResult(f"{label}: {p.name}", p.ok, p.rc, p.seconds, p.output) for p in res.phases]
    out.passed = all(r.passed for _, r in results)
    out.tests_ran = any(r.tests_ran for _, r in results)
    out.smoke_ran = any(r.smoke_ran for _, r in results)
    out.timed_out = any(r.timed_out for _, r in results)
    # Failing-test count across stacks. A stack that failed without a countable test failure (install, build, type-check,
    # site check) makes the count unknown unless another stack reported real failing tests: never report 0 for a red repo.
    known = sum(r.failing for _, r in results if r.failing)
    unknown = any(not r.passed and not r.failing for _, r in results)
    if known:
        out.failing = known
    elif unknown:
        out.failing = None
    else:
        counts = [r.failing for _, r in results if r.failing is not None]
        out.failing = 0 if counts else None
    failed = [(p, r) for p, r in results if not r.passed]
    if failed:
        out.output = "\n\n".join(f"[{stack_label(p)}] {r.output}" for p, r in failed)[-4000:]
    else:
        out.output = "all stacks passed: " + ", ".join(stack_label(p) for p, _ in results)
    return out


def run_profile(runner, root: Path, profile) -> "SandboxResult":
    """Run one Profile, or every stack of a StackSet, each in its own fresh sandbox, and merge the results."""
    if not isinstance(profile, StackSet):
        return runner.run(root, profile)
    results = []
    for part in profile.parts:
        res = runner.run(root, part)
        if res.system_fault:
            return res
        results.append((part, res))
    return _combine(results)


def stack_summary(profile, result: "SandboxResult | None" = None) -> list[dict]:
    """[{label, language, ok, phase}] for the dashboard: which stack passed and where it broke."""
    parts = profile.parts if isinstance(profile, StackSet) else [profile]
    rows = []
    for part in parts:
        label = stack_label(part)
        row = {"label": label, "language": part.language, "ok": None, "phase": ""}
        if result is not None:
            mine = [p for p in result.phases if p.name.startswith(label + ": ")] if isinstance(profile, StackSet) else result.phases
            if mine:
                bad = next((p for p in mine if not p.ok), None)
                row["ok"] = bad is None
                row["phase"] = (bad.name.split(": ", 1)[-1] if bad else mine[-1].name.split(": ", 1)[-1])
        rows.append(row)
    return rows


def count_tests(output: str) -> dict:
    """{discovered, passed, failed} read from a test runner's own summary line (pytest, node:test, Maven/Surefire, plain
    'N passed'). Empty dict when the output has no recognisable summary: callers must then say 'unknown', never 'zero'."""
    text = output or ""
    passed = failed = discovered = None
    m = re.search(r"(\d+) passed", text)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", text)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(?:#|\u2139)\s*tests (\d+)", text)
    if m:                                                   # node:test
        discovered = int(m.group(1))
        p = re.search(r"(?:#|\u2139)\s*pass (\d+)", text)
        f = re.search(r"(?:#|\u2139)\s*fail (\d+)", text)
        passed, failed = int(p.group(1)) if p else passed, int(f.group(1)) if f else failed
    runs = re.findall(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+)", text)
    if runs and discovered is None:                         # Maven Surefire: the last line is the total
        total, fails, errs = (int(x) for x in runs[-1])
        discovered, failed, passed = total, fails + errs, total - fails - errs
    if passed is None and failed is None and discovered is None:
        return {}
    passed, failed = passed or 0, failed or 0
    return {"discovered": discovered if discovered is not None else passed + failed, "passed": passed, "failed": failed}


def stack_report(profile, result: "SandboxResult") -> list[dict]:
    """stack_summary plus everything a baseline health report needs: the commands that were configured, what each phase did
    (exit code, seconds), the test counts, and which configured steps never ran because an earlier one failed."""
    rows = stack_summary(profile, result)
    parts = profile.parts if isinstance(profile, StackSet) else [profile]
    for part, row in zip(parts, rows):
        label = row["label"]
        mine = [p for p in result.phases if p.name.startswith(label + ": ")] if isinstance(profile, StackSet) else list(result.phases)
        short = lambda p: p.name.split(": ", 1)[-1]   # noqa: E731
        configured = [n for n, c in (("install", part.install), ("build", part.build), ("test", part.test), ("smoke", part.smoke)) if c]
        ran = {short(p) for p in mine}
        test_phase = next((p for p in mine if short(p) == "test"), None)
        row.update({
            "commands": {"install": part.install, "build": part.build, "test": part.test, "smoke": part.smoke},
            "phases": [{"name": short(p), "ok": p.ok, "rc": p.rc, "seconds": p.seconds} for p in mine],
            "not_run": [n for n in configured if n not in ran],
            "has_tests": bool(part.has_tests),
            "tests": count_tests(test_phase.output) if test_phase else {},
            "notes": list(part.notes)[:5],
        })
    return rows


def _python_profile(root: Path, names: set[str], base: str) -> Profile:
    prof = Profile(language="python", workdir=base)
    py = [n for n in names if n.endswith(".py")]
    if "requirements.txt" in names:
        prof.install = ("pip install --no-input --disable-pip-version-check --no-cache-dir "
                        "-r requirements.txt --target /work/.fx_deps")
    prof.build = "python -m compileall -q ."
    has_tests = any(re.search(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py)$", n) or n.startswith(("tests/", "test/")) for n in py)
    if has_tests:
        prof.test, prof.has_tests = "python -m pytest -q --maxfail=50 -p no:cacheprovider", True
    pre = f"{base}/" if base else ""
    proc = _read(root, f"{pre}Procfile") if "Procfile" in names else ""
    m = re.search(r"^web:\s*(.+)$", proc, re.M)
    if m:
        prof.smoke = m.group(1).strip()
    else:
        render = _read(root, f"{pre}render.yaml") if "render.yaml" in names else ""
        m = re.search(r"startCommand:\s*(.+)", render)
        if m:
            prof.smoke = m.group(1).strip().strip("'\"")
        elif "main.py" in names and "FastAPI(" in _read(root, f"{pre}main.py"):
            prof.smoke = "python -m uvicorn main:app --host 0.0.0.0 --port $PORT"
        elif "app.py" in names and "Flask(" in _read(root, f"{pre}app.py"):
            prof.smoke = "python -m flask --app app run --host 0.0.0.0 --port $PORT"
    return prof


def parse_failing(output: str) -> int | None:
    text = output or ""
    total, found = 0, False
    for pat in (r"(\d+) failed", r"(\d+) errors?\b", r"Tests:\s+(\d+) failed", r"(?:#|\u2139)\s*fail (\d+)"):
        for m in re.finditer(pat, text):
            total += int(m.group(1)); found = True
    return total if found else None


# ---- docker command construction (unit-tested without Docker) ---------------------------------------------------------
def docker_run_argv(*, name: str, image: str, workdir: str, command: str, network: bool, cfg: dict, env: dict | None = None,
                    ro_mounts: list[tuple[str, str]] | None = None) -> list[str]:
    sb = cfg["sandbox"]
    argv = ["docker", "run", "--rm", "--name", name,
            "--user", "10001:10001", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", str(sb["memory"]), "--memory-swap", str(sb["memory"]), "--cpus", str(sb["cpus"]),
            "--pids-limit", str(sb["pids"]),
            "--network", "bridge" if network else "none",
            "-v", f"{workdir}:/work:rw", "-w", "/work"]
    for host, cont in (ro_mounts or []):
        argv += ["-v", f"{host}:{cont}:ro"]
    for k, v in (env or {}).items():
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", k):
            argv += ["-e", f"{k}={v}"]
    argv += [image, "sh", "-c", command]
    return argv


def _default_exec(argv, timeout, cwd=None, env=None):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, env=env)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), False
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        return 124, out, True
    except FileNotFoundError as exc:
        return 127, str(exc), False


class _BaseRunner:
    def __init__(self, cfg: dict, exec_fn=None):
        self.cfg = cfg
        self.exec_fn = exec_fn or _default_exec

    def _finish(self, phases: list[PhaseResult], profile: Profile) -> SandboxResult:
        res = SandboxResult(phases=phases)
        res.tests_ran = any(p.name == "test" for p in phases)
        res.smoke_ran = any(p.name == "smoke" and p.ok for p in phases)
        res.passed = bool(phases) and all(p.ok for p in phases)
        res.timed_out = any(p.rc == 124 for p in phases)
        test_phase = next((p for p in phases if p.name == "test"), None)
        if test_phase:
            res.failing = 0 if test_phase.ok else parse_failing(test_phase.output)
        failed = [p for p in phases if not p.ok]
        pick = failed[0] if failed else (phases[-1] if phases else None)
        res.output = (f"[{pick.name}] exit {pick.rc}\n{pick.output}" if pick else "")[-4000:]
        return res


SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"
IMAGE_KEY = {"python": "image_python", "node": "image_node", "static": "image_node", "java": "image_java"}


def phase_plan(profile: Profile, sb: dict) -> list[tuple[str, str, bool, int]]:
    """(name, shell command, needs_network, timeout seconds). Only the install phase ever gets the network."""
    wd = shlex.quote(profile.workdir) if profile.workdir else ""
    def wrap(cmd: str) -> str:
        return f"cd {wd} && {cmd}" if wd else cmd
    plan = []
    if profile.install:
        plan.append(("install", wrap(profile.install), True, int(sb["install_timeout_seconds"])))
    if profile.build:
        plan.append(("build", wrap(profile.build), False, int(sb["timeout_seconds"])))
    if profile.test:
        plan.append(("test", wrap(profile.test), False, int(sb["timeout_seconds"])))
    if profile.smoke:
        plan.append(("smoke", f"python3 /opt/smoke.py {SMOKE_PORT} {SMOKE_WAIT} {json.dumps(wrap(profile.smoke))}", False, SMOKE_WAIT + 25))
    return plan


class DockerRunner(_BaseRunner):
    def run(self, repo_dir: Path, profile: Profile) -> SandboxResult:
        sb = self.cfg["sandbox"]
        if profile.language == "none" or profile.language not in IMAGE_KEY:
            return SandboxResult(error="no runnable project detected", output="no runnable project detected")
        image = sb.get(IMAGE_KEY[profile.language]) or sb["image_python"]
        mounts = {"smoke": [(str(SANDBOX_DIR / "smoke.py"), "/opt/smoke.py")],
                  "build": [(str(SANDBOX_DIR / "static_check.py"), "/opt/static_check.py")] if profile.language == "static" else None}
        run_id = uuid.uuid4().hex[:12]
        work = Path(tempfile.mkdtemp(prefix="fx-", dir=os.getenv("FIXENGINE_SCRATCH") or None))
        try:
            target = work / "repo"
            shutil.copytree(repo_dir, target, ignore=shutil.ignore_patterns(".git"))
            for p in [target, *target.rglob("*")]:
                try:
                    os.chmod(p, 0o777 if p.is_dir() else 0o666)
                except OSError:
                    pass
            sub = f"/{profile.workdir}" if profile.workdir else ""
            env = {"PYTHONPATH": f"/work/.fx_deps:/work{sub}", "CI": "1", "PORT": str(SMOKE_PORT)}
            phases: list[PhaseResult] = []
            for name, cmd, net, timeout in phase_plan(profile, sb):
                cname = f"fx-{run_id}-{name}"
                argv = docker_run_argv(name=cname, image=image, workdir=str(target), command=cmd, network=net, cfg=self.cfg,
                                       env=env, ro_mounts=mounts.get(name))
                started = time.time()
                rc, out, timed_out = self.exec_fn(argv, timeout + 10)
                if timed_out:
                    self.exec_fn(["docker", "kill", cname], 15)
                if rc == 127 and "docker" in out.lower():
                    return SandboxResult(system_fault=True, error="Docker is not available on this machine", output=out[-500:])
                phases.append(PhaseResult(name, rc == 0, rc, round(time.time() - started, 1), out[-6000:]))
                if rc != 0:
                    break
            return self._finish(phases, profile)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class LocalUnsafeRunner(_BaseRunner):
    """For this repo's own tests and development ONLY. Refuses to run unless explicitly allowed.

    It runs the project's commands directly on this machine with NO isolation. Use it only on the sample projects that
    ship with this repo (bench/cases) on a throw-away machine. Real customer code must go through Docker."""

    @staticmethod
    def _local_env(work: Path, extra: dict | None = None) -> dict:
        """Build a subprocess environment that works on both POSIX and Windows.

        On Windows, Python's user-site-packages live under %APPDATA% and
        %LOCALAPPDATA%, which are absent from the minimal env we normally
        construct.  Without them ``python -m pytest`` cannot find pytest even
        though it is installed, causing every sandbox test run to fail with
        "No module named pytest".  We carry those variables across so the
        subprocess finds the same packages as the parent process.
        """
        keep = {k.upper() for k in (
            "PATH", "JAVA_HOME", "LANG", "TMPDIR",
            # Windows-specific: needed for user site-packages, Winsock, and basic OS subsystem
            "APPDATA", "LOCALAPPDATA", "USERPROFILE",
            "SYSTEMROOT", "COMSPEC", "PATHEXT",
            "TMP", "TEMP", "PYTHONUSERBASE", "VIRTUAL_ENV",
            "WINDIR", "SYSTEMDRIVE", "PROGRAMDATA", "PROGRAMFILES"
        )}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env["HOME"] = str(work)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if extra:
            env.update(extra)
        return env

    def run(self, repo_dir: Path, profile: Profile) -> SandboxResult:
        if os.getenv("FIXENGINE_ALLOW_UNSAFE_LOCAL") != "1":
            return SandboxResult(system_fault=True, error="local_unsafe sandbox needs FIXENGINE_ALLOW_UNSAFE_LOCAL=1")
        if profile.language not in ("python", "node", "static", "java"):
            return SandboxResult(system_fault=True, error="local_unsafe sandbox does not support this project type")
        work = Path(tempfile.mkdtemp(prefix="fx-local-"))
        try:
            target = work / "repo"
            shutil.copytree(repo_dir, target, ignore=shutil.ignore_patterns(".git"))
            if profile.language != "python":
                return self._run_generic(target, work, profile)
            env = self._local_env(work, {"PYTHONPATH": str(target)})
            plan = []
            if profile.build:
                plan.append(("build", [sys.executable, "-m", "compileall", "-q", "."], 60))
            if profile.test:
                plan.append(("test", [sys.executable, "-m", "pytest", "-q", "--maxfail=50", "-p", "no:cacheprovider"], int(self.cfg["sandbox"]["timeout_seconds"])))
            phases = []
            for name, argv, timeout in plan:
                started = time.time()
                rc, out, _t = self.exec_fn(argv, timeout, str(target), env)
                phases.append(PhaseResult(name, rc == 0, rc, round(time.time() - started, 1), out[-6000:]))
                if rc != 0:
                    break
            return self._finish(phases, profile)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run_generic(self, target: Path, work: Path, profile: Profile) -> SandboxResult:
        sb = self.cfg["sandbox"]
        env = self._local_env(work, {"CI": "1", "PORT": str(SMOKE_PORT)})
        phases: list[PhaseResult] = []
        for name, cmd, net, timeout in phase_plan(profile, sb):
            if name == "install" and not (target / (profile.workdir or ".") / "package.json").exists() and profile.language == "node":
                continue
            win = sys.platform == "win32"
            quote = (lambda s: f'"{s}"') if win else shlex.quote  # cmd.exe does not understand POSIX single quotes
            cmd = cmd.replace("/opt/static_check.py", quote(str(SANDBOX_DIR / "static_check.py"))).replace("/opt/smoke.py", quote(str(SANDBOX_DIR / "smoke.py")))
            cmd = cmd.replace("python3 ", f"{quote(sys.executable)} ", 1) if cmd.startswith("python3 ") else cmd
            if win:
                # cmd.exe does not expand $VAR
                cmd = cmd.replace("$PORT", str(SMOKE_PORT))
                # `find` and `mkdir -p` are POSIX-only: build the javac source list in Python instead.
                if "find . -name '*.java'" in cmd:
                    srcs = sorted(p.relative_to(target / (profile.workdir or ".")).as_posix()
                                  for p in (target / (profile.workdir or ".")).rglob("*.java")
                                  if not any(part.startswith(".fx_") for part in p.parts))
                    (target / (profile.workdir or ".") / ".fx_srcs.txt").write_text(
                        "\n".join(f'"{s}"' for s in srcs), encoding="utf-8")
                    cmd = re.sub(r"find \. -name .*@\.fx_srcs\.txt", "if not exist .fx_out mkdir .fx_out && javac -encoding UTF-8 -Xlint:none -d .fx_out @.fx_srcs.txt", cmd)
            started = time.time()
            # On Windows write the command to a .bat file: passing it through `cmd /C` mangles nested quotes
            # (list2cmdline escapes with \" which cmd.exe does not understand). On POSIX use sh -c.
            if sys.platform == "win32":
                bat = work / f"phase_{name}.bat"
                bat.write_text(f"@echo off\r\ncd /d \"{target}\"\r\n{cmd}\r\nexit /b %ERRORLEVEL%\r\n", encoding="utf-8")
                shell_argv = ["cmd", "/D", "/C", str(bat)]
            else:
                shell_argv = ["sh", "-c", cmd]
            rc, out, _t = self.exec_fn(shell_argv, timeout, str(target), env)
            phases.append(PhaseResult(name, rc == 0, rc, round(time.time() - started, 1), out[-6000:]))
            if rc != 0:
                break
        return self._finish(phases, profile)


# ---- remote runner ----------------------------------------------------------------------------------------------------------
def tar_dir_b64(root: Path, limit_bytes: int = 30 * 1024 * 1024) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(Path(root).rglob("*")):
            rel = p.relative_to(root)
            if ".git" in rel.parts or not p.is_file() or p.is_symlink():
                continue
            tar.add(p, arcname=rel.as_posix())
    data = buf.getvalue()
    if len(data) > limit_bytes:
        raise ValueError("repository too large for the remote sandbox")
    return base64.b64encode(data).decode()


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class RemoteRunner(_BaseRunner):
    def run(self, repo_dir: Path, profile: Profile) -> SandboxResult:
        url, secret = os.getenv("FIXENGINE_SANDBOX_URL", "").rstrip("/"), os.getenv("FIXENGINE_SANDBOX_SECRET", "")
        if not url or not secret:
            return SandboxResult(system_fault=True, error="FIXENGINE_SANDBOX_URL / FIXENGINE_SANDBOX_SECRET are not set")
        try:
            body = json.dumps({"repo_b64": tar_dir_b64(repo_dir), "profile": asdict(profile)}).encode()
        except ValueError as exc:
            return SandboxResult(error=str(exc), output=str(exc))
        ts = str(int(time.time()))
        try:
            resp = httpx.post(url + "/run", content=body, timeout=int(self.cfg["sandbox"]["install_timeout_seconds"]) + 400,
                              headers={"X-Timestamp": ts, "X-Signature": sign(secret, ts, body), "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            return SandboxResult(system_fault=True, error=f"sandbox host unreachable ({type(exc).__name__})")
        if resp.status_code != 200:
            return SandboxResult(system_fault=True, error=f"sandbox host returned HTTP {resp.status_code}")
        return SandboxResult.from_dict(resp.json())


def make_runner(cfg: dict, exec_fn=None):
    mode = os.getenv("FIXENGINE_SANDBOX_MODE") or cfg["sandbox"]["mode"]
    if mode == "remote":
        return RemoteRunner(cfg, exec_fn)
    if mode == "local_unsafe":
        return LocalUnsafeRunner(cfg, exec_fn)
    return DockerRunner(cfg, exec_fn)
