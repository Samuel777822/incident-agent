import json
from pathlib import Path

REPOS_FILE = Path(__file__).parent / "repos.json"


def get_repo_config(service):
    repos = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    cfg = repos.get(service)
    if not cfg:
        raise ValueError(
            f"No repository configured for service '{service}'. Add it to repos.json first."
        )
    cfg.setdefault("mode", "report")
    cfg.setdefault("branch", "main")
    cfg.setdefault("test_command", "pytest")
    return cfg