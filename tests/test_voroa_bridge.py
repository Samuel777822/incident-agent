"""The temporary Voroa bridge: auto-merge is opt-in, one case thread keeps the worker loop free, cleanup removes only old scratch."""
import os
import threading
import time

import portal_worker
import temp_cleanup

DAY = 24 * 3600


def _age(path, seconds):
    old = time.time() - seconds
    for base, dirs, files in os.walk(path, topdown=False):
        for name in dirs + files:
            os.utime(os.path.join(base, name), (old, old))
    os.utime(path, (old, old))


def _scratch(root, name, age=2 * DAY):
    folder = root / name
    (folder / "repo").mkdir(parents=True)
    (folder / "repo" / "file.txt").write_text("x" * 10)
    _age(folder, age)
    return folder


def _use_root(monkeypatch, root, **env):
    monkeypatch.setattr(temp_cleanup.tempfile, "gettempdir", lambda: str(root))
    monkeypatch.delenv("FIXENGINE_SCRATCH", raising=False)
    monkeypatch.delenv("TEMP_CLEANUP_DRY_RUN", raising=False)
    monkeypatch.delenv("TEMP_CLEANUP_MAX_AGE_HOURS", raising=False)
    monkeypatch.setenv("TEMP_CLEANUP_ENABLED", "1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_auto_merge_stays_off_unless_it_is_switched_on(monkeypatch):
    calls = []
    monkeypatch.setattr(portal_worker, "process_auto_merges", lambda: calls.append(1))
    monkeypatch.delenv("AUTO_MERGE_ENABLED", raising=False)
    assert portal_worker.maybe_auto_merge() is False and calls == []
    monkeypatch.setenv("AUTO_MERGE_ENABLED", "0")
    assert portal_worker.maybe_auto_merge() is False and calls == []
    monkeypatch.setenv("AUTO_MERGE_ENABLED", "1")
    assert portal_worker.maybe_auto_merge() is True and calls == [1]


def test_one_case_thread_does_not_block_the_worker_loop(monkeypatch):
    monkeypatch.setenv("WORKER_CASE_THREADS", "1")
    queue = [{"incident_id": "a", "project_id": "p"}, {"incident_id": "b", "project_id": "p"}]
    gate = threading.Event()
    monkeypatch.setattr(portal_worker, "_claim", lambda: queue.pop(0) if queue else None)
    monkeypatch.setattr(portal_worker, "_process_claimed", lambda incident: gate.wait(5))
    monkeypatch.setattr(portal_worker, "_engine", lambda: None)
    monkeypatch.setattr(portal_worker, "_POOL", None)
    monkeypatch.setattr(portal_worker, "_ACTIVE", set())
    started = time.monotonic()
    assert portal_worker.dispatch_cases() is True
    assert time.monotonic() - started < 2                  # the case runs in its thread; the heartbeat loop goes on
    assert len(queue) == 1                                 # one at a time: the second case waits
    gate.set()
    for future in list(portal_worker._ACTIVE):
        future.result(timeout=5)
    portal_worker._POOL.shutdown(wait=True)
    for thread in threading.enumerate():                   # the lease renewer ends with its case; nothing leaks into other tests
        if thread.name == "lease":
            thread.join(timeout=5)


def test_cleanup_is_off_by_default(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path)
    monkeypatch.delenv("TEMP_CLEANUP_ENABLED")
    folder = _scratch(tmp_path, "fx-repo-old")
    assert temp_cleanup.sweep()["removed"] == 0 and folder.exists()


def test_cleanup_removes_only_old_folders_the_app_created(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path)
    old = _scratch(tmp_path, "fx-repo-old")
    old_pr = _scratch(tmp_path, "incident-agent-old")
    recent = _scratch(tmp_path, "fx-repo-recent", age=3600)
    other = _scratch(tmp_path, "customer-backup")
    dump = tmp_path / "fx-production.dump"
    dump.write_text("data")
    _age(dump, 2 * DAY)
    report = temp_cleanup.sweep()
    assert report["removed"] == 2 and report["kept"] == 1 and report["errors"] == 0
    assert not old.exists() and not old_pr.exists()
    assert recent.exists() and other.exists() and dump.exists()


def test_a_recent_file_deep_inside_keeps_an_active_workspace(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path)
    active = _scratch(tmp_path, "fx-agent-active")
    (active / "repo" / "file.txt").write_text("still being worked on")
    assert temp_cleanup.sweep()["removed"] == 0 and active.exists()


def test_dry_run_reports_but_removes_nothing(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path, TEMP_CLEANUP_DRY_RUN="1")
    old = _scratch(tmp_path, "fx-repo-old")
    report = temp_cleanup.sweep()
    assert report["would_remove"] == 1 and report["removed"] == 0 and report["bytes"] == 10 and old.exists()


def test_the_age_limit_cannot_be_set_dangerously_low(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path, TEMP_CLEANUP_MAX_AGE_HOURS="0")
    three_hours = _scratch(tmp_path, "fx-repo-young", age=3 * 3600)
    assert temp_cleanup.max_age_hours() == temp_cleanup.MIN_AGE_HOURS
    assert temp_cleanup.sweep()["removed"] == 0 and three_hours.exists()


def test_a_folder_that_vanishes_during_the_scan_does_not_stop_the_worker(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path)

    class Vanished:
        name = "fx-repo-gone"
        path = str(tmp_path / "fx-repo-gone")

        def is_symlink(self):
            return False

        def is_dir(self, follow_symlinks=True):
            return True

        def stat(self, follow_symlinks=True):
            raise FileNotFoundError(self.path)
    monkeypatch.setattr(temp_cleanup.os, "scandir", lambda _root: [Vanished()])
    assert temp_cleanup.sweep()["errors"] == 0


def test_a_removal_error_is_counted_and_does_not_stop_the_worker(tmp_path, monkeypatch):
    _use_root(monkeypatch, tmp_path)
    _scratch(tmp_path, "fx-repo-old")

    def refuse(_path):
        raise PermissionError("denied")
    monkeypatch.setattr(temp_cleanup.shutil, "rmtree", refuse)
    assert temp_cleanup.sweep()["errors"] == 1


def test_a_database_error_names_the_reason_but_never_the_secrets():
    import portal_db
    url = "postgresql://appuser:S3cretPw@db.internal.example.net:6543/agentdb?sslmode=require"
    exc = RuntimeError('connection to "db.internal.example.net" port 6543 failed: password authentication failed for user "appuser" (S3cretPw)')
    text = portal_db.describe_db_error(url, exc)
    assert "pass-word authentication failed" in text and "port=6543" in text and "options=sslmode" in text
    assert "password" not in text.lower()
    for secret in ("S3cretPw", "appuser", "db.internal.example.net"):
        assert secret not in text
    assert "no dots" in portal_db.describe_db_error("postgres://u:p@dpg-abc123/db", RuntimeError("timeout"))


def test_schema_setup_takes_turns_on_postgresql(monkeypatch):
    """The web app and the worker both run init_db at start; on PostgreSQL they must hold the same advisory lock."""
    import sys
    import types
    import portal_db
    events = []

    class FakeConn:
        def execute(self, sql, params=()):
            events.append(("execute", sql, params))

        def close(self):
            events.append(("close",))

    fake = types.SimpleNamespace(connect=lambda url, **kw: events.append(("connect", kw.get("autocommit"))) or FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.net/app")
    monkeypatch.setattr(portal_db, "_init_db_locked", lambda: events.append(("schema",)))
    portal_db.init_db()
    kinds = [e[0] for e in events]
    assert kinds == ["connect", "execute", "execute", "schema", "close"]
    assert events[0][1] is True
    assert events[2][1].startswith("SELECT pg_advisory_lock") and events[2][2] == (portal_db.SCHEMA_LOCK_KEY,)


def test_the_lock_is_released_when_schema_setup_fails(monkeypatch):
    import sys
    import types
    import pytest
    import portal_db
    closed = []

    class FakeConn:
        def execute(self, sql, params=()):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=lambda url, **kw: FakeConn()))
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.net/app")

    def boom():
        raise RuntimeError("deadlock detected")
    monkeypatch.setattr(portal_db, "_init_db_locked", boom)
    with pytest.raises(RuntimeError):
        portal_db.init_db()
    assert closed == [True]
