"""Proof that the Docker sandbox really builds and tests projects, and enforces its limits.

  python scripts/prove_sandbox.py

Part 1  language matrix: HTML/CSS, Node, TypeScript, Java, Python and a mixed repo go through detect_profiles -> DockerRunner
Part 2  resource / isolation probes: timeout, memory limit, no network, read-only root, pids limit, secrets canary
Part 3  Render -> VPS path: sandbox_service.py on localhost, called by RemoteRunner (HMAC signed), plus a bad-signature request
Output: verification/sandbox_proof.json and verification/sandbox_proof.md   (no secrets: the HMAC secret is random per run)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "bench")]

import make_cases as mc          # noqa: E402
import make_cases_v2 as v2       # noqa: E402
from fixengine import config as fx_config, sandbox  # noqa: E402

cfg = fx_config.load()
cfg["sandbox"]["mode"] = "docker"
os.environ.pop("FIXENGINE_ALLOW_UNSAFE_LOCAL", None)
scratch = Path(tempfile.mkdtemp(prefix="sbx-proof-"))
report: dict = {"docker": {}, "matrix": [], "probes": [], "remote": {}}


def sh(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.strip()


report["docker"] = {"version": sh("docker", "version", "--format", "{{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})"),
                    "images": {k: cfg["sandbox"][k] for k in ("image_python", "image_node", "image_java")},
                    "image_ids": {k: sh("docker", "image", "inspect", "--format", "{{.Id}} {{.Size}}", cfg["sandbox"][k]) for k in ("image_python", "image_node", "image_java")},
                    "limits": {k: cfg["sandbox"][k] for k in ("memory", "cpus", "pids", "timeout_seconds", "install_timeout_seconds")}}
print("[sandbox] docker", report["docker"]["version"], flush=True)


def count_tests(output: str) -> dict:
    """Best-effort counts from the runner's own summary line (pytest / node:test / maven / plain)."""
    out: dict = {}
    m = re.search(r"(\d+) passed", output)
    if m:
        out["passed"] = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    out["failed"] = int(m.group(1)) if m else 0
    m = re.search(r"(?:#|\u2139)\s*tests (\d+)", output) or re.search(r"Tests run: (\d+)", output)
    if m:
        out["discovered"] = int(m.group(1))
        m2 = re.search(r"(?:#|\u2139)\s*pass (\d+)", output)
        if m2:
            out["passed"] = int(m2.group(1))
    return out


def run_matrix(name: str, repo: Path, expect_image: str | None) -> None:
    profile = sandbox.detect_profiles(repo)
    parts = profile.parts if isinstance(profile, sandbox.StackSet) else [profile]
    runner = sandbox.make_runner(cfg)
    started = time.time()
    res = sandbox.run_profile(runner, repo, profile)
    row = {"case": name, "detected": [{"label": sandbox.stack_label(p), "language": p.language, "workdir": p.workdir,
                                       "image": cfg["sandbox"].get(sandbox.IMAGE_KEY.get(p.language, ""), "") or "-",
                                       "commands": {"install": p.install, "build": p.build, "test": p.test, "smoke": p.smoke},
                                       "notes": p.notes} for p in parts],
           "runner": type(runner).__name__, "passed": res.passed, "tests_ran": res.tests_ran, "smoke_ran": res.smoke_ran,
           "failing": res.failing, "system_fault": res.system_fault, "error": res.error, "seconds": round(time.time() - started, 1),
           "phases": [{"name": p.name, "ok": p.ok, "rc": p.rc, "seconds": p.seconds, "tests": count_tests(p.output) if "test" in p.name else None,
                       "log_tail": p.output[-300:]} for p in res.phases]}
    report["matrix"].append(row)
    print(f"[matrix] {name:<28} detected={[d['label'] for d in row['detected']]} passed={res.passed} fault={res.system_fault} {row['seconds']}s", flush=True)


