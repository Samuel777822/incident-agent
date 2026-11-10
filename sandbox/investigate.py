"""Live investigator. Runs inside the browser image (sandbox/Dockerfile.browser) WITH network, started by sandbox_service.py /investigate.

    python3 /opt/investigate.py /work/spec.json

spec: {"url": "https://client-site.example/isaiah/1", "steps": [{"click": "#next"}, {"expect_text": "In the beginning"}], "allowed_host": "client-site.example"}

Opens the client's PUBLIC site in headless Chromium like a visitor would and prints ONE line of JSON (the evidence report):
final address, title, page errors, console errors, failed requests (host, path without query, status, first 300 characters of the
answer), visible error messages, and the result of each step. No screenshots, no cookies kept, no logins, no form values sent
anywhere except by the steps themselves.

SAFETY (second layer; the first is the network rule in DEPLOY.md): every request the page makes is checked here, and anything that
resolves to a private, loopback, link-local (cloud metadata), reserved or multicast address is refused. Service workers are blocked.
Navigation steps may only open pages on the client's own host.
"""
import ipaddress
import json
import re
import socket
import sys
import time
from urllib.parse import urlparse

MAX_FAILED = 25
MAX_CONSOLE = 25
BODY_CHARS = 300
STEP_TIMEOUT_MS = 8000
NAV_TIMEOUT_MS = 25000
ERROR_TEXT = re.compile(r"(error|failed|failure|not found|something went wrong|cannot|can't|unable|try again|unavailable|"
                        r"exception|undefined|null|404|500|502|503|timed? ?out)", re.I)
_DNS: dict = {}


def public_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    if host in _DNS:
        return _DNS[host]
    ok = True
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        if not infos:
            ok = False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
                    or (ip.version == 6 and ip.ipv4_mapped and not public_host(str(ip.ipv4_mapped)))):
                ok = False
    except (OSError, ValueError):
        ok = False
    _DNS[host] = ok
    return ok


def _short(url: str) -> dict:
    try:
        p = urlparse(url)
        return {"host": (p.hostname or "")[:120], "path": (p.path or "/")[:200]}
    except ValueError:
        return {"host": "", "path": ""}


def visible_errors(page) -> list:
    """Short visible lines that look like an error message (what a visitor would read on the page)."""
    try:
        text = page.evaluate("() => (document.body && document.body.innerText) || ''")
    except Exception:
        return []
    lines = []
    for line in str(text).splitlines():
        line = " ".join(line.split())
        if 3 <= len(line) <= 200 and ERROR_TEXT.search(line) and line not in lines:
            lines.append(line)
        if len(lines) >= 8:
            break
    return lines


def run(spec: dict) -> dict:
    url = str(spec.get("url") or "")
    parts = urlparse(url)
    allowed = (spec.get("allowed_host") or parts.hostname or "").lower()
    report = {"ok": False, "mode": "browser", "url": url[:300], "final_url": "", "status": None, "title": "", "page_errors": [],
              "console_errors": [], "failed_requests": [], "visible_errors": [], "steps": [], "blocked": [], "ms": 0, "reason": ""}
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        report["reason"] = "not a public http(s) address"
        return report
    if not public_host(parts.hostname):
        report["reason"] = "the address does not resolve to a public internet address"
        return report
    from playwright.sync_api import sync_playwright
    started = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run"])
        ctx = browser.new_context(service_workers="block", accept_downloads=False, java_script_enabled=True,
                                  user_agent="Mozilla/5.0 (X11; Linux x86_64) AgentDaemon-Investigator/1.0 Chrome/120 Safari/537.36",
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        failed = report["failed_requests"]

        def route(r):
            u = r.request.url
            p = urlparse(u)
            if p.scheme in ("data", "blob", "about"):
                return r.continue_()
            if p.scheme not in ("http", "https") or not public_host(p.hostname or ""):
                if len(report["blocked"]) < 10:
                    report["blocked"].append(_short(u))
                return r.abort("blockedbyclient")
            return r.continue_()

        ctx.route("**/*", route)

        def on_response(resp):
            try:
                if resp.status >= 400 and len(failed) < MAX_FAILED:
                    body = ""
                    try:
                        body = resp.text()[:BODY_CHARS]
                    except Exception:
                        body = ""
                    failed.append({**_short(resp.url), "method": resp.request.method, "status": resp.status, "body": body,
                                   "type": resp.request.resource_type})
            except Exception:
                pass

        def on_failed(req):
            if len(failed) < MAX_FAILED and (req.failure or "") != "net::ERR_BLOCKED_BY_CLIENT":
                failed.append({**_short(req.url), "method": req.method, "status": 0, "body": str(req.failure or "")[:BODY_CHARS],
                               "type": req.resource_type})

        page.on("response", on_response)
        page.on("requestfailed", on_failed)
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)[:300]) if len(report["page_errors"]) < MAX_CONSOLE else None)
        page.on("console", lambda m: report["console_errors"].append(m.text[:300])
                if m.type == "error" and len(report["console_errors"]) < MAX_CONSOLE else None)
        try:
            resp = page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
            report["status"] = resp.status if resp else None
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            for step in (spec.get("steps") or [])[:10]:
                entry = {"step": {k: (v if isinstance(v, bool) else str(v)[:120]) for k, v in step.items()}, "ok": True, "detail": ""}
                try:
                    if "goto" in step:
                        target = str(step["goto"])
                        target = target if "://" in target else f"{parts.scheme}://{parts.netloc}/{target.lstrip('/')}"
                        if (urlparse(target).hostname or "").lower() != allowed:
                            raise AssertionError("only pages of your own site can be opened")
                        page.goto(target, wait_until="load", timeout=NAV_TIMEOUT_MS)
                    elif "click" in step:
                        page.click(str(step["click"]), timeout=STEP_TIMEOUT_MS)
                        page.wait_for_timeout(1200)
                    elif "fill" in step:
                        page.fill(str(step["fill"]), str(step.get("text", ""))[:200], timeout=STEP_TIMEOUT_MS)
                    elif "expect_text" in step:
                        page.wait_for_selector(f"text={step['expect_text']}", timeout=STEP_TIMEOUT_MS)
                    elif "expect_visible" in step:
                        page.wait_for_selector(str(step["expect_visible"]), state="visible", timeout=STEP_TIMEOUT_MS)
                    elif "wait" in step:
                        page.wait_for_timeout(min(int(step["wait"]), 5000))
                except Exception as exc:  # a failed step is a finding
                    entry["ok"] = False
                    entry["detail"] = str(exc).splitlines()[0][:240]
                report["steps"].append(entry)
                if not entry["ok"]:
                    break
            page.wait_for_timeout(800)
            report["final_url"] = page.url[:300]
            report["title"] = (page.title() or "")[:150]
            report["visible_errors"] = visible_errors(page)
            report["ok"] = True
        except Exception as exc:
            report["reason"] = "the page did not open: " + str(exc).splitlines()[0][:200]
        finally:
            report["ms"] = int((time.time() - started) * 1000)
            ctx.close()
            browser.close()
    return report


if __name__ == "__main__":
    try:
        result = run(json.load(open(sys.argv[1], encoding="utf-8")))
    except Exception as exc:  # never a stack trace: the caller reads one JSON line
        result = {"ok": False, "mode": "browser", "reason": f"investigator error: {type(exc).__name__}"}
    print("FXRESULT " + json.dumps(result)[:200000])
