"""Browser journeys: tiny scripted visits to a static site (open a page, click a button, expect something), run in a real headless
browser inside the sandbox with NO network. They are how the agent PROVES a user-facing fix ("the button now does something"),
not just that the code builds.

Generated for free from the site's own HTML (no model call); a problem seen in the live site (a dead click, a failing page) adds
a journey aimed at exactly that element. The file is written to `.fx_journeys.json` in the scratch copy of the repo and is never
committed to the customer's repository.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

FILE = ".fx_journeys.json"
STEP_KEYS = {"goto", "click", "fill", "expect_text", "expect_visible", "expect_change", "expect_no_page_errors", "wait"}
MAX_JOURNEYS = 8
MAX_STEPS = 10
BUTTON = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.I | re.S)
ATTR_ID = re.compile(r"""\bid\s*=\s*["']([A-Za-z][\w:-]{0,60})["']""", re.I)
TAGS = re.compile(r"<[^>]+>")
SKIP_PAGE = re.compile(r"(^|/)(node_modules|vendor|dist|build|coverage|\.git)/", re.I)


def _label(inner: str) -> str:
    return " ".join(TAGS.sub(" ", inner).split())[:40]


def _page_url(path: str, root: str) -> str:
    rel = PurePosixPath(path).relative_to(root) if root and path.startswith(root + "/") else PurePosixPath(path)
    return "/" + rel.as_posix()


def site_root(files: dict[str, str]) -> str:
    """The folder that holds the site (where index.html lives); '' when it is the repo root."""
    pages = sorted((p for p in files if p.lower().endswith((".html", ".htm")) and not SKIP_PAGE.search(p)), key=lambda p: (p.count("/"), p))
    if not pages:
        return ""
    index = next((p for p in pages if PurePosixPath(p).name.lower() == "index.html"), pages[0])
    return PurePosixPath(index).parent.as_posix().lstrip(".")


def generate(files: dict[str, str], *, evidence: dict | None = None) -> dict | None:
    """{'root': folder, 'journeys': [...]} or None when the repo has no HTML page."""
    root = site_root(files)
    pages = sorted((p for p in files if p.lower().endswith((".html", ".htm")) and not SKIP_PAGE.search(p)
                    and (not root or p.startswith(root + "/"))), key=lambda p: (p.count("/"), p))[:3]
    if not pages:
        return None
    journeys: list[dict] = []
    ev = evidence or {}
    target = str(ev.get("dom") or "")
    page = str(ev.get("page") or "")
    path = "/" + page.split("://", 1)[-1].split("/", 1)[-1].split("?")[0].split("#")[0].lstrip("/") if page else "/"
    if ev.get("kind") in ("dead_click", "ui_error_text") and target:
        sel = re.search(r"#([\w:-]+)", target)
        text = re.search(r'"([^"]{1,40})"', target)
        selector = f"#{sel.group(1)}" if sel else (f"text={text.group(1)}" if text else "")
        if selector:
            journeys.append({"name": f"Reported element reacts: {target[:60]}",
                             "steps": [{"goto": path or "/"}, {"click": selector, "expect_change": True}]})
    for pg in pages:
        url = _page_url(pg, root)
        journeys.append({"name": f"{url} opens without errors", "steps": [{"goto": url}, {"expect_no_page_errors": True}]})
        for attrs, inner in BUTTON.findall(files.get(pg, ""))[:4]:
            if re.search(r'type\s*=\s*["\']submit["\']|\bdisabled\b', attrs, re.I):
                continue
            ident, label = ATTR_ID.search(attrs), _label(inner)
            selector = f"#{ident.group(1)}" if ident else (f"text={label}" if label else "")
            if selector:
                journeys.append({"name": f"{url}: button {label or ident.group(1)} reacts",
                                 "steps": [{"goto": url}, {"click": selector, "expect_change": True}, {"expect_no_page_errors": True}]})
    journeys = [j for j in (validate(j) for j in journeys) if j][:MAX_JOURNEYS]
    return {"root": root, "journeys": journeys} if journeys else None


def validate(journey: dict) -> dict | None:
    """Only known step types, short strings, a bounded number of steps."""
    if not isinstance(journey, dict) or not isinstance(journey.get("steps"), list):
        return None
    steps = []
    for st in journey["steps"][:MAX_STEPS]:
        if not isinstance(st, dict) or not st or not set(st) <= STEP_KEYS | {"to", "text"}:
            return None
        clean = {k: (v if isinstance(v, bool) else str(v)[:200]) for k, v in st.items()}
        steps.append(clean)
    return {"name": str(journey.get("name", "journey"))[:100], "steps": steps} if steps else None


def write(root_dir: Path, spec: dict) -> bool:
    try:
        (Path(root_dir) / FILE).write_text(json.dumps(spec, indent=1), encoding="utf-8")
        return True
    except OSError:
        return False


def prepare(root_dir: Path, files: dict[str, str], *, evidence: dict | None = None) -> bool:
    spec = generate(files, evidence=evidence)
    return bool(spec) and write(root_dir, spec)
