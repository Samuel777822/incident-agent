"""Patch policy and application (plan 4.7). The model proposes; this code decides what is allowed to touch the repo."""
from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path, PurePosixPath

from . import prompts
from .repo_context import is_test_path

DENY_PATH = re.compile(r"(^|/)(\.github|\.gitlab|\.circleci|\.husky|deploy|infra|terraform|k8s|helm|\.mvn|gradle/wrapper)(/|$)", re.I)
DENY_NAME = re.compile(r"(billing|stripe|razorpay|paypal)", re.I)
DENY_FILES = {"requirements.txt", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
              "pyproject.toml", "pipfile", "pipfile.lock", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
              "procfile", "render.yaml", "vercel.json", "netlify.toml", "setup.py", "setup.cfg", ".gitignore",
              # plan v3: build and type-check configuration. A model must not loosen the checks that prove its own fix.
              "tsconfig.json", "jsconfig.json", ".eslintrc", ".eslintrc.json", ".eslintrc.js", "eslint.config.js", ".babelrc",
              "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties",
              "gradlew", "gradlew.bat", "mvnw", "mvnw.cmd", "vite.config.js", "vite.config.ts", "next.config.js", "webpack.config.js"}


class PolicyError(ValueError):
    pass


def check_edits(edits: list[dict], repo_files: dict[str, str], cfg: dict | None = None) -> None:
    max_files, max_lines = 5, 120
    if not edits:
        raise PolicyError("no edits")
    if len({e["file_path"] for e in edits}) > max_files:
        raise PolicyError(f"touches more than {max_files} files")
    changed = 0
    for e in edits:
        path = e["file_path"]
        parts = PurePosixPath(path).parts
        if path.startswith("/") or ".." in parts or path not in repo_files:
            raise PolicyError(f"unknown or unsafe path: {path[:80]}")
        if PurePosixPath(path).suffix.lower() not in prompts.CODE_EXT:
            raise PolicyError(f"not a source file: {path}")
        name = PurePosixPath(path).name.lower()
        if name in DENY_FILES or DENY_PATH.search(path) or DENY_NAME.search(path) or prompts.is_secret_path(path):
            raise PolicyError(f"protected file: {path}")
        if is_test_path(path):
            raise PolicyError(f"tests may not be edited: {path}")
        if prompts.contains_secret(e["new_text"]):
            raise PolicyError("the patch contains something that looks like a secret")
        flag = prompts.new_suspicious(e["old_text"], e["new_text"])
        if flag:
            raise PolicyError(f"the patch introduces a suspicious construct ({flag})")
        changed += max(len(e["old_text"].splitlines()), len(e["new_text"].splitlines()))
    if changed > max_lines:
        raise PolicyError(f"changes about {changed} lines (limit {max_lines})")


def apply_edits(edits: list[dict], repo_files: dict[str, str]) -> tuple[dict[str, str], str]:
    """Return ({path: new_text}, unified diff). old_text must occur exactly once per edit."""
    new_files: dict[str, str] = {}
    for e in edits:
        text = new_files.get(e["file_path"], repo_files[e["file_path"]])
        count = text.count(e["old_text"])
        if count == 0:
            raise PolicyError(f"old_text was not found in {e['file_path']}")
        if count > 1:
            raise PolicyError(f"old_text matches {count} places in {e['file_path']}")
        new_files[e["file_path"]] = text.replace(e["old_text"], e["new_text"], 1)
    diff_parts = []
    for path, new in new_files.items():
        old = repo_files[path]
        if new == old:
            raise PolicyError(f"the edit does not change {path}")
        if path.endswith(".py"):
            try:
                ast.parse(new, filename=path)
            except SyntaxError as exc:
                raise PolicyError(f"{path} would not parse: line {exc.lineno}") from None
        diff_parts.append("".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                                       fromfile=f"a/{path}", tofile=f"b/{path}")))
    return new_files, "\n".join(diff_parts)


def write_files(root: Path, new_files: dict[str, str]) -> None:
    root = Path(root).resolve()
    for rel, text in new_files.items():
        target = (root / rel).resolve()
        target.relative_to(root)             # raises if it escapes the repo
        target.write_text(text, encoding="utf-8")


def verification_level(*, baseline_failing, baseline_had_tests: bool, result, check_failed_before: bool = False) -> str:
    """How much the sandbox run actually proves (used in the PR text and to block auto-merge).

    check_failed_before: the bug came from a push check, so the sandbox run that failed on the pushed commit IS the
    reproduction. If that same run (install, build, type-check, tests, site check, start-up) is green after the fix, the fix
    is proven even when the project has no tests."""
    if result.passed and getattr(result, "journeys_ran", False) and baseline_failing not in (None, 0):
        return "journey_fixed"           # a real browser journey failed before the fix and passes now
    if check_failed_before and result.passed and baseline_failing not in (None, 0):
        if result.tests_ran and baseline_had_tests and baseline_failing > 0:
            return "tests_fixed"
        return "check_fixed"
    if result.tests_ran and result.passed:
        if baseline_had_tests and baseline_failing and baseline_failing > 0:
            return "tests_fixed"          # the tests failed before and pass now
        return "tests_pass_not_reproduced"  # tests pass, but they never reproduced this bug
    if result.smoke_ran and result.passed:
        return "smoke_only"
    if result.passed:
        return "build_only"
    return "failed"


