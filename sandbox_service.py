"""Tiny sandbox host. Run this on a small VPS that has Docker installed (NOT on Render).

    FIXENGINE_SANDBOX_SECRET=<long random> python sandbox_service.py          # listens on 0.0.0.0:8099

Put it behind HTTPS (Caddy / nginx) and firewall it to the portal's IP if you can. It accepts a signed request
(HMAC-SHA256 over timestamp + body, 5 minute window), unpacks the repo into a scratch folder and runs the same
hardened DockerRunner the portal would use locally. One job at a time.
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import os
import shutil
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
        self._reply(200, {"ok": True}) if self.path == "/health" else self._reply(404, {})

    def do_POST(self):
        secret = os.getenv("FIXENGINE_SANDBOX_SECRET", "")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if self.path not in ("/run", "/investigate") or not secret or length <= 0 or length > MAX_BODY:
            return self._reply(400, {"error": "bad request"})
        body = self.rfile.read(length)
        ts = self.headers.get("X-Timestamp", "")
        good = hmac.compare_digest(sandbox.sign(secret, ts, body), self.headers.get("X-Signature", ""))
        if not good or not ts.isdigit() or abs(time.time() - int(ts)) > 300:
            return self._reply(401, {"error": "unauthorized"})
        if self.path == "/investigate":
            if len(body) > 64 * 1024:
                return self._reply(400, {"error": "bad request"})
            with LOCK:                      # one job at a time: a 2 GB server cannot run a browser next to a build
                try:
                    from fixengine import investigator
                    self._reply(200, investigator.run_in_docker(json.loads(body), fx_config.load()))
                except Exception as exc:  # never leak internals
                    self._reply(200, {"ok": False, "mode": "browser", "reason": f"investigator host error: {type(exc).__name__}"})
            return
        with LOCK:
            scratch = Path(tempfile.mkdtemp(prefix="fx-host-"))
            try:
                req = json.loads(body)
                safe_extract(base64.b64decode(req["repo_b64"]), scratch)
                prof = sandbox.Profile(**{k: v for k, v in req.get("profile", {}).items() if k in sandbox.Profile.__dataclass_fields__})
                result = sandbox.DockerRunner(fx_config.load()).run(scratch, prof)
                self._reply(200, result.to_dict())
            except Exception as exc:  # never leak internals
                self._reply(200, sandbox.SandboxResult(system_fault=True, error=f"sandbox host error: {type(exc).__name__}").to_dict())
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8099"))), Handler).serve_forever()
