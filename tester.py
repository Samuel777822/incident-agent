import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_test_environment(repo_folder):
    env = os.environ.copy()
    repo_path = Path(repo_folder).resolve()

    # Search for virtualenv Scripts directory
    venv_candidates = [
        repo_path / ".venv" / "Scripts",
        repo_path.parent / ".venv" / "Scripts",
        Path(__file__).parent / ".venv" / "Scripts",
        Path(r"C:\Users\admin\Downloads\test\.venv\Scripts"),
    ]

    for venv_scripts in venv_candidates:
        if venv_scripts.is_dir():
            env["PATH"] = str(venv_scripts) + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(venv_scripts.parent)
            break

    return env


def run_tests(repo_folder, test_command="pytest", timeout=60):
    env = get_test_environment(repo_folder)
    
    # If test_command is "pytest", check if pytest is on path, else fallback to python -m pytest
    cmd = test_command
    if test_command.strip() == "pytest":
        pytest_exe = shutil.which("pytest", path=env.get("PATH"))
        if not pytest_exe:
            python_exe = shutil.which("python", path=env.get("PATH")) or sys.executable
            cmd = f'"{python_exe}" -m pytest'

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_folder),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        passed = (proc.returncode == 0)
        output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        return passed, output.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"Test command timed out after {timeout} seconds", -1
    except Exception as exc:
        return False, f"Failed to execute tests: {exc}", -1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    passed, out, code = run_tests(target)
    print(f"Passed: {passed} (code {code})")
    print(out[:500])
