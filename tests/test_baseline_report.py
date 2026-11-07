"""Baseline health report, test-count parsing and the first scan for every watch mode."""
import json
import sys
from pathlib import Path

import portal_db
import push_watch
import web_app
from fixengine import sandbox
from test_push_guard import FakeRunner, _snapshot, make_session, project_for, put
from test_web_app import web_env  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _audit_rows(project_id, action):
    conn = portal_db.get_connection()
    try:
        rows = portal_db._execute(conn, "SELECT detail FROM audit_log WHERE project_id=? AND action=?", (project_id, action)).fetchall()
        return [json.loads(r["detail"]) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ count_tests
def test_count_tests_reads_pytest_node_and_maven_summaries():
    assert sandbox.count_tests("== 3 failed, 40 passed in 1.2s ==") == {"discovered": 43, "passed": 40, "failed": 3}
    node = "\u2139 tests 43\n\u2139 pass 42\n\u2139 fail 1\n"
    assert sandbox.count_tests(node) == {"discovered": 43, "passed": 42, "failed": 1}
    assert sandbox.count_tests("# tests 5\n# pass 5\n# fail 0\n") == {"discovered": 5, "passed": 5, "failed": 0}
    maven = "Tests run: 3, Failures: 0, Errors: 0\nTests run: 91, Failures: 1, Errors: 1, Skipped: 0"
    assert sandbox.count_tests(maven) == {"discovered": 91, "passed": 89, "failed": 2}


def test_count_tests_says_unknown_not_zero_when_there_is_no_summary():
    assert sandbox.count_tests("") == {}
    assert sandbox.count_tests("BUILD SUCCESS") == {}


# ------------------------------------------------------------------------------------------------ stack_report
def test_stack_report_lists_commands_phases_tests_and_steps_that_never_ran(tmp_path):
    put(tmp_path, {"app.py": "x = 1\n", "test_app.py": "def test_x(): pass\n", "requirements.txt": ""})
    profile = sandbox.detect_profiles(tmp_path)
    result = sandbox.SandboxResult(passed=False, tests_ran=False, phases=[
        sandbox.PhaseResult("install", True, 0, 1.0, "ok"), sandbox.PhaseResult("build", False, 1, 0.5, "SyntaxError")])
    row = sandbox.stack_report(profile, result)[0]
    assert row["label"] == "Python" and row["ok"] is False and row["phase"] == "build"
    assert [p["name"] for p in row["phases"]] == ["install", "build"] and row["phases"][1]["rc"] == 1
    assert "test" in row["not_run"]                       # the test phase never ran: it is reported, not silently skipped
    assert row["has_tests"] is True and row["tests"] == {}
    assert row["commands"]["test"]


def test_stack_report_keeps_the_old_summary_keys():
    prof = sandbox.Profile(language="python", test="python -m pytest -q", has_tests=True)
    res = sandbox.SandboxResult(passed=True, tests_ran=True, phases=[sandbox.PhaseResult("test", True, 0, 1.0, "5 passed in 0.1s")])
    row = sandbox.stack_report(prof, res)[0]
    assert {"label", "language", "ok", "phase"} <= set(row) and row["tests"] == {"discovered": 5, "passed": 5, "failed": 0}


# ------------------------------------------------------------------------------------------------ the report itself
def _run(web_env, tmp_path, source, runner_result):
    user_id, *_ = make_session(f"{source}@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    repo = put(tmp_path / "repo", {"app.py": "x = 1\n", "test_app.py": "def test_x(): pass\n", "requirements.txt": ""})
    portal_db.enqueue_push_check(project_id, user_id, "a" * 40, "main", source=source)
    check = portal_db.claim_next_push_check()
    out = push_watch.run_check(check, runner=FakeRunner({"python": runner_result}), snapshot=_snapshot(repo), notify_fn=lambda *a: None)
    return project_id, out


def test_the_first_scan_after_connecting_writes_a_baseline_report(web_env, tmp_path):
    result = sandbox.SandboxResult(passed=True, tests_ran=True, phases=[
        sandbox.PhaseResult("install", True, 0, 1.0, "ok"), sandbox.PhaseResult("build", True, 0, 0.5, "ok"),
        sandbox.PhaseResult("test", True, 0, 2.0, "12 passed in 1.9s")], failing=0, output="all good")
    project_id, out = _run(web_env, tmp_path, "connect", result)
    assert out == "passed"
    [report] = _audit_rows(project_id, "baseline_report")
    assert report["passed"] is True and report["commit"] == "a" * 40 and report["source"] == "connect"
    assert report["tests_total"] == {"discovered": 12, "passed": 12, "failed": 0}
    assert report["stacks"][0]["commands"]["test"] and [p["name"] for p in report["stacks"][0]["phases"]] == ["install", "build", "test"]
    assert report["reported_at"] and "NOT isolated" in report["network"]       # FakeRunner is not the Docker runner: say so
    assert not _audit_rows(project_id, "push_report")


def test_a_later_push_writes_a_push_report_and_a_failing_baseline_is_recorded_as_failed(web_env, tmp_path):
    bad = sandbox.SandboxResult(passed=False, tests_ran=True, phases=[sandbox.PhaseResult("test", False, 1, 1.0, "2 failed, 10 passed")],
                                failing=2, output="[test] exit 1\n2 failed, 10 passed")
    project_id, out = _run(web_env, tmp_path, "webhook", bad)
    assert out == "failed"
    [report] = _audit_rows(project_id, "push_report")
    assert report["passed"] is False and report["tests_total"] == {"discovered": 12, "passed": 10, "failed": 2}
    assert not _audit_rows(project_id, "baseline_report")


def test_a_stack_whose_tests_have_no_countable_summary_is_listed_as_unknown(web_env, tmp_path):
    result = sandbox.SandboxResult(passed=True, tests_ran=True, phases=[sandbox.PhaseResult("test", True, 0, 1.0, "ok")], failing=0)
    project_id, _ = _run(web_env, tmp_path, "connect", result)
    [report] = _audit_rows(project_id, "baseline_report")
    assert report["tests_count_unknown_for"] == ["Python"] and report["tests_total"]["discovered"] == 0


# ------------------------------------------------------------------------------------------------ first scan in every watch mode
def test_runtime_only_projects_get_the_first_scan_too(web_env, monkeypatch):
    user_id, *_ = make_session("rt@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id, watch_mode="runtime")
    project = portal_db.get_project(project_id, user_id)
    monkeypatch.setattr(web_app, "_install_monitoring", lambda *a, **k: {"public": False})
    monkeypatch.setattr(push_watch, "branch_head", lambda p: {"sha": "b" * 40, "author": "dev", "message": "first"})
    result = web_app._activate_project(project, "token", "adi_key")
    assert result["scan"] is True and result.get("push") is None
    [check] = portal_db.list_push_checks(project_id)
    assert check["source"] == "connect" and check["sha"] == "b" * 40 and check["status"] == "queued"
    assert _audit_rows(project_id, "initial_scan_queued")[0]["queued"] is True
    assert "First scan started" in web_app._activation_summary(result, project)


def test_runtime_only_project_with_unreadable_branch_records_why_no_scan_was_queued(web_env, monkeypatch):
    user_id, *_ = make_session("rt2@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id, watch_mode="runtime")
    project = portal_db.get_project(project_id, user_id)
    monkeypatch.setattr(web_app, "_install_monitoring", lambda *a, **k: {"public": False})
    monkeypatch.setattr(push_watch, "branch_head", lambda p: None)
    result = web_app._activate_project(project, "token", "adi_key")
    assert result["scan"] is False
    assert "could not read the branch head" in _audit_rows(project_id, "initial_scan_queued")[0]["reason"]
