"""Free, rule-based triage (plan 4.3). No paid model runs before this."""
from __future__ import annotations

import re

EASY_TYPES = {"syntaxerror", "indentationerror", "importerror", "modulenotfounderror", "nameerror",
              "referenceerror", "unboundlocalerror", "keyerror", "attributeerror", "typeerror",
              # Java / TypeScript / static-site errors that are usually a one-line mistake
              "cannotfindsymbol", "incompatibletypes", "expected", "missingreturnstatement", "classxisnotabstract",
              "ts2304", "ts2339", "ts2551", "ts2552", "ts2322", "ts2345", "ts2307", "ts2532", "ts18048", "ts2554",
              "nullpointerexception", "arrayindexoutofboundsexception", "numberformatexception", "classcastexception"}
# Static HTML/CSS/JS problems found by sandbox/static_check.py (unclosed tag, missing file, unbalanced brace, JS syntax)
STATIC_HINTS = ("unclosed <", "unexpected closing", "missing file", "unbalanced", "missing }", "unterminated",
                "syntaxerror", "invalid json", "declaration without")
CONFIG_HINTS = ("environment variable", "environ", "no such file", "connection refused", "config",
                "secret", "api key", "permission denied", "module not found", "cannot find module")
# Whole-word matches only: a plain substring test made "race" match every Python "Traceback" and "lock" match "block".
HARD_RE = re.compile(r"\b(?:race condition|races?|deadlock\w*|lock(?:s|ed|ing)?|async\w*|await\w*|threads?|thread-?safe|concurren\w*|"
                     r"timeouts?|timed out|state|stale|cache[ds]?|inconsistent|memory|synchronized|volatile|promises?|"
                     r"unhandled rejection|useeffect|stack overflow)\b")


def classify(*, error_type: str, message: str, traceback: str, frame_count: int, files_in_trace: int,
             repo_tokens: int, has_tests: bool, prior_failures: int = 0, prior_models=()) -> dict:
    """Return {"bug_class": easy|medium|hard, "category": ..., "score": n, "reasons": [...]}"""
    et = (error_type or "").lower()
    text = f"{message}\n{traceback}".lower()
    score, reasons = 0, []
    if et in EASY_TYPES and files_in_trace <= 1:
        score -= 2
        reasons.append(f"simple error type ({error_type}) in one file")
    elif et in EASY_TYPES:
        score -= 1
        reasons.append(f"simple error type ({error_type})")
    category = "logic"
    if et.startswith("static_") or any(h in text for h in STATIC_HINTS) and et.startswith(("static", "syntax")):
        category = "markup_or_style"
        score -= 1
        reasons.append("static HTML/CSS/JS problem")
    elif et in {"syntaxerror", "indentationerror"}:
        category = "syntax"
    elif et in {"importerror", "modulenotfounderror"} or "cannot find module" in text:
        category = "missing_import"
    elif any(h in text for h in CONFIG_HINTS):
        category = "config_or_environment"
        score -= 1
        reasons.append("looks like config or environment")
    if category != "markup_or_style" and HARD_RE.search(text):
        score += 2
        category = "concurrency_or_state"
        reasons.append("async, race or state wording")
    if files_in_trace >= 3:
        score += 2
        reasons.append(f"{files_in_trace} files in the trace")
    elif files_in_trace == 2:
        score += 1
    if frame_count > 12:
        score += 1
    if repo_tokens > 40_000:
        score += 1
        reasons.append("large repo")
    if not has_tests:
        score += 1
        reasons.append("no tests to check against")
    if prior_failures >= 3:
        score += 2
        reasons.append(f"failed {prior_failures} times before")
    elif prior_failures >= 1:
        score += 1
    if re.search(r"assert|expected .* got|wrong (?:result|total|value)", text):
        score += 1
        reasons.append("wrong-result style failure")
    bug_class = "easy" if score <= 0 else ("medium" if score <= 2 else "hard")
    return {"bug_class": bug_class, "category": category, "score": score, "reasons": reasons}
