"""Pick the relevant files for a prompt (plan 5.5 / 6.7): traceback files, what they import, matching tests, manifests."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from . import prompts
from .fingerprint import app_frames

PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.*[\w.]*)\s+import|import\s+([\w.]+))", re.M)
JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\(\s*)['"](\.{1,2}/[^'"]+)['"]""")
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+?)(?:\.\*)?\s*;", re.M)
HTML_REF = re.compile(r"""(?:src|href)\s*=\s*['"]([^'"#?:]+?\.(?:js|mjs|css|html?))(?:[?#][^'"]*)?['"]""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]?([^'")\s;]+\.css)""", re.I)
TEST_NAME = re.compile(r"(^test_.*\.py$)|(_test\.py$)|(\.(test|spec)\.[jt]sx?$)|(^conftest\.py$)"
                       r"|(Tests?\.java$)|(^Test[A-Z]\w*\.java$)|(IT\.java$)", re.I)
JS_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", "/index.js", "/index.ts", "/index.tsx"]


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return bool(TEST_NAME.search(p.name)) or any(part.lower() in ("tests", "test", "__tests__", "spec") for part in p.parts[:-1])


def scan_repo(root: Path, *, max_files: int = 6000, max_bytes: int = 50 * 1024 * 1024) -> dict:
    """Read every plain-text source/manifest file once. Secret-looking files are never read."""
    files: dict[str, str] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in prompts.EXCLUDED_DIRS]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            if prompts.is_secret_path(rel):
                continue
            suffix = PurePosixPath(rel).suffix.lower()
            if suffix not in prompts.CODE_EXT and name not in prompts.MANIFESTS and suffix not in (".json", ".md", ".txt", ".cfg", ".toml", ".yml", ".yaml", ".html"):
                continue
            text = prompts.read_text_safe(Path(dirpath, name))
            if text is None:
                continue
            total += len(text)
            files[rel] = text
            if len(files) >= max_files or total > max_bytes:
                return {"files": files, "truncated": True}
    return {"files": files, "truncated": False}


def has_tests(files: dict[str, str]) -> bool:
    return any(is_test_path(p) and PurePosixPath(p).suffix in prompts.CODE_EXT for p in files)


def repo_tokens(files: dict[str, str]) -> int:
    return sum(prompts.estimate_tokens(t) for p, t in files.items() if PurePosixPath(p).suffix in prompts.CODE_EXT or p in prompts.MANIFESTS)


def _resolve_py(module: str, from_path: str, paths: set[str]) -> str | None:
    base = PurePosixPath(from_path).parent
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        target = base
        for _ in range(dots - 1):
            target = target.parent
        parts = [p for p in module.lstrip(".").split(".") if p]
        candidates = [target.joinpath(*parts) if parts else target]
    else:
        parts = module.split(".")
        candidates = [PurePosixPath(*parts), base.joinpath(*parts)]
    for c in candidates:
        for option in (f"{c}.py", f"{c}/__init__.py"):
            option = str(PurePosixPath(option))
            if option in paths:
                return option
    return None


def _resolve_js(spec: str, from_path: str, paths: set[str]) -> str | None:
    base = PurePosixPath(from_path).parent
    target = PurePosixPath(os.path.normpath(str(base / spec)).replace("\\", "/"))
    if str(target) in paths:
        return str(target)
    for ext in JS_EXTS:
        option = str(target) + ext
        if option in paths:
            return option
    return None


def _resolve_rel(spec: str, from_path: str, paths: set[str]) -> str | None:
    """A relative file reference from an HTML/CSS file (/abs paths are tried from the site root and from the page folder)."""
    base = PurePosixPath(from_path).parent
    for cand in ((base / spec.lstrip("/")), PurePosixPath(spec.lstrip("/"))):
        norm = os.path.normpath(str(cand)).replace("\\", "/")
        if norm in paths:
            return norm
    return None


def _resolve_java(qualified: str, paths: set[str]) -> str | None:
    tail = qualified.replace(".", "/") + ".java"
    for p in paths:
        if p == tail or p.endswith("/" + tail):
            return p
    return None


def imports_of(path: str, text: str, paths: set[str]) -> list[str]:
    found = []
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".java":
        for qualified in JAVA_IMPORT.findall(text):
            hit = _resolve_java(qualified, paths) or _resolve_java(qualified.rsplit(".", 1)[0], paths)
            if hit and hit != path:
                found.append(hit)
        return found
    if suffix in (".html", ".htm"):
        for spec in HTML_REF.findall(text):
            hit = _resolve_rel(spec, path, paths)
            if hit and hit != path:
                found.append(hit)
        return found
    if suffix in (".css", ".scss"):
        for spec in CSS_IMPORT.findall(text):
            hit = _resolve_rel(spec, path, paths)
            if hit and hit != path:
                found.append(hit)
        return found
    if path.endswith(".py"):
        for a, b in PY_IMPORT.findall(text):
            hit = _resolve_py(a or b, path, paths)
            if hit and hit != path:
                found.append(hit)
    elif PurePosixPath(path).suffix in prompts.CODE_EXT:
        for spec in JS_IMPORT.findall(text):
            hit = _resolve_js(spec, path, paths)
            if hit and hit != path:
                found.append(hit)
    return found


