import os
import subprocess
import sys

SECRET_VARS = ("GITHUB_TOKEN", "GROQ_API_KEY", "RENDER_API_KEY")


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
        return proc.returncode == 0, output.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"Test command timed out after {timeout} seconds", -1
    except Exception as exc:
        return False, f"Failed to execute tests: {exc}", -1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    passed, out, code = run_tests(target)
    print(f"Passed: {passed} (code {code})")
    print(out[:500])
