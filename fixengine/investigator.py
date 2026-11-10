"""The live investigator (v3.1): the agent looks at the client's REAL site, like an on-call engineer opening the page.

    investigate(url, steps)  -> evidence report (dict)

Where it runs:
  * remote (production): POST to the sandbox server's signed /investigate endpoint. It starts the browser image with network
    and runs sandbox/investigate.py: headless Chromium opens the public page, records failed requests, console and page errors
    and visible error messages, and runs the steps of a short journey (open, click, expect text).
  * docker (a machine with Docker): the same container, started here.
  * neither, or the browser image is missing: an honest plain page fetch ("I could not open your site in a real browser").

Used for: an owner's report ("Isaiah 1 is not loading"), problems the monitor saw, the model's own "open this page" requests,
and the check AFTER a fix is pushed (is the live site better, the same, or worse?).

Safety: public internet addresses only (private, loopback, link-local and reserved are refused, here AND in the container),
one job at a time on the sandbox server, a time limit and a memory limit. No cookies, no logins, no screenshots stored.
Everything it returns is page content, so it is shown to the model as UNTRUSTED data.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from . import sandbox

STEP_KEYS = {"goto", "click", "fill", "text", "expect_text", "expect_visible", "wait"}
MAX_STEPS = 10
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.I | re.S)


def enabled() -> bool:
    return os.getenv("FIX_INVESTIGATOR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


# ---- input checks -------------------------------------------------------------------------------------------------------
def clean_steps(steps) -> list[dict]:
    """Only the allowed step types, short strings, at most 10 steps. Anything else is dropped (never executed)."""
    out = []
    for st in (steps or [])[:MAX_STEPS]:
        if not isinstance(st, dict) or not st or not set(st) <= STEP_KEYS:
            continue
        out.append({k: (v if isinstance(v, bool) else str(v)[:200]) for k, v in st.items()})
    return out


def page_url(base_url: str, page: str = "") -> str:
    """The page to open: the evidence page / reported page on the client's own site, else the site address itself."""
    base = str(base_url or "").strip()
    if not base:
        return ""
    page = str(page or "").strip()
    if not page:
        return base
    if "://" in page:
        same = (urlparse(page).hostname or "").lower() == (urlparse(base).hostname or "").lower()
        return page.split("#")[0] if same else base
    return urljoin(base if base.endswith("/") else base + "/", page.lstrip("/"))


def _safe(url: str) -> str:
    try:
        import site_probe
        return site_probe.safe_url(url)
    except Exception:
        return ""


# ---- the portal side ---------------------------------------------------------------------------------------------------------
def investigate(url: str, steps=None, *, cfg: dict | None = None, exec_fn=None, http_post=None, fetcher=None) -> dict:
    """The evidence report for one page. Never raises."""
    if not enabled():
        return {"ok": False, "mode": "off", "reason": "the live investigator is switched off"}
    safe = _safe(url)
    if not safe:
        return {"ok": False, "mode": "refused", "url": str(url)[:300], "reason": "that address is not a public website, so it was not opened"}
    steps = clean_steps(steps)
    from . import config as fx_config
    cfg = cfg or fx_config.load()
    mode = os.getenv("FIXENGINE_SANDBOX_MODE") or cfg["sandbox"]["mode"]
    report = None
    if mode == "remote":
        report = _remote(safe, steps, http_post=http_post)
    elif mode == "docker":
        report = run_in_docker({"url": safe, "steps": steps}, cfg, exec_fn=exec_fn)
    if not report or (not report.get("ok") and report.get("mode") in ("unavailable", "no_image")):
        why = (report or {}).get("reason") or "no browser is set up"
        report = plain_fetch(safe, fetcher=fetcher)
        report["note"] = f"I could not open your site in a real browser ({why}), so this is a plain page fetch only."
    return report


