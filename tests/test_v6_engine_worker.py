"""v6: the worker works on several cases at the same time, each claimed once with a lease that is renewed while it runs."""
import threading
import time

import portal_worker


def test_several_cases_run_at_the_same_time(monkeypatch):
    monkeypatch.setenv("WORKER_CASE_THREADS", "3")
    queue = [{"incident_id": f"i{n}", "project_id": "p"} for n in range(5)]
    running, peak, lock, gate = [], [0], threading.Lock(), threading.Event()

    def fake_process(incident):
        with lock:
            running.append(incident["incident_id"])
            peak[0] = max(peak[0], len(running))
        gate.wait(5)
        with lock:
            running.remove(incident["incident_id"])
        return True
    monkeypatch.setattr(portal_worker, "_claim", lambda: queue.pop(0) if queue else None)
    monkeypatch.setattr(portal_worker, "_process_claimed", fake_process)
    monkeypatch.setattr(portal_worker, "_engine", lambda: None)
    monkeypatch.setattr(portal_worker, "_POOL", None)
    monkeypatch.setattr(portal_worker, "_ACTIVE", set())
    assert portal_worker.dispatch_cases() is True
    time.sleep(0.3)
    assert peak[0] == 3 and len(queue) == 2                  # three at once; the other two wait for a free slot
    assert portal_worker.dispatch_cases() is False             # all slots busy: nothing new is claimed
    gate.set()
    time.sleep(0.3)
    assert portal_worker.dispatch_cases() is True and not queue


def test_the_lease_is_short_and_renewed_while_a_case_runs(monkeypatch):
    monkeypatch.delenv("WORKER_LEASE_SECONDS", raising=False)
    assert portal_worker._lease_seconds() == 1200
    monkeypatch.setenv("WORKER_LEASE_SECONDS", "900")
    assert portal_worker._lease_seconds() == 900
    renewed = []
    monkeypatch.setattr(portal_worker.portal_db, "extend_lease", lambda iid, s: renewed.append(iid))
    real_wait = threading.Event.wait
    monkeypatch.setattr(threading.Event, "wait", lambda self, t=None: real_wait(self, 0.01))
    monkeypatch.setattr(portal_worker, "_process_claimed", lambda inc: time.sleep(0.1))
    portal_worker._process_claimed_safely({"incident_id": "abc", "project_id": "p"})
    assert renewed and set(renewed) == {"abc"}


def test_one_case_crashing_never_stops_the_others(monkeypatch):
    monkeypatch.setattr(portal_worker, "_process_claimed", lambda inc: 1 / 0)
    portal_worker._process_claimed_safely({"incident_id": "boom", "project_id": "p"})      # logged, not raised
