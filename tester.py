"""Safe subprocess test runner and helpers for interpreting test output."""
import os
import re
import subprocess
import sys
from dataclasses import dataclass

SECRET_VARS = ("GITHUB_TOKEN", "GROQ_API_KEY", "RENDER_API_KEY")


@dataclass(frozen=True)
class TestResult:
    __test__ = False
    passed: bool
    output: str
    return_code: int


def sanitize_test_output(output: str) -> str:
    """Mask configured credentials and common GitHub token URL patterns."""
    result = str(output or "")
    for name in SECRET_VARS:
        secret = os.getenv(name, "")
        if secret:
            result = result.replace(secret, "***")
    result = re.sub(r"(https?://x-access-token:)[^@/\s]+@", r"\1***@", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b", "***", result)
    return result


def classify_failure(output: str, return_code: int) -> str:
    if return_code == 0:
        return "passed"
    text = str(output or "").lower()
    if "assertionerror" in text or "assert " in text or "assertion failed" in text:
        return "assertion_failure"
    if "syntaxerror" in text or "indentationerror" in text:
        return "syntax_error"
    if "modulenotfounderror" in text or "importerror" in text:
        return "import_error"
    if "error during collection" in text or "error collecting" in text:
        return "collection_error"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "test_failure"


def extract_failure_summary(output: str, max_lines: int = 8) -> str:
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    relevant = [line for line in lines if re.search(r"(AssertionError|ImportError|ModuleNotFoundError|SyntaxError|FAILED|ERROR|Error:)", line)]
    return "\n".join((relevant or lines[-max_lines:])[:max_lines])[:2000]


def get_test_environment():
    env = os.environ.copy()
    for name in SECRET_VARS:
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_tests(repo_folder, test_command="pytest", timeout=120):
    cmd = (test_command or "pytest").strip()
    if cmd == "pytest":
        cmd = f'"{sys.executable}" -m pytest -q'
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_folder),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_test_environment(),
        )
        output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        output = sanitize_test_output(output).strip()
        return proc.returncode == 0, output, proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"Test command timed out after {timeout} seconds", -1
    except Exception as exc:
        return False, f"Failed to execute tests: {exc}", -1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    passed, out, code = run_tests(target)
    print(f"Passed: {passed} (code {code})")
    print(out[:500])
