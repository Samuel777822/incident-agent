"""v6 diagnose first: a problem the agent catches by itself is only diagnosed (what broke, why, the proposed fix, what it will
use of the bars). Nothing changes until the owner presses "Yes, fix it"; "That's not it" makes it look again; big jobs go to the
founders. The owner's own requests skip the question."""
import json

import portal_db
from fixengine import store
from tests import fx_helpers as H
from tests.test_v4_agent import FIX, _engine, call, reply
from tests.test_web_app import web_env  # noqa: F401  (fixture)

DIAG = dict(what_broke="Discounts are ten times too big at checkout", why="pricing.py divides the percent by 10 instead of 100",
            where=["pricing.py"], proposed_fix="Divide by 100 in apply_discount", size="small", is_code_problem=True, owner_steps=[],
            confidence="high")


def _asking(engine, pid):
    store.set_flag(f"autofix:{pid}", "")             # the default: ask before fixing


def test_a_caught_error_is_diagnosed_and_waits_for_the_owner(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("read_file", path="pricing.py")),
                                                                              reply(call("report_diagnosis", **DIAG))] + list(FIX)})
    _asking(engine, pid)
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "awaiting_approval"
    d = json.loads(store.get_flag(f"diagnosis:{inc}"))
    assert d["what_broke"].startswith("Discounts") and d["size"] == "small" and d["by"] == "haiku"
    assert d["est_engineer_pct"] == 3 and d["est_lead_pct"] == 0                 # Pro: Rs 8 of a Rs 230 Engineer bar
    assert not prs and portal_db.get_incident_row(inc)["stage"] == "awaiting_approval"
    tools = [t["function"]["name"] for t in transports["haiku"].calls[0]["tools"]]
    assert "edit_file" not in tools and "run_checks" not in tools and "report_diagnosis" in tools   # read-only
    # The owner presses "Yes, fix it": the engineer fixes it (with the diagnosis) and opens the pull request.
    store.set_flag(f"fix_approved:{inc}", json.dumps({"style": "proper"}))
    portal_db.reopen_incident_with_reply(inc, pid, "Yes, fix it (proper fix with a test)")
    assert engine.handle_incident(H.claim()) == "pr_opened"
    assert "pct / 100" in prs[0]["new_files"]["pricing.py"]
    bug = store.get_bug_by_incident(inc)
    assert store.get_flag(f"approved:{bug['id']}") == "proper"
    assert [a["result"] for a in store.list_attempts(bug["id"])][:1] == ["diagnosis"]


def test_the_owners_own_request_is_not_asked_again(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": list(FIX)})
    _asking(engine, pid)
    iid, _ = portal_db.ingest_event(pid, timestamp="2026-11-13T10:00:00Z", level="ERROR", message="[user report] discounts wrong",
                                    traceback='[evidence] {"kind": "user_report", "owner_report": "discounts are 10x too big"}\n',
                                    signature="user_report:abc")
    assert engine.handle_incident(H.claim()) == "pr_opened" and not store.get_flag(f"diagnosis:{iid}")


def test_a_problem_outside_the_code_becomes_steps_for_the_owner(tmp_path, monkeypatch):
    outside = {**DIAG, "is_code_problem": False, "owner_steps": ["Open Render, Environment.", "Add OPENROUTER_API_KEY."]}
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("report_diagnosis", **outside))]})
    _asking(engine, pid)
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_owner"
    assert not prs and "OPENROUTER_API_KEY" in portal_db.get_incident_row(inc)["live_result"]


def test_basic_stops_guessing_after_two_misses_and_offers_the_founders(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("report_diagnosis", **DIAG)),
                                                                              reply(call("report_diagnosis", **DIAG))]})
    _asking(engine, pid)
    uid = store.get_project_row(pid)["user_id"]
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE subscriptions SET plan='basic' WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()
    inc = H.make_incident(pid)
    for i in range(2):
        assert engine.handle_incident(H.claim()) == "awaiting_approval"
        store.set_flag(f"diagnosis_rejected:{inc}", "1")
        portal_db.reopen_incident_with_reply(inc, pid, f"THAT'S NOT IT ({i + 1}): the totals are fine, the coupon box is broken")
    assert engine.handle_incident(H.claim()) == "awaiting_approval"
    assert store.get_flag(f"founder_offer:{inc}") == "1" and "founders" in portal_db.get_incident_row(inc)["stage_detail"]


