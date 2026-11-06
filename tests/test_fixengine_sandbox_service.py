import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

import sandbox_service
from fixengine import sandbox


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setenv("FIXENGINE_SANDBOX_SECRET", "s3cret-for-tests")
    seen = {}

    def fake_run(self, repo_dir, profile):
        seen["files"] = sorted(p.name for p in Path(repo_dir).iterdir())
        seen["profile"] = profile.language
        return sandbox.SandboxResult(passed=True, tests_ran=True, failing=0, output="ok",
                                     phases=[sandbox.PhaseResult("test", True, 0, 0.1, "1 passed")])
    monkeypatch.setattr(sandbox.DockerRunner, "run", fake_run)
    server = ThreadingHTTPServer(("127.0.0.1", 0), sandbox_service.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_remote_runner_round_trip(host, tmp_path, monkeypatch):
    url, seen = host
    monkeypatch.setenv("FIXENGINE_SANDBOX_URL", url)
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "test_app.py").write_text("def test_x(): pass\n")
    from fixengine import config as fx_config
    res = sandbox.RemoteRunner(fx_config.load()).run(tmp_path, sandbox.detect_profile(tmp_path))
    assert res.passed and res.tests_ran and res.phases[0].name == "test"
    assert seen["files"] == ["app.py", "test_app.py"] and seen["profile"] == "python"


def test_host_rejects_bad_signatures_and_stale_timestamps(host):
    url, _ = host
    body = json.dumps({"repo_b64": "", "profile": {}}).encode()
    bad = httpx.post(url + "/run", content=body, headers={"X-Timestamp": "1", "X-Signature": "00"})
    assert bad.status_code == 401
    import time
    ts = str(int(time.time()) - 4000)
    stale = httpx.post(url + "/run", content=body, headers={"X-Timestamp": ts, "X-Signature": sandbox.sign("s3cret-for-tests", ts, body)})
    assert stale.status_code == 401
    assert httpx.get(url + "/health").json() == {"ok": True}


def test_host_never_extracts_outside_its_scratch_folder(tmp_path):
    import io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("ok.py", "../escape.py", "/abs.py"):
            info = tarfile.TarInfo(name); info.size = 1; tar.addfile(info, io.BytesIO(b"x"))
    dest = tmp_path / "d"; dest.mkdir()
    sandbox_service.safe_extract(buf.getvalue(), dest)
    assert (dest / "ok.py").exists() and not (tmp_path / "escape.py").exists() and not Path("/abs.py").exists()
