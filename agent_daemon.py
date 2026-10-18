"""
agent_daemon.py - 24/7 Autonomous On-Call Supervisor

Continuously monitors services:
  1. Pulls latest Git commits and reads app logs (sync_and_tail).
  2. Detects new errors and deduplicates them in SQLite.
  3. Waits for enough evidence (5 errors, 30 seconds), then runs AI diagnosis,
     testing and the pull request.
  4. Marks incidents resolved once their pull request is merged.
  5. Publishes the incident list to the live dashboard.
"""

import sys
import time
from datetime import datetime, timezone

from db import get_connection
from publish_incidents import publish_incidents
from resolve_merged import resolve_merged_prs
from run_diagnosis import run as run_diagnosis
from sync_and_tail import sync_and_tail

MIN_OCCURRENCES = 5       # errors needed before the agent acts
MIN_AGE_SECONDS = 30      # seconds since the first error (lets the bug reach GitHub)
COOLDOWN_SECONDS = 180    # do not retry the same incident sooner than this


def ready_for_diagnosis(inc_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT occurrences, first_seen FROM incidents WHERE id = ?", (inc_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    try:
        first = datetime.fromisoformat(row["first_seen"])
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - first).total_seconds()
    except Exception:
        return True
    return (row["occurrences"] or 0) >= MIN_OCCURRENCES and age >= MIN_AGE_SECONDS


def start_daemon(service: str = "coffee-shop", interval_seconds: int = 10):
    print("=" * 60)
    print(f"  AI ON-CALL ENGINEER DAEMON: MONITORING '{service}' 24/7")
    print(f"  Polling interval: every {interval_seconds}s | Press Ctrl+C to stop")
    print("=" * 60)

    iteration = 0
    last_attempt = {}
    while True:
        iteration += 1
        try:
            new_count, pending_ids = sync_and_tail(service)
            resolve_merged_prs()
            publish_incidents(service)
            if pending_ids:
                print(f"\n[DAEMON] Alert! Found {len(pending_ids)} incident(s) needing attention: {pending_ids}")
                for inc_id in pending_ids:
                    if not ready_for_diagnosis(inc_id):
                        print(f"[DAEMON] Incident #{inc_id}: waiting for more evidence before acting.")
                        continue
                    if time.time() - last_attempt.get(inc_id, 0) < COOLDOWN_SECONDS:
                        print(f"[DAEMON] Incident #{inc_id}: cooling down after the last attempt.")
                        continue
                    last_attempt[inc_id] = time.time()
                    print(f"[DAEMON] Launching auto-remediation for Incident #{inc_id}...")
                    run_diagnosis(inc_id)
                    publish_incidents(service)  # show the result on the dashboard right away
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
    svc = sys.argv[1] if len(sys.argv) > 1 else "coffee-shop"
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    start_daemon(svc, interval)