def _remote(url: str, steps: list, *, http_post=None) -> dict:
    base, secret = os.getenv("FIXENGINE_SANDBOX_URL", "").rstrip("/"), os.getenv("FIXENGINE_SANDBOX_SECRET", "")
    if not base or not secret:
        return {"ok": False, "mode": "unavailable", "reason": "the sandbox server is not configured"}
    body = json.dumps({"url": url, "steps": steps, "allowed_host": (urlparse(url).hostname or "").lower()}).encode()
    ts = str(int(time.time()))
    post = http_post or httpx.post
    try:
        resp = post(base + "/investigate", content=body, timeout=150,
                    headers={"X-Timestamp": ts, "X-Signature": sandbox.sign(secret, ts, body), "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        return {"ok": False, "mode": "unavailable", "reason": f"the sandbox server did not answer ({type(exc).__name__})"}
    if resp.status_code != 200:
        # 400 from an older sandbox_service.py that has no /investigate yet: say so plainly.
        return {"ok": False, "mode": "unavailable", "reason": f"the sandbox server answered HTTP {resp.status_code} (update sandbox_service.py)"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "mode": "unavailable", "reason": "the sandbox server sent an unreadable answer"}
    return data if isinstance(data, dict) else {"ok": False, "mode": "unavailable", "reason": "unreadable answer"}


# ---- the sandbox-server side (also used in docker mode) -------------------------------------------------------------------
_NO_IMAGE = re.compile(r"unable to find image|pull access denied|no such image|manifest unknown|repository does not exist", re.I)


def run_in_docker(spec: dict, cfg: dict, *, exec_fn=None) -> dict:
    """Start the browser image WITH network for one page, read the one JSON line it prints. One call = one container."""
    sb = cfg["sandbox"]
    image = sb.get("image_browser")
    url = str(spec.get("url") or "")
    if not image:
        return {"ok": False, "mode": "no_image", "reason": "the browser image is not configured"}
    if not _safe(url):
        return {"ok": False, "mode": "refused", "reason": "not a public website address"}
    clean = {"url": url, "steps": clean_steps(spec.get("steps")),
             "allowed_host": (urlparse(url).hostname or "").lower()}
    exec_fn = exec_fn or sandbox._default_exec
    work = Path(tempfile.mkdtemp(prefix="fx-inv-", dir=os.getenv("FIXENGINE_SCRATCH") or None))
    try:
        (work / "spec.json").write_text(json.dumps(clean), encoding="utf-8")
        os.chmod(work, 0o777)
        os.chmod(work / "spec.json", 0o666)
        icfg = {"sandbox": {**sb, "memory": sb.get("investigate_memory", "1g"), "cpus": sb.get("investigate_cpus", "1"),
                            "pids": sb.get("investigate_pids", 512)}}
        name = f"fx-inv-{uuid.uuid4().hex[:10]}"
        argv = sandbox.docker_run_argv(name=name, image=image, workdir=str(work), command="python3 /opt/investigate.py /work/spec.json",
                                       network=True, cfg=icfg, env={"HOME": "/tmp"},
                                       ro_mounts=[(str(sandbox.SANDBOX_DIR / "investigate.py"), "/opt/investigate.py")])
        net = str(sb.get("investigate_network") or "bridge")
        if net != "bridge" and "--network" in argv:
            argv[argv.index("--network") + 1] = net
        timeout = int(sb.get("investigate_timeout_seconds", 90))
        rc, out, timed_out = exec_fn(argv, timeout + 15)
        if rc != 0 and net != "bridge" and re.search(r"network .* not found", out or "", re.I):
            # The locked-down network from DEPLOY.md was not created yet: still work (the container checks every address too).
            argv[argv.index("--network") + 1] = "bridge"
            rc, out, timed_out = exec_fn(argv, timeout + 15)
        if timed_out:
            exec_fn(["docker", "kill", name], 15)
            return {"ok": False, "mode": "browser", "url": url, "reason": f"the page did not finish loading within {timeout} seconds"}
        if rc == 127 and "docker" in (out or "").lower():
            return {"ok": False, "mode": "unavailable", "reason": "Docker is not available on the sandbox server"}
        if rc != 0 and _NO_IMAGE.search(out or ""):
            return {"ok": False, "mode": "no_image", "reason": "the browser image is not built on the sandbox server"}
        for line in reversed((out or "").splitlines()):
            if line.startswith("FXRESULT "):
                try:
                    data = json.loads(line[len("FXRESULT "):])
                    return data if isinstance(data, dict) else {"ok": False, "mode": "browser", "reason": "unreadable result"}
                except ValueError:
                    break
        return {"ok": False, "mode": "browser", "url": url, "reason": "the browser stopped without a result"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- fallback: a plain fetch (no JavaScript) -----------------------------------------------------------------------------------
def plain_fetch(url: str, *, fetcher=None) -> dict:
    report = {"ok": False, "mode": "fetch", "url": url[:300], "final_url": "", "status": None, "title": "", "page_errors": [],
              "console_errors": [], "failed_requests": [], "visible_errors": [], "steps": [], "reason": ""}
    try:
        if fetcher:
            status, text, final = fetcher(url)
        else:
            import site_probe
            current = url
            with httpx.Client(timeout=httpx.Timeout(12, connect=6), follow_redirects=False,
                              headers={"User-Agent": "AgentDaemon-Investigator/1.0"}) as client:
                for _ in range(4):
                    resp = client.get(current)
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = site_probe.safe_url(urljoin(current, resp.headers["location"]))
                        if not current:
                            report["reason"] = "the site redirected to a non-public address"
                            return report
                        continue
                    break
                status, text, final = resp.status_code, resp.text[:200_000], current
    except httpx.HTTPError as exc:
        report["reason"] = f"the site did not answer ({type(exc).__name__})"
        return report
    report.update(ok=True, status=status, final_url=str(final)[:300])
    m = _TITLE.search(text or "")
    report["title"] = " ".join(m.group(1).split())[:150] if m else ""
    visible = " ".join(_TAGS.sub(" ", text or "").split())
    report["visible_errors"] = [s for s in re.split(r"(?<=[.!?])\s+", visible)
                                if 3 <= len(s) <= 200 and re.search(r"error|failed|not found|went wrong|unavailable", s, re.I)][:5]
    if status and int(status) >= 400:
        host = urlparse(url)
        report["failed_requests"] = [{"host": host.hostname or "", "path": host.path or "/", "method": "GET", "status": int(status),
                                      "body": visible[:300], "type": "document"}]
    return report


# ---- reading a report ---------------------------------------------------------------------------------------------------------
def problems(report: dict) -> list[str]:
    """Short, comparable problem lines (used for before/after and for the customer)."""
    if not report:
        return []
    out = []
    if not report.get("ok"):
        out.append("page did not open: " + str(report.get("reason") or "unknown")[:160])
    st = report.get("status")
    if isinstance(st, int) and st >= 400:
        out.append(f"page answered HTTP {st}")
    for f in report.get("failed_requests") or []:
        if f.get("type") in ("image", "font", "media") and int(f.get("status") or 0) in (0, 404):
            continue      # a missing picture is not what the client is waiting for
        out.append(f"request failed: {f.get('method', 'GET')} {f.get('host', '')}{f.get('path', '')} -> "
                   + (f"HTTP {f.get('status')}" if f.get("status") else str(f.get("body") or "network error")[:80]))
    out += ["page error: " + str(e)[:160] for e in (report.get("page_errors") or [])[:5]]
    out += ["console error: " + str(e)[:160] for e in (report.get("console_errors") or [])[:5]
            if "favicon" not in str(e).lower() and "failed to load resource" not in str(e).lower()]
    out += ["on the page: " + str(e)[:160] for e in (report.get("visible_errors") or [])[:4]]
    out += ["error in the address: " + str(e)[:200] for e in (report.get("url_errors") or [])[:3]]
    for s in report.get("steps") or []:
        if not s.get("ok"):
            out.append(f"step failed: {json.dumps(s.get('step'))[:100]} ({str(s.get('detail'))[:120]})")
    seen, unique = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:20]


def compare(before: dict, after: dict) -> str:
    """'fixed' (no problems left), 'better', 'same' or 'worse'. Conservative: 'worse' only when the page clearly got worse."""
    b, a = set(problems(before)), set(problems(after))
    if not after or not after.get("ok"):
        return "worse" if before and before.get("ok") else "same"
    if not a:
        return "fixed"
    if isinstance(after.get("status"), int) and after["status"] >= 500 and not (isinstance(before.get("status"), int) and before["status"] >= 500):
        return "worse"
    new = a - b
    if len(new) >= 2 and len(a) > len(b) + 1:
        return "worse"
    if len(a) < len(b) or (b and not (a & b) and len(a) <= len(b)):
        return "better"
    return "same"


def format_report(report: dict, *, limit: int = 3000) -> str:
    """Plain lines for the model (UNTRUSTED section) and for the customer."""
    if not report:
        return "No live check was made."
    head = [f"Opened: {report.get('url', '')}" + (f" (ended at {report['final_url']})" if report.get("final_url") and report.get("final_url") != report.get("url") else ""),
            f"How: {'a real browser' if report.get('mode') == 'browser' else 'a plain page fetch (no JavaScript ran)'}"]
    if report.get("note"):
        head.append(str(report["note"]))
    if report.get("status") is not None:
        head.append(f"Page status: HTTP {report.get('status')}")
    if report.get("title"):
        head.append(f"Title: {report['title']}")
    probs = problems(report)
    head.append("Problems seen: " + ("none" if not probs else ""))
    head += [f"- {p}" for p in probs]
    for f in (report.get("failed_requests") or [])[:6]:
        if f.get("body"):
            head.append(f"  answer from {f.get('host', '')}{f.get('path', '')}: {str(f['body'])[:300]}")
    hops = report.get("navigations") or []
    if len(hops) > 1:
        head.append("The visit went: " + " -> ".join(f"{h.get('host', '')}{h.get('path', '')}" for h in hops[:10]))
    oauth = report.get("oauth")
    if oauth:
        head.append(f"Sign-in request sent to {oauth.get('provider', '')}: redirect_uri={oauth.get('redirect_uri', '')} "
                    f"response_type={oauth.get('response_type', '')} state={'yes' if oauth.get('has_state') else 'NO'} scope={oauth.get('scope', '')}")
        head.append("(The investigator cannot sign in. Compare that redirect_uri with the callback route in the code and with what the "
                    "provider's console allows.)")
    if report.get("steps"):
        head.append("Steps: " + "; ".join(f"{json.dumps(s.get('step'))[:80]} {'ok' if s.get('ok') else 'FAILED'}" for s in report["steps"]))
    return "\n".join(head)[:limit]


def default_steps(report_text: str, html_files: dict[str, str] | None = None) -> list[dict]:
    """Free, rule-based journey from an owner's words: click a button they name (if the page has one), else just open the page."""
    steps: list[dict] = []
    text = (report_text or "")
    quoted = re.findall(r"[\"“']([^\"”']{2,40})[\"”']", text)
    named = re.findall(r"\bthe\s+([A-Z][\w-]{1,30}|[\w-]{2,30})\s+button\b", text, re.I)
    for label in (quoted + named)[:1]:
        steps.append({"click": f"text={label.strip()}"})
    if not steps:
        # "Continue with Google sends me back to login": click the sign-in button so the report shows where it goes and which
        # redirect_uri it sends. The investigator never types credentials; it stops at the provider's page.
        m = re.search(r"((?:continue|sign ?in|log ?in|sign ?up|login) with (google|github|facebook|apple|microsoft))", text, re.I)
        if m:
            steps.append({"click": f"text=/{m.group(2)}/i"})
        elif re.search(r"google.*(log ?in|sign ?in|auth)|(log ?in|sign ?in|auth)\w*.*google", text, re.I):
            steps.append({"click": "text=/google/i"})
    if steps:
        steps.append({"wait": "1500"})
    return clean_steps(steps)
