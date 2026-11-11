"""Tiny sandbox host. Run this on a small VPS that has Docker installed (NOT on Render).

    FIXENGINE_SANDBOX_SECRET=<long random> python sandbox_service.py          # listens on 0.0.0.0:8099

Put it behind HTTPS (Caddy / nginx) and firewall it to the portal's IP if you can. It accepts a signed request
(HMAC-SHA256 over timestamp + body, 5 minute window), unpacks the repo into a scratch folder and runs the same
hardened DockerRunner the portal would use locally. One job at a time.
"""
from __future__ import annotations

import base64
import errno
import glob
import hmac
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fixengine import config as fx_config
from fixengine import sandbox

LOCK = threading.Lock()
MAX_BODY = 60 * 1024 * 1024
MIN_FREE_GB = float(os.getenv("SANDBOX_MIN_FREE_GB", "4") or 4)


# ---- keeping the server healthy by itself ---------------------------------------------------------------------------------
# 11 Nov 2026: every run failed with "sandbox host error: OSError" and restarting the service did not help. A full disk (Docker
# build cache, stopped containers, old scratch folders) raises a plain OSError. The server now cleans up after itself, retries
# once, and says what is wrong instead of a bare "OSError".
def free_gb(path: str | None = None) -> float:
    try:
        return round(shutil.disk_usage(path or tempfile.gettempdir()).free / 1024 ** 3, 1)
    except OSError:
        return -1.0


def _quiet(argv: list[str], timeout: int = 180) -> bool:
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def free_space(force: bool = False) -> float:
    """Remove what is safe to remove: old scratch folders, stopped containers, unused volumes, dangling images and the build cache.
    The sandbox images themselves (python, node, java, browser) are tagged and are never removed. Returns the free GB after."""
    if not force and free_gb() >= MIN_FREE_GB:
        return free_gb()
    cutoff = time.time() - 1800
    try:
        image = fx_config.load()["sandbox"]["image_python"]
    except Exception:
        image = "python:3.12-slim"
    for folder in glob.glob(os.path.join(tempfile.gettempdir(), "fx-*")):
        try:
            if os.path.getmtime(folder) < cutoff:
                sandbox.remove_tree(Path(folder), image)        # also what the containers (uid 10001) left behind
        except OSError:
            pass
    for argv in (["docker", "container", "prune", "-f"], ["docker", "volume", "prune", "-f"],
                 ["docker", "image", "prune", "-f"], ["docker", "builder", "prune", "-af"]):
        _quiet(argv)
    return free_gb()


_DOCKER = {"at": 0.0, "ok": False}


def docker_ok() -> bool:
    if time.time() - _DOCKER["at"] > 60:
        _DOCKER.update(at=time.time(), ok=_quiet(["docker", "info"], timeout=20))
    return bool(_DOCKER["ok"])


def health() -> dict:
    disk = free_gb()
    dock = docker_ok()
    return {"ok": dock and disk >= 1, "disk_free_gb": disk, "docker": dock}


def describe(exc: BaseException) -> str:
    """A short, safe reason (no paths, no secrets): 'No space left on device', 'Docker is not running', ..."""
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return f"the sandbox server's disk is full ({free_gb()} GB free)"
        if isinstance(exc, FileNotFoundError) and "docker" in str(exc).lower():
            return "Docker is not installed or not on the PATH of the sandbox service"
        if isinstance(exc, PermissionError):
            return "the sandbox service is not allowed to use Docker (add its user to the docker group)"
        return f"{type(exc).__name__}: {exc.strerror or 'system error'}" + (f" (errno {exc.errno})" if exc.errno else "")
    return type(exc).__name__


def run_job(body: bytes) -> dict:
    """Unpack and run one repo. A full disk is cleaned up and the run is tried once more."""
    free_space()
    for attempt in (1, 2):
        scratch = None
        try:
            scratch = Path(tempfile.mkdtemp(prefix="fx-host-"))
            req = json.loads(body)
            safe_extract(base64.b64decode(req["repo_b64"]), scratch)
            prof = sandbox.Profile(**{k: v for k, v in req.get("profile", {}).items() if k in sandbox.Profile.__dataclass_fields__})
            return sandbox.DockerRunner(fx_config.load()).run(scratch, prof).to_dict()
        except OSError as exc:
            if attempt == 1 and exc.errno in (errno.ENOSPC, errno.EDQUOT):
                free_space(force=True)
                continue
            return sandbox.SandboxResult(system_fault=True, error=f"sandbox host error: {describe(exc)}").to_dict()
        except Exception as exc:  # never leak internals
            return sandbox.SandboxResult(system_fault=True, error=f"sandbox host error: {describe(exc)}").to_dict()
        finally:
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
    return sandbox.SandboxResult(system_fault=True, error="sandbox host error: the disk is still full after cleaning up").to_dict()


def safe_extract(data: bytes, dest: Path) -> None:
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar:
            name = m.name.replace("\\", "/")
            if not m.isreg() or name.startswith("/") or ".." in name.split("/"):
                continue
            count += 1
            if count > 8000 or m.size > 20 * 1024 * 1024:
                raise ValueError("archive too large")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._reply(200, health()) if self.path == "/health" else self._reply(404, {})

    def do_POST(self):
        secret = os.getenv("FIXENGINE_SANDBOX_SECRET", "")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if self.path not in ("/run", "/investigate", "/maintenance") or not secret or length <= 0 or length > MAX_BODY:
            return self._reply(400, {"error": "bad request"})
        body = self.rfile.read(length)
        ts = self.headers.get("X-Timestamp", "")
        good = hmac.compare_digest(sandbox.sign(secret, ts, body), self.headers.get("X-Signature", ""))
        if not good or not ts.isdigit() or abs(time.time() - int(ts)) > 300:
            return self._reply(401, {"error": "unauthorized"})
        if self.path == "/maintenance":       # the portal asks after a failed run: free space now, say how it went
            with LOCK:
                before = free_gb()
                after = free_space(force=True)
            return self._reply(200, {**health(), "cleaned": True, "freed_gb": round(max(0.0, after - before), 1)})
        if self.path == "/investigate":
            if len(body) > 64 * 1024:
                return self._reply(400, {"error": "bad request"})
            with LOCK:                      # one job at a time: a 2 GB server cannot run a browser next to a build
                try:
                    from fixengine import investigator
                    self._reply(200, investigator.run_in_docker(json.loads(body), fx_config.load()))
                except Exception as exc:  # never leak internals
                    self._reply(200, {"ok": False, "mode": "browser", "reason": f"investigator host error: {describe(exc)}"})
            return
        with LOCK:
            self._reply(200, run_job(body))

    def log_message(self, *args):
        pass


def _janitor() -> None:
    """Every 30 minutes, when nothing is running: keep at least MIN_FREE_GB free."""
    while True:
        time.sleep(1800)
        if LOCK.acquire(blocking=False):
            try:
                free_space()
            finally:
                LOCK.release()


if __name__ == "__main__":
    free_space()
    threading.Thread(target=_janitor, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8099"))), Handler).serve_forever()
