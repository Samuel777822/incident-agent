"""The incident page and board show how the agent worked: modes tried, results, switches. Never model names."""
import pytest

import web_app
from fixengine import store, ui
from tests.test_web_app import _request, web_env  # noqa: F401
from tests.test_fixengine_web import _login, _project


def _incident(project_id):
    incident_id, _ = web_app.portal_db.ingest_event(
        project_id, timestamp="2026-11-05T10:00:00+00:00", level="ERROR", message="KeyError: 'sku'",
        traceback="Traceback...\nKeyError: 'sku'", signature="KeyError@orders.py")
    return incident_id


def _bug_with_tries(user_id, project_id, incident_id):
    bug = store.create_bug(project_id=project_id, user_id=user_id, incident_id=incident_id,
                           fingerprint_json={"hash": "x"}, bug_class="medium", category="")
    plan = [("groq", "fail"), ("groq", "fail"), ("haiku", "fail"), ("groq", "system_fault"), ("sonnet", "pass")]
    for tier, result in plan:
        aid = store.add_attempt(bug=bug, tier=tier, model="some-model-id", used_strong_diag=False, info_hash="h")
        store.finish_attempt(aid, result=result, failing_before=3, failing_after=0 if result == "pass" else 3,
                             diagnosis="the lookup assumed the key exists")
    return bug


def test_mode_path_groups_runs_and_uses_plain_names():
    assert ui.mode_path(["groq", "groq", "groq", "haiku", "sonnet"]) == "Low effort ×3 → Engineer ×1 → Lead engineer ×1"
    assert ui.mode_path([]) == ""


def test_incident_page_shows_each_try_the_switches_and_no_model_names(web_env):
    user_id, cookie = _login()
    project_id = _project(user_id)
    incident_id = _incident(project_id)
    _bug_with_tries(user_id, project_id, incident_id)
    status, _, body = _request(f"/projects/{project_id}/incidents/{incident_id}", cookie=cookie)
    assert status == "200 OK"
    assert "How the agent worked on this" in body
    assert "Path so far: <strong>Low effort ×2 → Engineer ×1 → Lead engineer ×1</strong>" in body
    assert "Switched from Low effort to Engineer" in body and "Switched from Engineer to Lead engineer" in body
    assert "Fix passed the tests" in body and "Fix did not pass the tests" in body
    assert "not counted as a try" in body                       # the technical fault is shown but not numbered
    assert "Failing tests: 3 before, 0 after" in body
    for hidden in ("some-model-id", "claude-", "gpt-oss", "haiku", "sonnet", "opus"):
        assert hidden not in body.lower()


def test_board_card_shows_the_path_summary(web_env):
    user_id, cookie = _login()
    project_id = _project(user_id)
    incident_id = _incident(project_id)
    _bug_with_tries(user_id, project_id, incident_id)
    status, _, body = _request(f"/projects/{project_id}/incidents/live", cookie=cookie)
    assert status == "200 OK" and "tries: Low effort ×2 → Engineer ×1 → Lead engineer ×1" in body


def test_another_customer_never_sees_the_trail(web_env):
    user_id, _ = _login()
    project_id = _project(user_id)
    incident_id = _incident(project_id)
    _bug_with_tries(user_id, project_id, incident_id)
    other_id, other_cookie = _login("other@example.com")
    status, _, body = _request(f"/projects/{project_id}/incidents/{incident_id}", cookie=other_cookie)
    assert status == "404 Not Found" and "How the agent worked" not in body


def test_incident_without_engine_work_has_no_trail_section(web_env):
    user_id, cookie = _login()
    project_id = _project(user_id)
    incident_id = _incident(project_id)
    _, _, body = _request(f"/projects/{project_id}/incidents/{incident_id}", cookie=cookie)
    assert "How the agent worked" not in body


def test_waiting_for_decision_links_to_the_usage_page():
    html = ui.trail_html({"bug": {"status": "awaiting_choice", "review_report": ""}, "attempts": []})
    assert "Waiting for your decision" in html and "href='/usage'" in html
