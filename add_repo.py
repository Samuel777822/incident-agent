import json
from pathlib import Path

REPOS_FILE = Path(__file__).parent / "repos.json"


def add_repo(service, url, branch="main", test_command="pytest"):
    repos = {}
    if REPOS_FILE.exists():
        repos = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    repos[service] = {"url": url, "branch": branch, "test_command": test_command}
    REPOS_FILE.write_text(json.dumps(repos, indent=2), encoding="utf-8")
    print("saved:", service, "->", url)


if __name__ == "__main__":
    service = input("Service name (same as 'service' in their logs): ").strip()
    url = input("GitHub repo URL: ").strip()
    branch = input("Branch [main]: ").strip() or "main"
    add_repo(service, url, branch)