import json
from pathlib import Path

REPOS_FILE = Path(__file__).parent / "repos.json"


def add_repo(service, url, branch="main", test_command="pytest", mode=None, log_path=None):
    repos = {}
    if REPOS_FILE.exists():
        repos = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    entry = repos.get(service, {})
    entry.update({"url": url, "branch": branch, "test_command": test_command})
    entry["mode"] = mode or entry.get("mode", "report")
    if log_path:
        entry["log_path"] = log_path
    repos[service] = entry
    REPOS_FILE.write_text(json.dumps(repos, indent=2), encoding="utf-8")
    print("saved:", service, "->", url, "| mode:", entry["mode"])


if __name__ == "__main__":
    service = input("Service name (same as 'service' in their logs): ").strip()
    url = input("GitHub repo URL: ").strip()
    branch = input("Branch [main]: ").strip() or "main"
    mode = input("Mode report/pr/auto [keep current or report]: ").strip() or None
    log_path = input("Absolute path to the app log file [skip]: ").strip() or None
    add_repo(service, url, branch, mode=mode, log_path=log_path)