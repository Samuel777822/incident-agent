import subprocess

from repo_sync import run_git


def get_git_evidence(folder, commits=5, per_commit_chars=1500):
    try:
        hashes = run_git(
            ["log", f"-{commits}", "--pretty=format:%h"], cwd=folder
        ).split()
        parts = []
        for h in hashes:
            shown = run_git(
                ["show", "--date=short", "--pretty=format:%h | %ad | %an | %s", "-U2", h],
                cwd=folder,
            )
            parts.append(shown[:per_commit_chars])
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as err:
        return f"Git history unavailable: {err}"
    return (
        "RECENT COMMITS (newest first; each cut to a size limit):\n\n"
        + "\n\n---\n\n".join(parts)
    )