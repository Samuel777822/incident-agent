"""The big picture (v3.1): what an on-call engineer knows about a project before reading any single file.

Built for free from the downloaded repository (no model call) and sent as the first, CACHED prompt block, so every try sees it at
cache-read prices: the file tree, the stacks and entry points, the pages, every outside host and AI model id the code uses, the
NAMES of the environment variables it reads (never their values), and this project's own history (earlier cases and what fixed
them). It is rebuilt from the branch on every try, so it is always current after a push.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from . import prompts

URL_RE = re.compile(r"https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s'\"`<>)]*)?")
ENV_RE = [re.compile(r"process\.env\.([A-Z][A-Z0-9_]{1,60})"), re.compile(r"process\.env\[['\"]([A-Z][A-Z0-9_]{1,60})['\"]\]"),
          re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]{1,60})['\"]"), re.compile(r"os\.environ\[['\"]([A-Z][A-Z0-9_]{1,60})['\"]\]"),
          re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]{1,60})"), re.compile(r"System\.getenv\(\s*\"([A-Z][A-Z0-9_]{1,60})\"")]
MODEL_RE = re.compile(r"['\"`]((?:[a-z0-9-]+/)?(?:gpt|claude|gemini|llama|mistral|mixtral|qwen|deepseek|gemma|phi|command|grok|kimi|glm)"
                      r"[a-zA-Z0-9.:_/-]{1,80})['\"`]")
ROUTE_RE = [re.compile(r"@(?:app|router|bp|blueprint)\.(?:get|post|put|delete|patch|route)\(\s*['\"]([^'\"]{1,120})['\"]"),
            re.compile(r"\b(?:app|router)\.(?:get|post|put|delete|patch|all|use)\(\s*['\"`](/[^'\"`]{0,120})['\"`]"),
            re.compile(r"@(?:Get|Post|Put|Delete|Request)Mapping\(\s*(?:value\s*=\s*)?\"([^\"]{1,120})\"")]
ENTRY_NAMES = {"index.html", "app.py", "main.py", "server.py", "wsgi.py", "manage.py", "server.js", "app.js", "index.js", "main.js",
               "main.ts", "index.ts", "server.ts", "App.jsx", "App.tsx", "main.jsx", "main.tsx", "Application.java", "Main.java"}
FRAMEWORK_HINTS = (("react", "React"), ("next", "Next.js"), ("vue", "Vue"), ("svelte", "Svelte"), ("express", "Express"),
                   ("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"), ("spring-boot", "Spring Boot"),
                   ("vite", "Vite"), ("@angular/core", "Angular"))
SKIP_HOSTS = {"www.w3.org", "w3.org", "schemas.xmlsoap.org", "json-schema.org", "example.com", "localhost", "fonts.googleapis.com",
              "fonts.gstatic.com", "github.com", "www.apache.org", "opensource.org", "creativecommons.org"}


def build(files: dict[str, str], *, history: list[dict] | None = None, site_url: str = "", max_chars: int = 9000) -> str:
    paths = sorted(files)
    lines: list[str] = []
    if site_url:
        lines.append(f"Live site: {site_url}")
    blob_manifest = " ".join(files.get(p, "") for p in paths if PurePosixPath(p).name in ("package.json", "requirements.txt", "pyproject.toml", "pom.xml"))
    frameworks = [name for key, name in FRAMEWORK_HINTS if re.search(r"[\"'\s]" + re.escape(key) + r"[\"'=<>~^\s]", blob_manifest, re.I)]
    exts: dict[str, int] = {}
    for p in paths:
        exts[PurePosixPath(p).suffix.lower() or "(none)"] = exts.get(PurePosixPath(p).suffix.lower() or "(none)", 0) + 1
    lines.append("Files: " + ", ".join(f"{k} x{v}" for k, v in sorted(exts.items(), key=lambda kv: -kv[1])[:10]) + f" ({len(paths)} total)")
    if frameworks:
        lines.append("Frameworks: " + ", ".join(frameworks))
    entries = [p for p in paths if PurePosixPath(p).name in ENTRY_NAMES and p.count("/") <= 2]
    if entries:
        lines.append("Entry points: " + ", ".join(entries[:12]))
    pages = [p for p in paths if p.lower().endswith((".html", ".htm")) and "node_modules" not in p][:25]
    if pages:
        lines.append("Pages: " + ", ".join(pages))
    hosts: dict[str, set] = {}
    envs: set[str] = set()
    models: dict[str, set] = {}
    routes: list[str] = []
    for p in paths:
        if PurePosixPath(p).suffix.lower() not in prompts.CODE_EXT:
            continue
        text = files[p]
        for m in URL_RE.finditer(text):
            host = m.group(1).lower()
            if host in SKIP_HOSTS or host.endswith((".svg", ".png")):
                continue
            hosts.setdefault(host, set()).add(p)
        for rx in ENV_RE:
            envs.update(rx.findall(text))
        for m in MODEL_RE.finditer(text):
            mid = m.group(1)
            if len(mid) >= 5 and not mid.endswith((".js", ".py", ".css")):
                models.setdefault(mid, set()).add(p)
        for rx in ROUTE_RE:
            for r in rx.findall(text):
                if len(routes) < 40:
                    routes.append(f"{r} ({p})")
    if hosts:
        lines.append("Outside services the code calls:")
        lines += [f"- {h} (in {', '.join(sorted(where)[:3])})" for h, where in sorted(hosts.items(), key=lambda kv: -len(kv[1]))[:20]]
    if models:
        lines.append("AI model ids in the code:")
        lines += [f"- {mid} (in {', '.join(sorted(where)[:3])})" for mid, where in sorted(models.items())[:15]]
    if routes:
        lines.append("Server routes: " + "; ".join(routes[:40]))
    if envs:
        lines.append("Environment variables read (names only): " + ", ".join(sorted(envs)[:40]))
    if history:
        lines.append("Earlier cases in this project (newest first):")
        for h in history[:6]:
            lines.append(f"- {str(h.get('when', ''))[:10]} {str(h.get('signature', ''))[:90]} -> {str(h.get('root_cause', '') or 'no diagnosis')[:220]}")
    tree = [p for p in paths if not any(part in prompts.EXCLUDED_DIRS for part in PurePosixPath(p).parts)]
    lines.append("File tree:")
    budget = max_chars - sum(len(x) + 1 for x in lines) - 40
    for p in tree:
        entry = f"  {p} ({len(files[p]) // 1024 or '<1'} KB)"
        if budget - len(entry) < 0:
            lines.append(f"  ... and {len(tree) - tree.index(p)} more files")
            break
        lines.append(entry)
        budget -= len(entry) + 1
    return "\n".join(lines)[:max_chars]


def hint_words(*texts: str) -> list[str]:
    """Words from a report / evidence that are worth searching the code for ('isaiah', 'chapter', '/api/verses', 'sendBtn')."""
    import cases
    out: list[str] = []
    for t in texts:
        for w in re.findall(r"[A-Za-z_][\w./-]{2,40}", t or ""):
            low = w.lower().strip("./-")
            if len(low) < 3 or low in cases._STOP or low in ("https", "http", "www", "com", "get", "post"):
                continue
            if low not in out:
                out.append(low)
    return out[:20]