# ---- the case page -----------------------------------------------------------------------------------------------------------
def test_the_case_card_shows_the_diagnosis_and_the_owners_buttons(tmp_path, monkeypatch):
    import incident_board
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {})
    inc = H.make_incident(pid)
    store.set_flag(f"diagnosis:{inc}", json.dumps({**DIAG, "est_engineer_pct": 7, "est_lead_pct": 14}))
    html = incident_board.diagnosis_box_html({"id": inc}, pid, "tok")
    for text in ("What broke:", "Why:", "The fix:", "Yes, fix it", "Proper fix", "Quick fix", "That's not it",
                 "about 7% of your Engineer bar", "14% of your Lead engineer bar", "rejects_diagnosis"):
        assert text in html, text
    assert "Send it to the founders" not in html
    store.set_flag(f"founder_offer:{inc}", "1")
    assert "Send it to the founders" in incident_board.diagnosis_box_html({"id": inc}, pid, "tok")
    assert incident_board.diagnosis_box_html({"id": "nothing"}, pid, "tok") == ""


def test_yes_fix_it_and_thats_not_it_and_the_founders_buttons_work(web_env, monkeypatch):
    import notifications
    from tests.test_web_app import _request
    from tests.test_v3_web import _setup
    sent = []
    monkeypatch.setattr(notifications, "notify_admins", lambda subject, body, kind="admin": sent.append(subject) or [])
    user_id, csrf, cookie, pid = _setup()
    inc = H.make_incident(pid)
    store.set_flag(f"diagnosis:{inc}", json.dumps(DIAG))
    status, headers, _ = _request(f"/projects/{pid}/incidents/{inc}/approve", method="POST", cookie=cookie,
                                  form={"csrf": csrf, "style": "quick"})
    assert status.startswith("30") and "case=approved" in dict(headers)["Location"]
    assert json.loads(store.get_flag(f"fix_approved:{inc}")) == {"style": "quick"}
    _request(f"/projects/{pid}/incidents/{inc}/reply", method="POST", cookie=cookie,
             form={"csrf": csrf, "text": "No, the coupon box is broken", "rejects_diagnosis": "1"})
    assert store.get_flag(f"diagnosis_rejected:{inc}") == "1"
    status, headers, _ = _request(f"/projects/{pid}/incidents/{inc}/founders", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "case=founders" in dict(headers)["Location"] and sent and store.get_flag(f"founder_request:{inc}") == "1"
    status, _, _ = _request(f"/projects/{pid}/incidents/{inc}/approve", method="POST", cookie=cookie, form={})
    assert status.startswith("403")                                              # CSRF checked
    _request(f"/projects/{pid}/fix-without-asking", method="POST", cookie=cookie, form={"csrf": csrf, "autofix": "on"})
    assert store.get_flag(f"autofix:{pid}") == "1"


def test_the_fix_run_gets_the_approved_diagnosis_and_the_owners_choice(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("report_diagnosis", **DIAG))] + list(FIX)})
    _asking(engine, pid)
    inc = H.make_incident(pid)
    engine.handle_incident(H.claim())
    store.set_flag(f"fix_approved:{inc}", json.dumps({"style": "quick"}))
    portal_db.reopen_incident_with_reply(inc, pid, "Yes, fix it (quick fix)")
    assert engine.handle_incident(H.claim()) == "pr_opened"
    fix_brief = json.dumps(transports["haiku"].calls[1]["messages"][1]["content"])
    assert "THE OWNER APPROVED THIS DIAGNOSIS" in fix_brief and "QUICK FIX" in fix_brief and "divides the percent by 10" in fix_brief
