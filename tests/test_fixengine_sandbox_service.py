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
    health = httpx.get(url + "/health").json()
    assert set(health) == {"ok", "disk_free_gb", "docker"} and health["disk_free_gb"] > 0


def test_host_never_extracts_outside_its_scratch_folder(tmp_path):
    import io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("ok.py", "../escape.py", "/abs.py"):
            info = tarfile.TarInfo(name); info.size = 1; tar.addfile(info, io.BytesIO(b"x"))
    dest = tmp_path / "d"; dest.mkdir()
    sandbox_service.safe_extract(buf.getvalue(), dest)
    assert (dest / "ok.py").exists() and not (tmp_path / "escape.py").exists() and not Path("/abs.py").exists()


# ---- 11 Nov 2026: "sandbox host error: OSError" on every run, a restart did not help (a full disk) -------------------------
def test_a_full_disk_is_cleaned_up_and_the_run_is_tried_again(monkeypatch):
    import errno
    calls = {"runs": 0, "cleaned": 0}

    class Runner:
        def __init__(self, cfg):
            pass

        def run(self, root, prof):
            calls["runs"] += 1
            if calls["runs"] == 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            return sandbox.SandboxResult(passed=True, tests_ran=True)

    monkeypatch.setattr(sandbox_service.sandbox, "DockerRunner", Runner)
    monkeypatch.setattr(sandbox_service, "free_space", lambda force=False: calls.__setitem__("cleaned", calls["cleaned"] + 1) or 9.0)
    out = sandbox_service.run_job(_job())
    assert out["passed"] and calls == {"runs": 2, "cleaned": 2}


def test_the_error_says_what_is_wrong_not_just_oserror(monkeypatch):
    import errno

    class Runner:
        def __init__(self, cfg):
            pass

        def run(self, root, prof):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(sandbox_service.sandbox, "DockerRunner", Runner)
    monkeypatch.setattr(sandbox_service, "free_space", lambda force=False: 0.2)
    out = sandbox_service.run_job(_job())
    assert out["system_fault"] and "disk is full" in out["error"] and out["error"] != "sandbox host error: OSError"
    assert "not allowed to use Docker" in sandbox_service.describe(PermissionError(13, "Permission denied"))
    assert "Docker is not installed" in sandbox_service.describe(FileNotFoundError(2, "No such file", "docker"))


def test_cleanup_never_removes_the_sandbox_images(monkeypatch):
    seen = []
    monkeypatch.setattr(sandbox_service, "_quiet", lambda argv, timeout=180: seen.append(argv) or True)
    sandbox_service.free_space(force=True)
    assert ["docker", "image", "prune", "-f"] in seen                       # dangling layers only
    assert not any("-a" in a and "image" in a for a in seen) and not any("rmi" in a for a in seen)


def _job() -> bytes:
    import base64, io, tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("app.py"); info.size = 1; tar.addfile(info, io.BytesIO(b"x"))
    return json.dumps({"repo_b64": base64.b64encode(buf.getvalue()).decode(), "profile": {"language": "python"}}).encode()