def make(name: str, builder) -> Path:
    d = scratch / name
    d.mkdir(parents=True)
    builder(d)
    return d


# ---------------------------------------------------------------- part 1: language matrix
run_matrix("html-css-only", make("static", v2.static_base), "node")
run_matrix("javascript-node", make("js", v2.js_base), "node")
run_matrix("typescript", make("ts", v2.ts_base), "node")
run_matrix("java", make("java", v2.java_base), "java")
run_matrix("python", make("py", mc.base_repo), "python")


def mixed(d: Path) -> None:
    v2.java_base(d / "service")
    v2.js_base(d / "web")
    mc.base_repo(d / "tools")
    (d / "README.md").write_text("mixed language repo (no Python at the root, no pom at the root)\n", encoding="utf-8")


run_matrix("mixed-java+js+python", make("mixed", mixed), None)


def java_js_only(d: Path) -> None:
    v2.java_base(d / "api")
    v2.js_base(d / "ui")


run_matrix("mixed-java+js (no Python)", make("javajs", java_js_only), None)

# ---------------------------------------------------------------- part 2: limits and isolation
PROBE_PY = {
    "timeout (infinite loop, 15 s limit)": ("import time\ndef test_hang():\n    while True:\n        time.sleep(0.1)\n", {"timeout_seconds": 15}, "expect timed_out"),
    "memory limit (allocate 3 GiB, 1 GiB cap)": ("def test_mem():\n    b = bytearray(3 * 1024**3)\n    assert len(b)\n", {}, "expect rc 137 (OOM kill)"),
    "network isolation (connect to 1.1.1.1:53)": ("import socket\ndef test_net():\n    s = socket.create_connection(('1.1.1.1', 53), timeout=5)\n    s.close()\n", {}, "expect failure"),
    "read-only root fs (write /etc/x)": ("def test_ro():\n    open('/etc/x', 'w').write('x')\n", {}, "expect failure"),
    "non-root user (uid must be 10001)": ("import os\ndef test_uid():\n    assert os.getuid() == 10001\n", {}, "expect pass"),
    "pids limit (fork bomb, 256 cap)": ("import os\ndef test_fork():\n    kids = 0\n    try:\n        for _ in range(2000):\n            pid = os.fork()\n            if pid == 0:\n                import time; time.sleep(20); os._exit(0)\n            kids += 1\n    except OSError:\n        assert kids < 2000\n        return\n    raise AssertionError('fork bomb was not stopped, kids=%d' % kids)\n", {}, "expect pass: OSError at the cap"),
    "no host secrets in the environment": ("import os\ndef test_env():\n    assert 'PROOF_SECRET_TOKEN' not in os.environ\n    assert not [v for v in os.environ.values() if 'must-not-leak' in v]\n    # GPG_KEY is the PUBLIC key id baked into the official python image, not a secret\n    bad = [k for k in os.environ if any(w in k.upper() for w in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY'))]\n    assert not bad, bad\n", {}, "expect pass"),
}
os.environ["PROOF_SECRET_TOKEN"] = "must-not-leak"            # exists on the host; the container must not see it
for title, (code, overrides, expectation) in PROBE_PY.items():
    d = scratch / re.sub(r"\W+", "_", title)[:30]
    d.mkdir(parents=True)
    (d / "test_probe.py").write_text(code, encoding="utf-8")
    pcfg = json.loads(json.dumps(cfg))
    pcfg["sandbox"].update(overrides)
    prof = sandbox.Profile(language="python", test="python -m pytest -q -x -p no:cacheprovider", has_tests=True)
    t0 = time.time()
    res = sandbox.DockerRunner(pcfg).run(d, prof)
    phase = res.phases[-1] if res.phases else None
    row = {"probe": title, "expectation": expectation, "passed": res.passed, "timed_out": res.timed_out, "rc": phase.rc if phase else None,
           "seconds": round(time.time() - t0, 1), "system_fault": res.system_fault, "error": res.error,
           "log_tail": (phase.output[-260:] if phase else "")}
    report["probes"].append(row)
    print(f"[probe ] {title:<48} rc={row['rc']} timed_out={res.timed_out} passed={res.passed} {row['seconds']}s", flush=True)

