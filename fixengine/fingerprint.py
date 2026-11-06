"""Bug fingerprint (plan 4.2): is this error the same bug again, or a new one?"""
from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

_FRAME = re.compile(r'File "([^"\n]+)", line (\d+), in ([^\n]+)')
_PYTEST_FRAME = re.compile(r"^([\w./\\-]+\.py):(\d+): ", re.M)
_JS_FRAME = re.compile(r"at (?:(\S+) )?\(?([^\s()]+):(\d+):\d+\)?")
# Java stack frame:  at com.shop.Orders.create(Orders.java:42)
_JAVA_FRAME = re.compile(r"at\s+([\w$.]+)\.([\w$<>]+)\(([\w$]+\.java):(\d+)\)")
# javac:  src/main/java/Orders.java:12: error: cannot find symbol
_JAVAC = re.compile(r"^([\w./\\-]+\.java):(\d+):\s*(?:error|warning)", re.M)
# tsc:  src/orders.ts(12,5): error TS2322: Type 'string' is not assignable ...   (also the colon form  src/a.ts:12:5 - error TS2322)
_TSC = re.compile(r"^([\w./\\-]+\.(?:tsx?|jsx?))(?:\((\d+),\d+\)|:(\d+):\d+)\s*[:\-]\s*error\s+(TS\d+)", re.M)
# static site checker:  index.html:14: unclosed <div>     css/site.css:30: missing }
_WEB = re.compile(r"^([\w./\\-]+\.(?:html?|css|scss|vue|svelte|js|mjs|json)):(\d+):\s", re.M)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b", re.I)
_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_QUOTED_ID = re.compile(r"(['\"])[A-Za-z0-9_\-]{16,}\1")


def normalize_message(message: str) -> str:
    """Strip numbers, IDs, addresses and timestamps so 'same error' compares equal."""
    text = str(message or "")[:2000]
    text = _TIME.sub("<time>", text)
    text = _UUID.sub("<id>", text)
    text = _ADDR.sub("<addr>", text)
    text = _QUOTED_ID.sub("<id>", text)
    text = _HEX.sub("<id>", text)
    text = _NUM.sub("<n>", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def app_frames(traceback: str) -> list[tuple[str, int, str]]:
    frames = [(p.replace("\\", "/"), int(n), fn.strip()) for p, n, fn in _FRAME.findall(traceback or "")]
    if not frames:
        frames = []
        for section in (traceback or "").split("Caused by:"):       # each chained cause prints its own innermost-first frames
            frames += [(file, int(n), fn.strip("<>")) for _cls, fn, file, n in _JAVA_FRAME.findall(section)][::-1]
    if not frames:
        frames = [(p.replace("\\", "/"), int(a or b), "") for p, a, b, _code in _TSC.findall(traceback or "")][::-1]
    if not frames:
        frames = [(p.replace("\\", "/"), int(n), "") for p, n in _JAVAC.findall(traceback or "")][::-1]
    if not frames:
        frames = [(p.replace("\\", "/"), int(n), "") for p, n in _WEB.findall(traceback or "")][::-1]
    if not frames:
        frames = [(p.replace("\\", "/"), int(n), "") for p, n in _PYTEST_FRAME.findall(traceback or "")]
    if not frames:
        frames = [(p.replace("\\", "/"), int(n), (fn or "").strip()) for fn, p, n in _JS_FRAME.findall(traceback or "")][::-1]
    mine = [f for f in frames if "site-packages" not in f[0] and "node_modules" not in f[0]
            and not f[0].startswith(("node:", "internal/"))]
    return mine or frames


def error_type(message: str, traceback: str, hint: str = "") -> str:
    if hint:
        return hint.strip()[:80]
    code = re.search(r"\berror\s+(TS\d+)", f"{traceback}\n{message}")
    if code:
        return code.group(1)                       # e.g. TS2322 (a TypeScript compiler error code)
    javac = re.search(r":\d+:\s*error:\s*([^\n]{3,60})", traceback or "")
    if javac:
        return re.sub(r"[^A-Za-z ]", "", javac.group(1)).strip().title().replace(" ", "")[:60] or "JavacError"
    web = _WEB.search(traceback or "")
    if web and not re.search(r"(?m)^\s*at\s", traceback or ""):
        tail = (traceback or "")[web.end():].split("\n", 1)[0]
        word = re.sub(r"[^A-Za-z ]", "", tail).strip().split(" ")[:3]
        return "Static_" + "".join(w.title() for w in word if w)[:40]
    # Java: the root cause is the LAST "Caused by:", otherwise the first exception line.
    java = re.findall(r"(?m)^(?:Caused by:\s*|Exception in thread \"[^\"]*\"\s+)?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*(?:Exception|Error))\b", traceback or "")
    if java and re.search(r"(?m)^\s+at\s+[\w$.]+\([\w$]+\.java:\d+\)", traceback or ""):
        return java[-1].split(".")[-1].split("$")[-1]
    js = re.search(r"(?m)^(?:Uncaught\s+)?([A-Z][A-Za-z]*(?:Error|Exception))\b:", traceback or "")
    if js and re.search(r"(?m)^\s+at\s", traceback or ""):          # Node/browser traces print the error on the FIRST line
        return js.group(1)
    lines = [ln for ln in (traceback or "").strip().splitlines() if ln.strip()]
    if lines:
        last = lines[-1].split(":", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][\w.]*", last):
            return last.split(".")[-1]
    return (str(message).split(":", 1)[0].strip() or "Error")[:80]


def fingerprint(message: str, traceback: str, *, exception_type: str = "", failing_tests=(), endpoint: str = "") -> dict:
    frames = app_frames(traceback)
    etype = error_type(message, traceback, exception_type)
    if frames:
        path, _line, func = frames[-1]
        where = f"{PurePosixPath(path).name}:{func}"   # no line number: edits shift lines
        files = sorted({PurePosixPath(f[0]).name for f in frames})[:6]
    else:
        where, files = "unknown", []
    norm = normalize_message(message)
    parts = [etype, where, norm, endpoint, ",".join(sorted(str(t) for t in failing_tests)[:10])]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return {"hash": digest, "error_type": etype, "where": where, "files": files,
            "normalized_message": norm[:300], "failing_tests": sorted(str(t) for t in failing_tests)[:20]}


def same_bug(a: dict, b: dict) -> bool:
    return bool(a) and bool(b) and a.get("hash") == b.get("hash")


def made_progress(before: dict, after: dict, failing_before: int | None = None, failing_after: int | None = None) -> bool:
    """Progress means: fewer failing tests, or a changed AND smaller error (plan 4.2 / 6.5 rule 2)."""
    if failing_before is not None and failing_after is not None and failing_after < failing_before:
        return True
    if same_bug(before, after):
        return False
    if after.get("error_type") != before.get("error_type") or after.get("where") != before.get("where"):
        return len(after.get("normalized_message", "")) <= len(before.get("normalized_message", "")) or \
               len(after.get("failing_tests", [])) < len(before.get("failing_tests", []))
    return len(after.get("normalized_message", "")) < len(before.get("normalized_message", ""))
