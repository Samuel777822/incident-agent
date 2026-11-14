"""v6: the founders are two college students, so normal cases NEVER go to them. Only the worst case (a job the diagnosis called
"big" that still failed after everything was tried) shows a link to the paid custom-job form. Anyone can send a custom job
(a whole app, or a big change) from the public form; the founders reply within 1 to 2 hours on WhatsApp or email."""
import json
import re

import portal_db
from fixengine import store
from tests import fx_helpers as H
from tests.test_v4_agent import _engine, call, reply
from tests.test_web_app import _cookie_value, _request, web_env  # noqa: F401  (fixture)

BIG = dict(what_broke="The whole booking flow is missing", why="It was never built", where=["src/"], proposed_fix="Build it",
           size="big", is_code_problem=True, owner_steps=[], confidence="high")


def _basic(pid):
    uid = store.get_project_row(pid)["user_id"]
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE subscriptions SET plan='basic' WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def test_a_normal_case_that_cannot_be_finished_never_goes_to_the_founders(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("give_up", reason="stuck", findings="x"))]})
    _basic(pid)
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_human"
    assert not store.get_flag(f"founder_offer:{inc}") and not store.get_flag(f"guide_offer:{inc}")
    row = portal_db.get_incident_row(inc)
    assert "founder" not in (row["stage_detail"] or "").lower() and "Tell the agent more" in (row["stage_detail"] or "")
    assert "sonnet" not in transports or not transports["sonnet"].calls          # Basic never pays for the Lead engineer


def test_only_a_big_job_that_failed_after_everything_offers_the_founders(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("give_up", reason="too big", findings="x"))]})
    _basic(pid)
    inc = H.make_incident(pid)
    store.set_flag(f"diagnosis:{inc}", json.dumps(BIG))             # the owner said "Yes, fix it" to a big diagnosis
    store.set_flag(f"autofix:{pid}", "1")
    assert engine.handle_incident(H.claim()) == "needs_human"
    assert store.get_flag(f"founder_offer:{inc}") == "1"
    assert "very big job" in portal_db.get_incident_row(inc)["stage_detail"]


def test_the_case_card_links_to_the_form_only_in_the_worst_case(tmp_path, monkeypatch):
    import incident_board
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {})
    inc = H.make_incident(pid)
    store.set_flag(f"diagnosis:{inc}", json.dumps({**BIG, "est_engineer_pct": 13, "est_lead_pct": 19}))
    html = incident_board.diagnosis_box_html({"id": inc, "stage": "awaiting_approval"}, pid, "tok")
    assert "Yes, fix it" in html and "founders" not in html.lower()               # a big job is tried by the AI first
    assert incident_board.diagnosis_box_html({"id": inc, "stage": "needs_human"}, pid, "tok") == ""   # no "Yes, fix it" after
    store.set_flag(f"founder_offer:{inc}", "1")
    failed = incident_board.diagnosis_box_html({"id": inc, "stage": "needs_human"}, pid, "tok")
    assert f"/build-request?kind=fix&amp;case={inc}" in failed and "Yes, fix it" not in failed and "paid" in failed


def _form(**over):
    base = {"name": "Riya", "email": "riya@example.com", "whatsapp": "+91 98765 43210", "kind": "build",
            "purpose": "Fest tickets for our college", "idea": "A booking site where students buy fest passes with UPI",
            "design": "Dark, neon", "pages": "4-10", "accounts": "yes", "database": "yes", "timeline": "2-4weeks",
            "deadline": "28 Nov", "hosting": "suggest", "domain": "need", "domain_name": "fest.in", "extra": ""}
    base.update(over)
    return base


def test_anyone_can_send_a_custom_job_and_the_founders_get_every_answer(web_env, monkeypatch):
    import notifications
    import web_app
    admins, customers = [], []
    monkeypatch.setattr(notifications, "notify_admins", lambda subject, body, kind="admin": admins.append((subject, body)) or [])
    monkeypatch.setattr(notifications, "notify_customer", lambda to, subject, body, kind="customer": customers.append((to, body)))
    status, headers, page = _request("/build-request")                           # public: no sign-in needed
    assert status == "200 OK" and "Ask the founders to build or fix your app" in page
    for text in ("within 1 to 2 hours on WhatsApp or email", "WhatsApp number", "How many pages?", "Does it save data",
                 "Where should it be hosted?", "Domain name", "When do you need it?", "What should be fixed or changed?",
                 "&#8377;2,000", "&#8377;600 a month", "from &#8377;200", "you pay these to the provider"):
        assert text in page, text
    csrf = re.search(r"name='csrf' value='([^']+)'", page).group(1)
    cookie = f"{web_app.CSRF_COOKIE}={_cookie_value(headers, web_app.CSRF_COOKIE)}"
    _, _, bad = _request("/build-request", method="POST", cookie=cookie, form={"csrf": csrf, **_form(whatsapp="12")})
    assert "WhatsApp number we can reach" in bad and "Fest tickets" in bad and not admins       # answers are kept
    _, _, ok = _request("/build-request", method="POST", cookie=cookie, form={"csrf": csrf, **_form()})
    assert "Sent to the founders" in ok and "1 to 2 hours" in ok
    subject, body = admins[0]
    assert "build a new app" in subject and "Riya" in subject
    for text in ("riya@example.com", "https://wa.me/919876543210", "4 to 10 pages", "Yes, it saves data", "2 to 4 weeks",
                 "Please suggest and set it up", "I need one", "fest.in", "UPI"):
        assert text in body, text
    assert customers[0][0] == "riya@example.com" and "1 to 2 hours" in customers[0][1]
    tickets = [t for t in portal_db.admin_list_support_messages() if t["email"] == "riya@example.com"]
    assert tickets and "wa.me/919876543210" in tickets[0]["message"]           # saved for the admin tickets list


def test_a_fix_request_needs_what_to_fix_and_bots_and_expired_forms_are_refused(web_env, monkeypatch):
    import notifications
    import web_app
    admins = []
    monkeypatch.setattr(notifications, "notify_admins", lambda subject, body, kind="admin": admins.append(subject) or [])
    monkeypatch.setattr(notifications, "notify_customer", lambda *a, **k: None)
    status, headers, page = _request("/build-request?kind=fix")
    assert "value='fix' checked" in page
    csrf = re.search(r"name='csrf' value='([^']+)'", page).group(1)
    cookie = f"{web_app.CSRF_COOKIE}={_cookie_value(headers, web_app.CSRF_COOKIE)}"
    _, _, page = _request("/build-request", method="POST", cookie=cookie, form={"csrf": csrf, **_form(kind="fix", idea="")})
    assert "what should be fixed or changed" in page and not admins
    _, _, page = _request("/build-request", method="POST", cookie=cookie,
                          form={"csrf": csrf, **_form(kind="fix", app_link="https://github.com/me/app", fix_what="The login page loops forever")})
    assert "Sent to the founders" in page and "fix or change an app" in admins[0]
    _request("/build-request", method="POST", cookie=cookie, form={"csrf": csrf, **_form(), "website": "spam.example"})
    assert len(admins) == 1                                                      # the hidden bot field: ignored
    status, _, _ = _request("/build-request", method="POST", cookie=cookie, form=_form())
    assert status.startswith("403")                                              # CSRF checked
