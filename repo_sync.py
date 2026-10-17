import subprocess
from pathlib import Path

from config import get_repo_config

WORKSPACES = Path(__file__).parent / "workspaces"


def run_git(args, cwd=None):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def get_local_repo(service):
    cfg = get_repo_config(service)
    folder = WORKSPACES / service
    if (folder / ".git").is_dir():
        run_git(["fetch", "origin", cfg["branch"]], cwd=folder)
        run_git(["reset", "--hard", f"origin/{cfg['branch']}"], cwd=folder)
    else:
        WORKSPACES.mkdir(exist_ok=True)
        run_git(["clone", "--branch", cfg["branch"], cfg["url"], str(folder)])
    return folder