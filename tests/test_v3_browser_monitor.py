"""Runs the Node harness that exercises monitors/browser_monitor.js v3 against a fake DOM (failed requests, dead clicks, error text)."""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "browser_monitor_harness.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_browser_monitor_v3_reports_the_right_things_and_stays_quiet_otherwise():
    run = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "ALL PASSED" in run.stdout
