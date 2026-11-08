"""v3 web pages: the 'tell the agent what's broken' box, the flow diagram, the new-feature banner."""
import hashlib

import portal_db
from fixengine import orchestrator
from test_monitoring_v2 import active_user, new_project
from test_web_app import _request, web_env  # noqa: F401  (web_env is a fixture)


def _setup():
    user_id, csrf, cookie = active_user("owner@example.com")
    project_id = new_project(user_id, "r" * 40, gate_state="active")
    return user_id, csrf, cookie, project_id


def test_report_box_creates_an_incident_the_agent_will_pick_up(web_env):
    _user, csrf, cookie, project_id = _setup()
    status, headers, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie,
                                  form={"csrf": csrf, "text": "Isaiah chapter 1 is not loading"})
    assert status.startswith("30") and "reported=1" in str(headers)
    incidents = portal_db.list_incidents(project_id)
    assert len(incidents) == 1 and incidents[0]["signature"].startswith("user_report:")
    conn = portal_db.get_connection()
    try:
        event = dict(portal_db._execute(conn, "SELECT message,traceback FROM log_events WHERE project_id=?", (project_id,)).fetchone())
    finally:
        conn.close()
    evidence = orchestrator._evidence_of({"first_event": event})
    assert evidence == {"kind": "user_report", "owner_report": "Isaiah chapter 1 is not loading"} and event["message"].startswith("[user report]")


def test_report_box_rejects_empty_text_bad_csrf_other_users_and_floods(web_env):
    _user, csrf, cookie, project_id = _setup()
    status, headers, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "x"})
    assert "reported=short" in str(headers) and portal_db.list_incidents(project_id) == []
    status, _, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": "wrong", "text": "the button does nothing"})
    assert status.startswith("403")
    for i in range(5):
        _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": f"problem number {i} on the page"})
    _, headers, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "yet another problem here"})
    assert "reported=limit" in str(headers) and len(portal_db.list_incidents(project_id)) == 5
    _other, other_csrf, other_cookie = active_user("someone@example.com")
    status, _, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=other_cookie, form={"csrf": other_csrf, "text": "not my project at all"})
    assert status.startswith("404")


def test_project_page_shows_flow_report_card_and_flash_and_dashboard_the_banner(web_env):
    _user, csrf, cookie, project_id = _setup()
    _, _, page = _request(f"/projects/{project_id}?reported=1", cookie=cookie)
    assert page.count("flow-node") == 7 and "Tell the agent what&#x27;s broken" in page.replace("'", "&#x27;") or "Tell the agent what's broken" in page
    assert f"action='/projects/{project_id}/report'" in page and "Sent. The agent is looking at your code now" in page
    assert "up to 3 rounds" in page and "Site check" in page
    _, _, dash = _request("/dashboard", cookie=cookie)
    assert "new-banner" in dash and "Tell the agent" in dash


def test_the_live_board_refreshes_every_five_seconds(web_env):
    _user, _csrf, cookie, _project_id = _setup()
    status, _, js = _request("/assets/live.js", cookie=cookie)
    assert status == "200 OK" and "5000" in js and "3000" not in js
