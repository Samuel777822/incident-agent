"""
agent_daemon.py - 24/7 Autonomous On-Call Supervisor

Continuously monitors services:
  1. Pulls latest Git commits and reads app logs (sync_and_tail).
  2. Detects new errors and deduplicates them in SQLite.
  3. Automatically runs AI diagnosis, testing, and auto-merge remediation!
"""

import sys
import time

from sync_and_tail import sync_and_tail
from resolve_merged import resolve_merged_prs
from run_diagnosis import run as run_diagnosis


def start_daemon(service: str = "shop-api", interval_seconds: int = 10):
    print("=" * 60)
    print(f"  AI ON-CALL ENGINEER DAEMON: MONITORING '{service}' 24/7")
    print(f"  Polling interval: every {interval_seconds}s | Press Ctrl+C to stop")
    print("=" * 60)

    iteration = 0
    while True:
        iteration += 1
        try:
            new_count, pending_ids = sync_and_tail(service)
            resolve_merged_prs()
            if pending_ids:
                print(f"\n[DAEMON] Alert! Found {len(pending_ids)} incident(s) needing attention: {pending_ids}")
                for inc_id in pending_ids:
                    print(f"[DAEMON] Launching auto-remediation for Incident #{inc_id}...")
                    run_diagnosis(inc_id)
            else:
                if iteration % 6 == 1:  # Print heartbeat roughly every minute
                    print(f"[DAEMON Heartbeat] Checked '{service}' at {time.strftime('%H:%M:%S')} - All quiet.")
        except KeyboardInterrupt:
            print("\n[DAEMON] Shutting down on user request.")
            break
        except Exception as err:
            print(f"[DAEMON Error] Cycle error: {err}")

        time.sleep(interval_seconds)


if __name__ == "__main__":
    svc = sys.argv[1] if len(sys.argv) > 1 else "shop-api"
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    start_daemon(svc, interval)
