"""v6: Basic has no Lead engineer, so when the Engineer cannot finish the founders are offered; big jobs can be sent to the
founders from any page with a short form."""
import json

from fixengine import store
import portal_db
from tests import fx_helpers as H
from tests.test_v4_agent import _engine, call, reply
from tests.test_web_app import _request, web_env  # noqa: F401  (fixture)


def test_basic_offers_the_founders_when_the_engineer_cannot_finish(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("give_up", reason="too big", findings="x"))]})
    uid = store.get_project_row(pid)["user_id"]
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE subscriptions SET plan='basic' WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_human"
    assert store.get_flag(f"founder_offer:{inc}") == "1" and not store.get_flag(f"guide_offer:{inc}")
    assert "sonnet" not in transports or not transports["sonnet"].calls          # Basic never pays for the Lead engineer


def test_the_build_request_form_emails_the_founders(web_env, monkeypatch):
    import notifications
    from tests.test_v3_web import _setup
    sent = []
    monkeypatch.setattr(notifications, "notify_admins", lambda subject, body, kind="admin": sent.append((subject, body)) or [])
    _user, csrf, cookie, _pid = _setup()
    status, _, page = _request("/build-request", cookie=cookie)
    assert status == "200 OK" and "Ask the founders to build it" in page and "Rs 2,000" in page
    _, _, page = _request("/build-request", method="POST", cookie=cookie, form={"csrf": csrf, "kind": "app", "what": "A booking app for my clinic"})
    assert "Sent." in page and sent and "whole app" in sent[0][0] and "booking app" in sent[0][1]
    status, _, _ = _request("/build-request", method="POST", cookie=cookie, form={"kind": "app", "what": "no csrf here at all"})
    assert status.startswith("403")
    assert _request("/build-request")[0].startswith("30")                       # sign-in needed
