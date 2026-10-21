"""Run the portal and its tenant-aware incident worker in one Render web service."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

STOPPING = False


def _stop(*_args):
    global STOPPING
    STOPPING = True


def _start():
    env = os.environ.copy()
    port = env.get("PORT", "10000")
    workers = env.get("WEB_CONCURRENCY", "1")
    threads = env.get("GUNICORN_THREADS", "4")
    children = {}
    if env.get("PORTAL_RUN_WORKER", "1").strip() != "0":
        children["incident-worker"] = subprocess.Popen([sys.executable, "portal_worker.py"], env=env)
    children["web"] = subprocess.Popen([
        "gunicorn", "--preload", "--bind", f"0.0.0.0:{port}",
        "--workers", workers, "--threads", threads, "--timeout", "120",
        "wsgi:application",
    ], env=env)
    return children


def _stop_children(children):
    for child in children.values():
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 15
    for child in children.values():
        if child.poll() is None:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    children = _start()
    try:
        while not STOPPING:
            failed = [name for name, child in children.items() if child.poll() is not None]
            if failed:
                print("Portal process exited; restarting supervised processes: " + ", ".join(failed),
                      flush=True)
                _stop_children(children)
                if STOPPING:
                    break
                time.sleep(2)
                children = _start()
            time.sleep(0.5)
    finally:
        _stop_children(children)


if __name__ == "__main__":
    main()
