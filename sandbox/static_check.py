"""Static website check, run INSIDE the sandbox (standard library only, plus `node` when it is installed).

    python static_check.py [ROOT] [--site-root DIR]

Looks for the mistakes that break a plain HTML/CSS/JS site and that vibe-coded pages are full of:

  * HTML: unclosed or stray tags, unterminated attribute quotes, unclosed comments
  * local files that a page points to (stylesheets, scripts, images, links) but that do not exist
  * CSS: unbalanced braces/parentheses, unterminated strings or comments, declarations without a colon,
    missing @import files
  * JavaScript (linked files and inline <script> blocks): syntax errors, via `node --check`
  * JSON files that do not parse

Every problem is printed as   path:line: message   and the last line is   static_check: N errors in M files.
Exit code 0 = clean, 1 = problems found. This is a syntax/structure check, not a visual or behavioural test.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

SKIP_DIRS = {"node_modules", ".git", ".fx_deps", ".fx_out", ".fx_m2", ".fx_gradle", "dist", "build", "target", ".next",
             "__pycache__", "venv", ".venv", "coverage", "vendor", "templates"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr",
        "command", "keygen"}
# End tags the HTML spec lets authors leave out. A missing </li> or </p> is not a bug.
OPTIONAL_END = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup", "colgroup",
                "caption", "rt", "rp", "html", "body", "head"}
FILE_EXT = re.compile(r"\.(?:html?|css|js|mjs|json|png|jpe?g|gif|svg|webp|ico|avif|pdf|mp3|mp4|webm|woff2?|ttf|otf|txt|xml)$", re.I)
SKIP_REF = re.compile(r"^(?:#|mailto:|tel:|sms:|javascript:|data:|blob:|about:|https?:|//|\{\{|\{%|<%|\$\{|\{)", re.I)
REF_ATTRS = {"link": "href", "script": "src", "img": "src", "source": "src", "iframe": "src", "video": "src", "audio": "src",
             "a": "href", "form": "action", "embed": "src"}
JS_TYPES = {"", "text/javascript", "application/javascript", "module"}
MAX_FILES, MAX_BYTES = 2000, 1_500_000


def _lines_before(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------------------------------------------------------- HTML
class PageChecker(HTMLParser):
    def __init__(self, rel: str, page_dir: Path, site_root: Path, errors: list, inline_js: list, inline_css: list):
        super().__init__(convert_charrefs=True)
        self.rel, self.page_dir, self.site_root = rel, page_dir, site_root
        self.errors, self.inline_js, self.inline_css = errors, inline_js, inline_css
        self.stack: list[tuple[str, int]] = []
        self._script: tuple[int, bool] | None = None
        self._style: int | None = None
        self._buf: list[str] = []
        self.in_svg = 0

    def err(self, line: int, msg: str) -> None:
        self.errors.append((self.rel, line, msg))

    # -- references to other files
    def _check_ref(self, tag: str, attrs: dict, line: int) -> None:
        attr = REF_ATTRS.get(tag)
        value = (attrs.get(attr) or "").strip() if attr else ""
        if tag == "link" and attrs.get("rel", "").lower() in ("preconnect", "dns-prefetch", "canonical", "alternate"):
            return
        if not value or SKIP_REF.match(value):
            return
        clean = unquote(re.split(r"[?#]", value, maxsplit=1)[0])
        if not clean:
            return
        if tag == "a" and not FILE_EXT.search(clean) and not clean.endswith("/"):
            return                                  # clean URLs like /about are the server's business, not a missing file
        base = self.site_root if clean.startswith("/") else self.page_dir
        target = (base / clean.lstrip("/")).resolve()
        if target.exists() and (target.is_file() or (target / "index.html").exists() or clean.endswith("/")):
            return
        self.err(line, f"missing file {value}")

    # -- tags
    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        a = {k: (v if v is not None else "") for k, v in attrs}
        raw = self.get_starttag_text() or ""
        if raw.count('"') % 2 == 1 or raw.count("'") % 2 == 1 and "=" in raw and not re.search(r"\w'\w", raw):
            self.err(line, f"unterminated attribute quote in <{tag}>")
        if tag == "svg":
            self.in_svg += 1
        if tag in REF_ATTRS:
            self._check_ref(tag, a, line)
        if tag == "script":
            if not a.get("src") and a.get("type", "").lower() in JS_TYPES:
                self._script = (line, a.get("type", "").lower() == "module")
            self._buf = []
        elif tag == "style":
            self._style, self._buf = line, []
        if tag in VOID:
            return
        self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        line = self.getpos()[0]
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag in REF_ATTRS:
            self._check_ref(tag, a, line)

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if tag == "svg" and self.in_svg:
            self.in_svg -= 1
        if tag in ("script", "style"):
            text = "".join(self._buf)
            if tag == "script" and self._script is not None:
                self.inline_js.append((self.rel, self._script[0], text, self._script[1]))
            elif tag == "style" and self._style is not None:
                self.inline_css.append((self.rel, self._style, text))
            self._script, self._style, self._buf = None, None, []
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for left_tag, left_line in self.stack[i + 1:]:
                    if left_tag not in OPTIONAL_END:
                        self.err(left_line, f"unclosed <{left_tag}> (still open at </{tag}> on line {line})")
                del self.stack[i:]
                return
        self.err(line, f"unexpected closing </{tag}> with no matching open tag")

    def handle_data(self, data):
        if self._script is not None or self._style is not None:
            self._buf.append(data)

    def finish(self) -> None:
        for tag, line in self.stack:
            if tag not in OPTIONAL_END:
                self.err(line, f"unclosed <{tag}>")


def check_html(path: Path, rel: str, site_root: Path, errors: list, inline_js: list, inline_css: list) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    opens, closes = [m.start() for m in re.finditer(r"<!--", text)], text.count("-->")
    if len(opens) > closes:
        errors.append((rel, _lines_before(text, opens[closes]), "unclosed comment <!--"))
    checker = PageChecker(rel, path.parent, site_root, errors, inline_js, inline_css)
    try:
        checker.feed(text)
        checker.close()
    except Exception as exc:                        # the parser itself gave up: report it as a problem with the page
        errors.append((rel, checker.getpos()[0], f"HTML could not be parsed ({type(exc).__name__})"))
        return
    checker.finish()


# ----------------------------------------------------------------------------------------------------------------- CSS
def check_css(text: str, rel: str, errors: list, first_line: int = 1, base_dir: Path | None = None) -> None:
    n, i, line = len(text), 0, first_line
    blocks: list[int] = []
    parens: list[int] = []
    pending: list[str] = []
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                errors.append((rel, line, "unterminated comment /*"))
                return
            line += text.count("\n", i, end)
            i = end + 2
            continue
        if c in "\"'":
            j, start_line = i + 1, line
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n":
                    errors.append((rel, start_line, "unterminated string in CSS"))
                    break
                j += 1
            else:
                pass
            if j >= n:
                errors.append((rel, start_line, "unterminated string in CSS"))
                return
            pending.append(text[i:j + 1])
            i = j + 1
            continue
        if text.startswith("url(", i) and not re.match(r"url\(\s*['\"]", text[i:i + 12]):
            end = text.find(")", i)
            if end == -1:
                errors.append((rel, line, "unclosed url("))
                return
            pending.append(text[i:end + 1])
            i = end + 1
            continue
        if c == "(":
            parens.append(line)
        elif c == ")":
            if not parens:
                errors.append((rel, line, "unbalanced ) in CSS"))
            else:
                parens.pop()
        elif c == "{":
            blocks.append(line)
            pending = []
        elif c in ";}":
            decl = "".join(pending).strip()
            if decl and ":" not in decl and not decl.startswith(("@", "}")) and blocks:
                errors.append((rel, line, f"declaration without ':' near '{decl[:40]}'"))
            if decl.startswith("@import") and base_dir is not None:
                m = re.search(r"""@import\s+(?:url\()?\s*['"]?([^'")\s;]+)""", decl)
                if m and not SKIP_REF.match(m.group(1)) and not (base_dir / m.group(1)).exists():
                    errors.append((rel, line, f"missing file {m.group(1)}"))
            pending = []
            if c == "}":
                if not blocks:
                    errors.append((rel, line, "unexpected } with no matching {"))
                else:
                    blocks.pop()
        else:
            pending.append(c)
        i += 1
    for opened in blocks:
        errors.append((rel, opened, "missing } (block opened here is never closed)"))
    for opened in parens:
        errors.append((rel, opened, "missing ) in CSS"))


# ------------------------------------------------------------------------------------------------------------------- JS
def _node_check(source: Path) -> tuple[int, str] | None:
    """Return (line, message) for a syntax error, or None if the file parses."""
    proc = subprocess.run(["node", "--check", str(source)], capture_output=True, text=True, timeout=30)
    if proc.returncode == 0:
        return None
    err = proc.stderr or ""
    m = re.search(r":(\d+)\n", err)
    msg = re.search(r"((?:Syntax|Reference|Type)Error:[^\n]*)", err)
    return (int(m.group(1)) if m else 1), (msg.group(1) if msg else (err.strip().splitlines() or ["syntax error"])[-1][:160])


def check_js_file(path: Path, rel: str, errors: list) -> None:
    hit = _node_check(path)
    if hit:
        errors.append((rel, hit[0], hit[1]))


def check_inline_js(rel: str, first_line: int, code: str, is_module: bool, errors: list, tmp: Path) -> None:
    if not code.strip():
        return
    target = tmp / ("inline.mjs" if is_module else "inline.js")
    target.write_text(code, encoding="utf-8")
    hit = _node_check(target)
    if hit:
        errors.append((rel, first_line + hit[0] - 1, hit[1] + " (inline <script>)"))


# ------------------------------------------------------------------------------------------------------------------- run
def iter_files(root: Path, excludes=()):
    count = 0
    root = Path(root)
    excluded = {(root / e).resolve() for e in excludes if e}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".fx_")
                             and Path(dirpath, d).resolve() not in excluded)
        for name in sorted(filenames):
            p = Path(dirpath, name)
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            count += 1
            if count > MAX_FILES:
                return
            yield p


