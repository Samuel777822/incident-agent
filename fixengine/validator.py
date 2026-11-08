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


PROVEN_LEVELS = ("tests_fixed", "check_fixed", "journey_fixed")

VERIFY_TEXT = {
    "journey_fixed": "A browser journey (opening the pages and clicking the buttons) failed before the fix and passes with it, and the build and checks pass too.",
    "parse_only": "Every changed file still parses. The sandbox could not be used for this check.",
    "check_fixed": "The pushed commit failed our sandbox check (install, build, type-check, tests or site check). With this fix the same check passes.",
    "tests_fixed": "Tests that failed before the fix now pass, the project builds, and (where detectable) it starts.",
    "tests_pass_not_reproduced": "The project's tests pass, but they did not reproduce this error before the fix, so the fix is NOT proven. Review carefully.",
    "smoke_only": "This project has no tests. It builds and starts, but the fix itself is NOT proven by a test. Review carefully.",
    "build_only": "NOT VERIFIED: no tests or start-up check were available. Only a syntax/build check passed. Review carefully.",
}