def _window(text: str, line_no: int, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    lo = hi = max(0, min(line_no - 1, len(lines) - 1))
    size = len(lines[lo]) + 1
    while True:
        grew = False
        if lo > 0 and size + len(lines[lo - 1]) + 1 <= max_chars:
            lo -= 1; size += len(lines[lo]) + 1; grew = True
        if hi < len(lines) - 1 and size + len(lines[hi + 1]) + 1 <= max_chars:
            hi += 1; size += len(lines[hi]) + 1; grew = True
        if not grew:
            break
    return f"# (file shortened: showing lines {lo + 1}-{hi + 1} of {len(lines)})\n" + "\n".join(lines[lo:hi + 1])


WORD = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")


def symbol_hits(files: dict[str, str], traceback: str, limit: int = 4) -> list[str]:
    """Source files that DEFINE a name mentioned in the error text (helps when the log has no file paths, e.g. a CI report)."""
    words = {w for w in WORD.findall(traceback or "")}
    scores: dict[str, int] = {}
    for path, text in files.items():
        if is_test_path(path) or PurePosixPath(path).suffix not in prompts.CODE_EXT:
            continue
        defined = set(re.findall(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)|^\s*class\s+([A-Za-z_]\w*)|function\s+([A-Za-z_]\w*)", text, re.M))
        if path.endswith(".java"):      # class/interface/enum/record names and method names
            defined |= {(a, b, "") for a, b in re.findall(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)|"
                                                          r"^\s*(?:public|private|protected|static|final|\s)+[\w<>\[\], ?]+\s+([a-z_]\w*)\s*\(", text, re.M)}
        elif path.endswith((".css", ".scss")):   # class and id selectors
            defined |= {(a, "", "") for a in re.findall(r"[.#]([A-Za-z_][\w-]*)\s*[{,:\s]", text)}
        names = {n for tup in defined for n in tup if n}
        hit = len(names & words)
        if hit:
            scores[path] = hit
    return [p for p, _ in sorted(scores.items(), key=lambda kv: (-kv[1], len(files[kv[0]])))][:limit]


def keyword_hits(files: dict[str, str], hints: list[str] | None, limit: int = 6) -> list[tuple[str, int]]:
    """Files that mention the words of an owner's report or the live evidence (a URL path, an element id, 'chapter'), best first,
    with the line of the first hit. This is what lets a plain-words report reach the right code when there is no traceback."""
    if not hints:
        return []
    scored = []
    for p, text in files.items():
        if is_test_path(p) or PurePosixPath(p).suffix.lower() not in prompts.CODE_EXT:
            continue
        low = text.lower()
        score, first_line = 0, 0
        for h in hints:
            n = low.count(h.lower())
            if n:
                score += min(n, 5) * (3 if ("/" in h or "_" in h or any(c.isupper() for c in h)) else 1)
                if not first_line:
                    first_line = low[:low.find(h.lower())].count("\n") + 1
        if score:
            scored.append((score, p, first_line))
    scored.sort(key=lambda x: (-x[0], len(files[x[1]])))
    return [(p, line) for _s, p, line in scored[:limit]]


def select(files: dict[str, str], traceback: str, budget_tokens: int, hints: list[str] | None = None) -> tuple[dict, dict]:
    """Return (source files to show and allow editing, test files shown as context only)."""
    paths = set(files)
    frames = app_frames(traceback)
    by_name: dict[str, list[str]] = {}
    for p in paths:
        by_name.setdefault(PurePosixPath(p).name, []).append(p)
    first: list[tuple[str, int]] = []
    for fpath, line, _fn in reversed(frames):      # innermost frame first
        candidates = [p for p in by_name.get(PurePosixPath(fpath).name, []) if not is_test_path(p)]
        # prefer the candidate whose tail matches the frame path
        candidates.sort(key=lambda p: -len(os.path.commonprefix([p[::-1], fpath[::-1]])))
        if candidates and candidates[0] not in [x[0] for x in first]:
            first.append((candidates[0], line))
    if not first:
        first = keyword_hits(files, hints)       # no stack trace (an owner's report, a browser problem): follow the words
    order: list[tuple[str, int]] = list(first)
    seen = {p for p, _ in order}
    for p in symbol_hits(files, traceback):
        if p not in seen:
            order.append((p, 0)); seen.add(p)
    for p, _line in list(first):
        for dep in imports_of(p, files[p], paths):
            if dep not in seen and not is_test_path(dep):
                order.append((dep, 0)); seen.add(dep)
    for name in sorted(prompts.MANIFESTS):
        for p in by_name.get(name, []):
            if p not in seen:
                order.append((p, 0)); seen.add(p)
    others = sorted((p for p in paths if p not in seen and not is_test_path(p) and PurePosixPath(p).suffix in prompts.CODE_EXT),
                    key=lambda p: len(files[p]))
    order.extend((p, 0) for p in others)
    chosen: dict[str, str] = {}
    used = 0
    per_file_cap = max(2000, budget_tokens * 4 // 3)
    for p, line in order:
        text = _window(files[p], line, per_file_cap)
        cost = prompts.estimate_tokens(text)
        if used + cost > budget_tokens * 0.8:
            if p in [x[0] for x in first] and not chosen.get(p):
                text = _window(files[p], line, max(1500, (budget_tokens - used) * 4))
                cost = prompts.estimate_tokens(text)
            else:
                continue
        chosen[p] = text
        used += cost
    stems = {PurePosixPath(p).stem.replace("test_", "").replace("_test", "") for p in chosen}
    tests: dict[str, str] = {}
    test_budget = int(budget_tokens * 0.2)
    for p in sorted(paths):
        if is_test_path(p) and PurePosixPath(p).suffix in prompts.CODE_EXT:
            stem = PurePosixPath(p).stem.replace("test_", "").replace("_test", "").replace(".test", "").replace(".spec", "")
            if stem in stems or PurePosixPath(p).name == "conftest.py":
                cost = prompts.estimate_tokens(files[p])
                if cost <= test_budget:
                    tests[p] = files[p]; test_budget -= cost
    return chosen, tests
