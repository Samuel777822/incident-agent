"""Start-up smoke check, run INSIDE the sandbox container with the network disabled (loopback still works).

usage: python /opt/smoke.py PORT WAIT_SECONDS "start command"
Passes when the app answers any HTTP request on 127.0.0.1:PORT with a status below 500.
"""
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    port, wait, command = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    env = dict(os.environ, PORT=str(port), HOST="0.0.0.0")
    proc = subprocess.Popen(command, shell=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    deadline, status = time.time() + wait, None
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                    status = resp.status
                    break
            except urllib.error.HTTPError as err:
                status = err.code
                break
            except Exception:
                time.sleep(0.5)
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
    try:
        out = proc.communicate(timeout=5)[0] or ""
    except Exception:
        out = ""
    if status is not None and status < 500:
        print(f"SMOKE OK: HTTP {status}")
        return 0
    print(f"SMOKE FAILED: status={status}\n{out[-1500:]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
