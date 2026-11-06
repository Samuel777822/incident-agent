"""Read a local `.env` file into the environment (no extra package needed).

Why: so you paste your API key into ONE file on your own computer instead of typing it into every terminal.
Rules: real environment variables always win (so Render's environment screen is never overridden), nothing is printed,
and the file is listed in .gitignore and .dockerignore so it can never be committed or copied into an image.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED: set[str] = set()


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not (key[0].isalpha() or key[0] == "_") or not all(c.isalnum() or c == "_" for c in key):
            continue
        if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_env_file(path: str | os.PathLike | None = None) -> list[str]:
    """Load KEY=VALUE lines from the .env next to the project (or from `path`). Returns the names it set. Never overrides."""
    candidates = [Path(path)] if path else [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for file in candidates:
        try:
            if not file.is_file():
                continue
            values = parse(file.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
        set_now = []
        for key, value in values.items():
            if value and not os.environ.get(key):          # empty placeholders and existing variables are left alone
                os.environ[key] = value
                set_now.append(key)
                _LOADED.add(key)
        return set_now
    return []
