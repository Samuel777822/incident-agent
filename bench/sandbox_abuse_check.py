"""Does the Docker sandbox really contain hostile or broken code?  (needs Docker; refuses to run any other way)

    docker build -f sandbox/Dockerfile.python -t fixengine-sandbox-python:1 sandbox     # once
    python bench/sandbox_abuse_check.py

Each check runs a small, harmless-looking-but-nasty Python script INSIDE the sandbox container, exactly the way the engine
runs a customer's tests, and then asks: was the bad thing stopped?

  infinite_loop        a loop that never ends          -> must be killed by the time limit
  memory_hog           asks for far more RAM than allowed -> must be killed, not take the host down
  too_many_processes   starts hundreds of processes     -> the process limit must refuse most of them
  network_blocked      tries to reach the internet during the test run -> must fail
  secrets_not_visible  looks for our planted fake keys in its environment, by name AND by value -> must find none
  read_only_system     tries to write to system folders  -> must be refused
  no_docker_socket     looks for the Docker socket       -> must not exist
  not_root             checks who it runs as             -> must not be root

PASS means contained. Any FAIL means the sandbox is NOT safe to use with other people's code: do not launch until fixed.
This script never runs the checks outside Docker, because they are meant to be dangerous without it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixengine import config as fx_config, sandbox  # noqa: E402

CONTAINED = "CONTAINED"

# Fake credentials planted on THIS side (the host). The sandbox must never see them, neither under their own name nor smuggled under another
# name. They are built from pieces so secret scanners on GitHub do not mistake them for real keys.
# Why not "any variable whose name contains KEY": the official python image defines GPG_KEY, a PUBLIC key id used to verify the Python download.
# That is not a secret, and a name heuristic made this check fail on a correctly isolated sandbox.
CANARY_MARK = "FAKE-canary-must-never-reach-the-sandbox"
CANARIES = {
    "ANTHROPIC_API_KEY": "sk-" + "ant-" + CANARY_MARK,
    "GROQ_API_KEY": "gsk" + "_" + CANARY_MARK,
    "OPENROUTER_API_KEY": "sk-or-" + "v1-" + CANARY_MARK,
    "GITHUB_TOKEN": "gh" + "p_" + CANARY_MARK,
    "DATABASE_URL": "postgresql://" + "user:" + CANARY_MARK + "@db.invalid/prod",
    "SESSION_SECRET": CANARY_MARK,
    "FIXENGINE_SANDBOX_SECRET": CANARY_MARK,
    "RAZORPAY_KEY_SECRET": CANARY_MARK,
    "BREVO_API_KEY": CANARY_MARK,
}


def secrets_script() -> str:
    """The script that runs INSIDE the sandbox: fail if any planted name is present OR any variable (whatever its name) holds a planted value."""
    return ("import os\n"
            f"planted = {sorted(CANARIES)!r}\n"
            f"mark = {CANARY_MARK!r}\n"
            "by_name = set(planted).intersection(os.environ)\n"
            "by_value = {k for k, v in os.environ.items() if mark in v}\n"
            "bad = sorted(by_name | by_value)\n"
            "print('ESCAPED: ' + ', '.join(bad) if bad else 'CONTAINED')\n"
            "raise SystemExit(1 if bad else 0)\n")


CHECKS = {
    "infinite_loop": ("while True:\n    pass\n", "killed"),
    "memory_hog": ("data = bytearray(6 * 1024 ** 3)\nprint('ALLOCATED', len(data))\n", "killed"),
    "too_many_processes": (
        "import subprocess\nprocs, failed = [], 0\nfor _ in range(600):\n    try:\n        procs.append(subprocess.Popen(['sleep', '5']))\n"
        "    except Exception:\n        failed += 1\nprint('started', len(procs), 'refused', failed)\n"
        "for p in procs:\n    p.kill()\nraise SystemExit(0 if failed > 50 else 1)\n", "exit0"),
    "network_blocked": (
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=4)\nexcept OSError:\n    print('CONTAINED')\n    raise SystemExit(0)\n"
        "print('ESCAPED: reached the internet')\nraise SystemExit(1)\n", "exit0"),
    "secrets_not_visible": (secrets_script(), "exit0"),
    "read_only_system": (
        "ok = []\nfor path in ('/etc/fx_probe', '/usr/fx_probe', '/opt/fx_probe'):\n    try:\n        open(path, 'w').write('x')\n        ok.append(path)\n"
        "    except OSError:\n        pass\nprint('ESCAPED: wrote ' + ', '.join(ok) if ok else 'CONTAINED')\nraise SystemExit(1 if ok else 0)\n", "exit0"),
    "no_docker_socket": (
        "import os\nfound = [p for p in ('/var/run/docker.sock', '/run/docker.sock') if os.path.exists(p)]\n"
        "print('ESCAPED: ' + ','.join(found) if found else 'CONTAINED')\nraise SystemExit(1 if found else 0)\n", "exit0"),
    "not_root": (
        "import os\nprint('ESCAPED: running as root' if os.getuid() == 0 else 'CONTAINED')\nraise SystemExit(1 if os.getuid() == 0 else 0)\n", "exit0"),
}


def docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def run_check(name: str, script: str, expect: str, cfg: dict) -> tuple[bool, str]:
    work = Path(tempfile.mkdtemp(prefix="fx-abuse-"))
    try:
        (work / "abuse.py").write_text(script, encoding="utf-8")
        profile = sandbox.Profile(language="python", test="python abuse.py", has_tests=True)
        res = sandbox.DockerRunner(cfg).run(work, profile)
        if res.system_fault:
            return False, f"could not run: {res.error}"
        phase = next((p for p in res.phases if p.name == "test"), None)
        if phase is None:
            return False, "no test phase ran"
        if expect == "killed":
            return (not phase.ok and phase.rc != 0), f"exit {phase.rc} after {phase.seconds}s"
        return phase.ok, (phase.output.strip().splitlines() or ["(no output)"])[-1][:120]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    if not docker_ready():
        print("Docker is not running or not installed. These checks only make sense inside the real sandbox, so nothing was run.")
        return 2
    os.environ.update(CANARIES)          # plant the fake secrets on THIS side: if any shows up inside the sandbox, the check fails
    cfg = fx_config.load()
    cfg["sandbox"]["mode"] = "docker"
    cfg["sandbox"]["timeout_seconds"] = 20                 # keep the infinite-loop check short
    failed = 0
    for name, (script, expect) in CHECKS.items():
        ok, detail = run_check(name, script, expect, cfg)
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name:20s} {detail}")
    print("\nAll contained." if not failed else f"\n{failed} check(s) FAILED: the sandbox is NOT safe yet.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