# ---------------------------------------------------------------- part 3: Render -> VPS path (same service code, localhost)
secret = secrets.token_hex(24)
port = 18099
env = dict(os.environ, FIXENGINE_SANDBOX_SECRET=secret, PORT=str(port))
svc = subprocess.Popen([sys.executable, str(ROOT / "sandbox_service.py")], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(2)
try:
    import httpx
    health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=10).json()
    os.environ.update({"FIXENGINE_SANDBOX_URL": f"http://127.0.0.1:{port}", "FIXENGINE_SANDBOX_SECRET": secret})
    repo = scratch / "py"
    prof = sandbox.detect_profiles(repo)
    t0 = time.time()
    good = sandbox.RemoteRunner(cfg).run(repo, prof)
    good_secs = round(time.time() - t0, 1)
    body = b"{}"
    bad = httpx.post(f"http://127.0.0.1:{port}/run", content=body, headers={"X-Timestamp": str(int(time.time())), "X-Signature": "0" * 64}, timeout=10)
    stale_ts = str(int(time.time()) - 3600)
    stale = httpx.post(f"http://127.0.0.1:{port}/run", content=body, headers={"X-Timestamp": stale_ts, "X-Signature": sandbox.sign(secret, stale_ts, body)}, timeout=10)
    os.environ["FIXENGINE_SANDBOX_SECRET"] = "wrong-secret"
    wrong = sandbox.RemoteRunner(cfg).run(repo, prof)
    report["remote"] = {"health": health, "signed_run_passed": good.passed, "signed_run_phases": [(p.name, p.ok, p.rc) for p in good.phases],
                        "signed_run_seconds": good_secs, "bad_signature_http": bad.status_code, "stale_timestamp_http": stale.status_code,
                        "wrong_secret_result": {"system_fault": wrong.system_fault, "error": wrong.error},
                        "note": "Service code is identical to the VPS's; this proves protocol, auth and execution, NOT the customer's real VPS/network."}
    print("[remote] health", health, "signed run passed:", good.passed, "bad sig:", bad.status_code, "stale:", stale.status_code,
          "wrong secret ->", wrong.error, flush=True)
finally:
    svc.terminate()

out = ROOT / "verification"
out.mkdir(exist_ok=True)
(out / "sandbox_proof.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
md = ["# Sandbox proof (generated by scripts/prove_sandbox.py)", "", f"Docker {report['docker']['version']}", "", "## Language matrix", "",
      "| Case | Detected stacks (image) | Passed | Phases (rc, seconds) | Tests |", "|---|---|---|---|---|"]
for r in report["matrix"]:
    det = "; ".join(f"{d['label']} ({d['image']})" for d in r["detected"])
    ph = ", ".join(f"{p['name']} rc={p['rc']} {p['seconds']}s" for p in r["phases"])
    tests = "; ".join(f"{p['name']}: {p['tests']}" for p in r["phases"] if p.get("tests"))
    md.append(f"| {r['case']} | {det} | {r['passed']} | {ph} | {tests or '-'} |")
md += ["", "## Limits and isolation", "", "| Probe | Expected | rc | timed out | seconds | Log tail |", "|---|---|---|---|---|---|"]
for r in report["probes"]:
    md.append(f"| {r['probe']} | {r['expectation']} | {r['rc']} | {r['timed_out']} | {r['seconds']} | `{r['log_tail'][-120:].strip().replace(chr(10), ' ')}` |")
md += ["", "## Render -> VPS path", "", "```json", json.dumps(report["remote"], indent=2), "```"]
(out / "sandbox_proof.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("[sandbox] done", flush=True)