PROVEN_LEVELS = ("tests_fixed", "check_fixed", "journey_fixed", "new_test_fixed")

VERIFY_TEXT = {
    "new_test_fixed": "The engineer wrote a new test for this problem: it FAILS on the old code and PASSES with the fix, and the build and checks pass too.",
    "journey_fixed": "A browser journey (opening the pages and clicking the buttons) failed before the fix and passes with it, and the build and checks pass too.",
    "parse_only": "Every changed file still parses. The sandbox could not be used for this check.",
    "check_fixed": "The pushed commit failed our sandbox check (install, build, type-check, tests or site check). With this fix the same check passes.",
    "tests_fixed": "Tests that failed before the fix now pass, the project builds, and (where detectable) it starts.",
    "tests_pass_not_reproduced": "The project's tests pass, but they did not reproduce this error before the fix, so the fix is NOT proven. Review carefully.",
    "smoke_only": "This project has no tests. It builds and starts, but the fix itself is NOT proven by a test. Review carefully.",
    "build_only": "NOT VERIFIED: no tests or start-up check were available. Only a syntax/build check passed. Review carefully.",
}


# =================================================================================================================================
# v4: rules for the engineer's (agent's) final change. These are the mistakes the old engine actually pushed to Bible-Well:
# a working key replaced by a placeholder, a fake Supabase client, an error message removed "so the monitor stops reporting it",
# and a Bible version deleted to avoid an error. Each is now rejected before anything leaves the sandbox.
# =================================================================================================================================
AGENT_MAX_FILES = 30
AGENT_MAX_LINES = 2500
LOCK_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "composer.lock", "gemfile.lock", "cargo.lock"}
MONITOR_FILES = re.compile(r"(^|/)(incident[-_]agent[-_](monitor|config)[\w.-]*|INCIDENT_AGENT_SETUP\.md)$", re.I)
PLACEHOLDER = re.compile(r"""['"`](public[-_]anon[-_]key|anon[-_]key[-_]here|your[-_ ]?(?:api[-_ ]?|anon[-_ ]?|secret[-_ ]?)?key(?:[-_ ]?here)?|"""
                         r"""changeme|change[-_]me|replace[-_]?me|placeholder|x{4,}|<your[^>'"`]*>|YOUR_[A-Z0-9_]+|todo[-_ ]?key|dummy[-_ ]?key)['"`]""", re.I)
LONG_LITERAL = re.compile(r"""['"`]([A-Za-z0-9_\-\.=+/]{32,})['"`]""")
ENV_READ = re.compile(r"(import\.meta\.env\.|process\.env\.|os\.(?:getenv|environ)|System\.getenv|Deno\.env)")
STUB_WORD = re.compile(r"\b(stub(?:bed|s)?|mock(?:ed|s)?|fake|dummy|no-?op client)\b", re.I)
ERROR_REPORT = re.compile(r"(console\.(?:error|warn)\s*\(|\blogger\.(?:error|exception|warning)\s*\(|\blogging\.(?:error|exception)\s*\(|"
                          r"\bthrow\b|\braise\b|captureException|reportError)")
QUOTED = re.compile(r"""['"]([^'"\n]{1,40})['"]""")
BUILD_FILES = {"package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "tsconfig.json", "vite.config.js",
               "vite.config.ts", "next.config.js", "webpack.config.js"}
HOSTING_FILES = {"dockerfile", "procfile", "render.yaml", "vercel.json", "netlify.toml", "fly.toml", "railway.json", "app.yaml",
                 "docker-compose.yml", ".gitignore"}


def name_of(path: str) -> str:
    return PurePosixPath(path).name.lower()


LIST_ITEM = r"""['"][^'"\n]{1,40}['"]"""
LIST_LITERAL = re.compile(r"[\[(]\s*" + LIST_ITEM + r"(?:\s*,\s*" + LIST_ITEM + r")+\s*,?\s*[\])]")
OPTION_VALUE = re.compile(r"^\w[\w .+&/-]{0,29}$")


def list_values(line: str) -> list[str]:
    """Simple values of a list / tuple literal on one line: ["NIV", "ESV", "NLT"] -> NIV, ESV, NLT.

    Only real option lists count. Quoted HTML or code fragments ('<a class=', '</section>') are not options: counting them made
    the rule reject ordinary layout edits in pages that build their HTML inside strings."""
    out = []
    for m in LIST_LITERAL.finditer(line):
        vals = [v for v in QUOTED.findall(m.group(0)) if OPTION_VALUE.match(v.strip())]
        if len(vals) >= 2:
            out += vals
    return out