def check_site(root: Path, site_root: Path | None = None, excludes=()) -> tuple[list, int]:
    root = Path(root).resolve()
    site_root = Path(site_root).resolve() if site_root else root
    errors: list = []
    inline_js: list = []
    inline_css: list = []
    checked = 0
    have_node = shutil.which("node") is not None
    tmp = Path(tempfile.mkdtemp(prefix="fx-static-"))
    try:
        for p in iter_files(root, excludes):
            rel = p.relative_to(root).as_posix()
            suffix = p.suffix.lower()
            if suffix in (".html", ".htm"):
                checked += 1
                check_html(p, rel, site_root, errors, inline_js, inline_css)
            elif suffix in (".css",):
                checked += 1
                check_css(p.read_text(encoding="utf-8", errors="replace"), rel, errors, base_dir=p.parent)
            elif suffix in (".js", ".mjs", ".cjs") and have_node and not p.name.endswith(".min.js"):
                checked += 1
                check_js_file(p, rel, errors)
            elif suffix == ".json" and p.name not in ("package-lock.json",):
                checked += 1
                try:
                    json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
                except ValueError as exc:
                    errors.append((rel, getattr(exc, "lineno", 1) or 1, f"invalid JSON: {str(exc)[:80]}"))
        for rel, line, text in inline_css:
            check_css(text, rel, errors, first_line=line)
        if have_node:
            for rel, line, code, is_module in inline_js:
                check_inline_js(rel, line, code, is_module, errors, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    errors.sort(key=lambda e: (e[0], e[1]))
    return errors, checked


def main(argv: list[str]) -> int:
    """static_check.py [ROOT] [--site-root DIR] [--exclude DIR ...]   (--exclude skips another stack's folder in a mixed repo)"""
    site_root, excludes, args = None, [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--site-root", "--exclude") and i + 1 < len(argv):
            if a == "--site-root":
                site_root = Path(argv[i + 1])
            else:
                excludes.append(argv[i + 1].strip("/"))
            i += 2
            continue
        if not a.startswith("--"):
            args.append(a)
        i += 1
    root = Path(args[0]) if args else Path(".")
    errors, checked = check_site(root, site_root, excludes)
    for rel, line, msg in errors:
        print(f"{rel}:{line}: {msg}")
    print(f"static_check: {len(errors)} errors in {checked} files" + ("" if shutil.which("node") else "  (JavaScript syntax is checked by the browser journeys and your GitHub tests)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
