"""One-time setup: asks for your OpenRouter key (hidden while you type) and creates the private .env file for you.

    python setup_env.py

The key is only written to .env on this computer. It is never printed, never sent anywhere by this script, and .env is ignored
by git and Docker. Paste a NEW key (delete any key that was ever shared in a chat or a screenshot first).
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build_env_text(example_text: str, key: str) -> str:
    out, done = [], False
    for line in example_text.splitlines():
        if re.match(r"^OPENROUTER_API_KEY=", line):
            out.append("OPENROUTER_API_KEY=" + key)
            done = True
        else:
            out.append(line)
    if not done:
        out.append("OPENROUTER_API_KEY=" + key)
    return "\n".join(out) + "\n"


def looks_like_openrouter_key(key: str) -> bool:
    return key.startswith("sk-or-") and len(key) > 20 and not re.search(r"\s", key)


def run(env_path: Path = HERE / ".env", example_path: Path = HERE / ".env.example", ask=getpass.getpass, confirm=input) -> int:
    if env_path.exists():
        answer = confirm(f"{env_path.name} already exists. Replace it? [y/N] ").strip().lower()
        if answer != "y":
            print("Nothing changed.")
            return 0
    key = ask("Paste your NEW OpenRouter key (you will not see it as you type) and press Enter: ").strip().strip("\"'")
    if not looks_like_openrouter_key(key):
        print("That does not look like an OpenRouter key (they start with sk-or-). Nothing was written.")
        return 1
    example = example_path.read_text(encoding="utf-8") if example_path.exists() else ""
    env_path.write_text(build_env_text(example, key), encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)                      # only you can read it (ignored on Windows)
    except OSError:
        pass
    print(f"Done. Your key is saved in {env_path.name} on this computer only. The key was not shown or sent anywhere.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