def agent_path_problem(path: str, *, existed: bool) -> str:
    """'' when the agent may write this file, else the reason. New test files are allowed (a reproduction); existing ones are not."""
    name = PurePosixPath(path).name.lower()
    if prompts.is_secret_path(path):
        return f"{path} is a secret / key file: never written"
    if DENY_PATH.search(path):
        return f"{path} is a CI, deploy or infrastructure file: not changed automatically"
    if name in LOCK_FILES:
        return f"{path} is a lock file: not changed automatically"
    if MONITOR_FILES.search(path):
        return f"{path} is part of the Agent Daemon monitor: it must not be changed to make a report go away"
    if existed and is_test_path(path):
        return f"{path} is an existing test: tests are not edited (add a NEW test to reproduce the bug)"
    return ""


def _added_removed(old: str, new: str) -> tuple[list[str], list[str]]:
    added, removed = [], []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


def agent_change_problems(original: dict[str, str], changed: dict[str, str]) -> list[str]:
    """HARD blocks only: what must never go out ([] = acceptable). Secrets in code, protected files (secret, lock, CI, monitor,
    existing tests), risky constructs, code that does not parse, absurd size. Judgement calls are warnings, see agent_change_warnings."""
    return _agent_review(original, changed)[0]


def agent_change_warnings(original: dict[str, str], changed: dict[str, str]) -> list[str]:
    """Judgement calls the ENGINEER may make (it decides), but a person should see them before they go live: a removed option,
    removed error reporting, a stub, a placeholder value, a value moved to an environment variable. Such a fix becomes a pull
    request with these warnings written in plain words, instead of a silent push."""
    return _agent_review(original, changed)[1]


def _agent_review(original: dict[str, str], changed: dict[str, str]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    if len(changed) > AGENT_MAX_FILES:
        problems.append(f"changes {len(changed)} files (limit {AGENT_MAX_FILES}); split the work or explain it to the owner")
    total = 0
    for path, new in sorted(changed.items()):
        old = original.get(path, "")
        why = agent_path_problem(path, existed=path in original)
        if why:
            problems.append(why)
            continue
        added, removed = _added_removed(old, new)
        total += max(len(added), len(removed))
        test_file = is_test_path(path)
        add_text, rem_text = "\n".join(added), "\n".join(removed)
        if prompts.contains_secret(add_text):
            problems.append(f"{path}: the change adds something that looks like a secret key")
        flag = prompts.new_suspicious(old, new)
        if flag and not test_file:
            problems.append(f"{path}: the change adds a risky construct ({flag})")
        if path.endswith(".py") and new.strip():
            try:
                ast.parse(new, filename=path)
            except SyntaxError as exc:
                problems.append(f"{path}: would not parse (line {exc.lineno})")
        if test_file:
            continue
        if PLACEHOLDER.search(add_text) and not PLACEHOLDER.search(rem_text) and name_of(path) not in prompts.EXAMPLE_ENV:
            warnings.append(f"{path}: puts a placeholder where a real value was (if the real value is needed, the site breaks)")
        lost = [m.group(1) for line in removed for m in LONG_LITERAL.finditer(line) if m.group(1) not in new]
        if lost and ENV_READ.search(add_text):
            warnings.append(f"{path}: moves a value from the code into an environment variable; your host must have that variable set")
        if STUB_WORD.search(add_text) and not STUB_WORD.search(old):
            warnings.append(f"{path}: adds a stub / fake object instead of the real service")
        lost_reports = len(ERROR_REPORT.findall(rem_text)) - len(ERROR_REPORT.findall(add_text))
        if lost_reports > 0:
            warnings.append(f"{path}: removes error reporting (console.error / throw / logging)")
        old_options = {q for line in removed for q in list_values(line)}
        gone = sorted(q for q in old_options if f'"{q}"' not in new and f"'{q}'" not in new)
        if gone:
            warnings.append(f"{path}: removes {', '.join(repr(g) for g in gone[:4])} from a list (check that this was intended)")
    if total > AGENT_MAX_LINES:
        problems.append(f"changes about {total} lines (limit {AGENT_MAX_LINES})")
    return problems, warnings


SAFE_SCRIPTS = {"test", "lint", "format", "typecheck", "check", "test:watch", "test:unit", "coverage"}


def _only_test_scripts(old: str | None, new: str) -> bool:
    """package.json where the only change is a test / lint script: that runs nothing on the live site."""
    import json as _json
    try:
        before, after = _json.loads(old or "{}"), _json.loads(new)
    except ValueError:
        return False
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    rest = lambda d: {k: v for k, v in d.items() if k != "scripts"}          # noqa: E731
    if rest(before) != rest(after):
        return False
    sb, sa = before.get("scripts") or {}, after.get("scripts") or {}
    touched = {k for k in set(sb) | set(sa) if sb.get(k) != sa.get(k)}
    return bool(touched) and touched <= SAFE_SCRIPTS


def agent_risk_notes(changed: dict[str, str], original: dict[str, str] | None = None) -> list[str]:
    """Not forbidden, but a person should look first (the change goes to a pull request, not straight to the live branch)."""
    original = original or {}
    notes = [f"{p} changes a dependency or build setting" for p in changed if name_of(p) in BUILD_FILES
             and not (name_of(p) == "package.json" and _only_test_scripts(original.get(p), changed[p]))]
    notes += [f"{p} changes how your app is hosted" for p in changed if name_of(p) in HOSTING_FILES]
    return notes
