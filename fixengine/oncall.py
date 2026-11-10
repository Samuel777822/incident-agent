"""The on-call engineer's eyes (v3.1).

Models only return text. When the model needs to look before it fixes, it asks for one of a FIXED menu of look-ups and this code
runs it and returns the result as UNTRUSTED data. No tools, no shell, no secrets, no network except the live investigator on the
client's own public site and the public model lists.

    read_file   a range of lines of a repository file the engine downloaded (secret files were never downloaded)
    search      where a text / identifier appears in the repository
    open_page   the live investigator on a page of the client's own site
    run_journey the live investigator with steps (open, click, fill, expect text)
    check_model whether an AI model id is still served (OpenRouter / Groq / Anthropic public lists)
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from . import investigator, prompts

MAX_SEARCH_HITS = 20
MAX_PAGE_LOOKS = 2          # live pages per try (each is a real browser run on the sandbox server)


class LookupBudget:
    def __init__(self, pages: int = MAX_PAGE_LOOKS):
        self.pages = pages


def read_file(files: dict[str, str], path: str, start: int, end: int) -> str:
    path = str(path or "").strip().lstrip("./").replace("\\", "/")
    if path not in files:
        name = PurePosixPath(path).name.lower()
        similar = [p for p in files if PurePosixPath(p).name.lower() == name][:5] or [p for p in files if name and name in p.lower()][:5]
        return f"read_file {path}: no such file in the repository." + (f" Did you mean: {', '.join(similar)}?" if similar else "")
    lines = files[path].splitlines()
    start, end = max(1, start), min(len(lines), end)
    body = "\n".join(f"{n:>5}| {lines[n - 1]}" for n in range(start, end + 1))
    return f"read_file {path} lines {start}-{end} of {len(lines)}:\n{prompts.redact(body)}"


def search(files: dict[str, str], needle: str) -> str:
    needle = str(needle or "").strip()
    if len(needle) < 2:
        return "search: give at least 2 characters."
    low = needle.lower()
    hits = []
    for p in sorted(files):
        if PurePosixPath(p).suffix.lower() not in prompts.CODE_EXT and PurePosixPath(p).name not in prompts.MANIFESTS:
            continue
        for n, line in enumerate(files[p].splitlines(), start=1):
            if low in line.lower():
                hits.append(f"{p}:{n}: {line.strip()[:200]}")
                if len(hits) >= MAX_SEARCH_HITS:
                    break
        if len(hits) >= MAX_SEARCH_HITS:
            break
    if not hits:
        return f"search {needle!r}: not found anywhere in the repository."
    return f"search {needle!r} ({len(hits)} hits{', first ' + str(MAX_SEARCH_HITS) if len(hits) >= MAX_SEARCH_HITS else ''}):\n" + prompts.redact("\n".join(hits))


def check_model(model_id: str) -> str:
    from . import model_catalog
    model_id = str(model_id or "").strip()
    provider = "openrouter" if "/" in model_id else ("groq" if re.search(r"llama|mixtral|gemma|qwen|whisper", model_id, re.I) else "anthropic")
    listing = model_catalog.models(provider)
    if listing is None:
        return f"check_model {model_id}: the {provider} model list could not be read right now."
    ids = {m["id"] for m in listing}
    if model_id in ids:
        return f"check_model {model_id}: still served by {provider}."
    family = re.split(r"[/:-]", model_id.split("/")[-1])[0].lower()
    free = model_id.endswith(":free")
    near = sorted((i for i in ids if family and family in i.lower() and (i.endswith(":free") == free)), reverse=True)[:8]
    return (f"check_model {model_id}: NOT served by {provider} any more (retired or misspelt)."
            + (f" Similar {'free ' if free else ''}models served now: {', '.join(near)}." if near else ""))


def run_requests(requests: list[dict], *, files: dict[str, str], site_url: str = "", budget: LookupBudget | None = None,
                 investigate_fn=None) -> list[str]:
    budget = budget or LookupBudget()
    investigate_fn = investigate_fn or investigator.investigate
    out = []
    for req in requests:
        kind, value = req.get("kind"), req.get("value")
        try:
            if kind == "read_file":
                out.append(read_file(files, str(value), int(req.get("from_line", 1)), int(req.get("to_line", 250))))
            elif kind == "search":
                out.append(search(files, str(value)))
            elif kind == "check_model":
                out.append(check_model(str(value)))
            elif kind in ("open_page", "run_journey"):
                if not site_url:
                    out.append(f"{kind}: the address of the live site is not known (the owner can add it on the project page).")
                    continue
                if budget.pages <= 0:
                    out.append(f"{kind}: no more live page visits in this try; use what you have.")
                    continue
                budget.pages -= 1
                if kind == "open_page":
                    url, steps = investigator.page_url(site_url, str(value)), []
                else:
                    steps = investigator.clean_steps(value if isinstance(value, list) else [])
                    first = next((i for i, s in enumerate(steps) if "goto" in s), -1)
                    url = investigator.page_url(site_url, steps[first]["goto"] if first >= 0 else "")
                    if first >= 0:
                        steps = steps[:first] + steps[first + 1:]
                report = investigate_fn(url, steps)
                out.append(f"{kind} {url}:\n" + investigator.format_report(report))
            else:
                out.append(f"unknown request {kind!r} ignored.")
        except Exception as exc:     # a look-up must never break the try
            out.append(f"{kind}: could not be done ({type(exc).__name__}).")
    return out
