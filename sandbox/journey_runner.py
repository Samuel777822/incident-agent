"""Runs inside the browser sandbox image (sandbox/Dockerfile.browser), with NO network.

  python3 /opt/journey_runner.py /work/.fx_journeys.json

Serves the site from /work/<root> on localhost, opens each journey in headless Chromium and checks it. Requests to any other host are
blocked (or answered from "replay" in the spec). Prints what failed in plain words; exit code 1 when any journey failed.
"""
import functools
import http.server
import json
import os
import sys
import threading

PORT = 8765


def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(path):
    spec = json.load(open(path, encoding="utf-8"))
    base_dir = os.path.join(os.path.dirname(path), spec.get("root", "")) if spec.get("root") else os.path.dirname(path)
    serve(base_dir)
    from playwright.sync_api import sync_playwright
    replay = spec.get("replay") or {}
    failures, passed = [], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        for journey in spec.get("journeys", []):
            ctx = browser.new_context()
            page = ctx.new_page()
            problems, blocked, changed = [], set(), {"n": 0}

            def route(r, blocked=blocked):
                url = r.request.url
                host = url.split("/")[2] if "://" in url else ""
                if host.startswith("127.0.0.1") or host.startswith("localhost"):
                    return r.continue_()
                rec = replay.get(host)
                if rec:
                    return r.fulfill(status=int(rec.get("status", 200)), body=str(rec.get("body", "")),
                                     content_type=rec.get("content_type", "application/json"))
                blocked.add(host)
                return r.abort("blockedbyclient")

            ctx.route("**/*", route)
            page.on("pageerror", lambda e, problems=problems: problems.append("page error: " + str(e)[:200]))
            page.on("console", lambda m, problems=problems: problems.append("console error: " + m.text[:200]) if m.type == "error" else None)
            page.add_init_script("window.__fxChanged=0;new MutationObserver(()=>{window.__fxChanged++}).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});")
            step_no = 0
            try:
                for step in journey["steps"]:
                    step_no += 1
                    if "goto" in step:
                        page.goto(f"http://127.0.0.1:{PORT}{step['goto']}", wait_until="load", timeout=15000)
                    elif "click" in step:
                        before, url = page.evaluate("window.__fxChanged"), page.url
                        page.click(step["click"], timeout=5000)
                        page.wait_for_timeout(900)
                        if step.get("expect_change") and page.evaluate("window.__fxChanged") == before and page.url == url:
                            raise AssertionError(f"clicking {step['click']} did nothing (the page did not change)")
                    elif "fill" in step:
                        page.fill(step["fill"], step.get("text", ""), timeout=5000)
                    elif "expect_text" in step:
                        page.wait_for_selector(f"text={step['expect_text']}", timeout=5000)
                    elif "expect_visible" in step:
                        page.wait_for_selector(step["expect_visible"], state="visible", timeout=5000)
                    elif "wait" in step:
                        page.wait_for_timeout(min(int(step["wait"]), 3000))
                    elif step.get("expect_no_page_errors"):
                        page.wait_for_timeout(300)
                        real = [p for p in problems if "Failed to load resource" not in p]
                        if real:
                            raise AssertionError("; ".join(real[:3]))
                passed += 1
            except Exception as exc:  # a failed step is the finding, not a crash
                failures.append(f"FAILED journey '{journey['name']}' at step {step_no}: {str(exc).splitlines()[0][:240]}")
            finally:
                ctx.close()
        browser.close()
    print(f"journeys: {passed} passed, {len(failures)} failed")
    for line in failures:
        print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
