"""When the agent asks the owner a question, there is a box to answer it right where the question is shown."""
import portal_db
import incident_board
import live_status
from fixengine import store
from test_web_app import web_env  # noqa: F401  (fixture)


def _asked(project_id, csrf, cookie, question="Where is the chat window: a dialog box, or a page of its own?"):
    from test_web_app import _request
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the chat does not open"})
    inc = portal_db.list_incidents(project_id)[0]
    portal_db.set_live_result(inc["id"], "QUESTION: " + question)
    return inc


def test_the_case_card_shows_the_question_with_an_answer_box(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    inc = _asked(project_id, csrf, cookie)
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "The agent is asking you" in page and "Where is the chat window" in page
    assert f"/projects/{project_id}/incidents/{inc['id']}/reply" in page and "Send answer" in page and "<textarea" in page


def test_the_answer_box_is_outside_the_folding_summary():
    inc = {"id": "abc", "signature": "user_report:x", "status": "awaiting_choice", "live_result": "QUESTION: Which page?"}
    html = incident_board.render_board("p1", [inc], "auto", "tok")
    assert html.index("</summary>") < html.index("The agent is asking you")
    assert incident_board.question_box_html({"id": "a", "live_result": "Live check ok"}, "p1", "tok") == ""
    assert incident_board.question_box_html({"id": "a", "live_result": "QUESTION: x"}, "p1", "") == ""     # no form without a token


def test_answering_reopens_the_case_and_returns_to_the_project(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    inc = _asked(project_id, csrf, cookie)
    status, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/reply", method="POST", cookie=cookie,
                                  form={"csrf": csrf, "text": "It is a dialog box at the bottom right.",
                                        "next": f"/projects/{project_id}#case-{inc['id']}"})
    location = dict(headers)["Location"]
    assert status.startswith("30") and location == f"/projects/{project_id}?replied=1#case-{inc['id']}"
    assert store.client_replies(inc["id"]) == ["It is a dialog box at the bottom right."]
    assert portal_db.get_incident_row(inc["id"])["status"] == "diagnosing"
    _, _, page = _request(f"/projects/{project_id}?replied=1", cookie=cookie)
    assert "is continuing on this case" in page.replace("&#x27;", "'")


def test_the_return_address_cannot_leave_the_project(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    inc = _asked(project_id, csrf, cookie)
    for bad in ("https://evil.example.com/", "//evil.example.com", "/projects/other-project", "/admin", f"/projects/{project_id}x"):
        _, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/reply", method="POST", cookie=cookie,
                                 form={"csrf": csrf, "text": "answer " + bad, "next": bad})
        assert dict(headers)["Location"].startswith(f"/projects/{project_id}/incidents/{inc['id']}"), bad


def test_the_dashboard_links_straight_to_the_answer_box():
    work = {"incidents": [{"id": "i1", "project_id": "p1", "project_name": "shop", "status": "awaiting_choice", "stage": "waiting_user",
                           "signature": "user_report:x", "live_result": "QUESTION: Which browser?"}], "checks": []}
    html = live_status.live_panel(work, {"p1": "auto"}, None)
    assert "The agent is asking you" in html and "Which browser?" in html and "href='/projects/p1#answer-i1'" in html


def test_the_live_refresh_never_wipes_an_answer_being_typed():
    js = incident_board.LIVE_JS
    assert "function typing()" in js and "if (typing()) { return; }" in js
