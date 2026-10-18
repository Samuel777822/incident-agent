from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".idea",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "demo_tools",
}

EXCLUDED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".exe",
    ".dll",
}


def collect_repository(repo_path):
    root = Path(repo_path).resolve()

    if not root.is_dir():
        raise ValueError(f"Repository folder does not exist: {root}")

    # Reject a virtual environment selected as the repository root.
    if (
            root.name.lower() in {".venv", "venv", "virtualenv"}
            or (root / "pyvenv.cfg").is_file()
    ):
        raise ValueError(
            f"This looks like a Python virtual environment, not a repository root: {root}\n"
            "Choose the project folder containing files such as main.py and requirements.txt."
        )

    evidence = {}

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(root)

        if any(part in EXCLUDED_DIRS for part in relative_path.parts[:-1]):
            continue

        if path.name in EXCLUDED_FILES:
            continue

        if path.name.startswith(".env."):
            continue

        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        evidence[relative_path.as_posix()] = content

    return evidence


if __name__ == "__main__":
    repo_path = input("Enter the full path to your repository folder: ")

    evidence = collect_repository(repo_path)

    print("\nFiles collected:", len(evidence))

    for file_path in sorted(evidence):
        content = evidence[file_path]

        print(f"\n{'=' * 60}")
        print(f"FILE: {file_path}")
        print("=" * 60)
        print(content[:300])