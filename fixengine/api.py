"""Small functions the web layer calls (kept out of web_app.py so they can be tested without HTTP)."""
from __future__ import annotations

import portal_db

from . import admin_tools, store
from . import config as fx_config
from .guard import Guard

CHOICES = {"auto", "lower", "higher", "review", "haiku", "sonnet", "opus"}


def usage_view(user_id: str, guard: Guard | None = None) -> dict:
    guard = guard or Guard()
    return {"panel": guard.usage_panel(user_id), "mode": store.get_mode(user_id), "choices": store.list_user_choices(user_id),
            "bugs": store.user_bugs(user_id), "period": store.current_period(), "level_name": guard.level_name()}


def answer_choice(choice_id: str, choice: str, user_id: str) -> bool:
    if choice not in CHOICES:
        return False
    row = store.get_choice(choice_id)
    if not row or row["user_id"] != user_id or row["status"] != "waiting":
        return False
    bug = store.get_bug(row["bug_id"])
    if not bug or not store.resolve_choice(choice_id, choice):
        return False
    paid = list(fx_config.PAID_TIERS)
    warned = row["tier"]
    pin = ""
    if choice in paid:
        pin = choice
    elif choice == "lower":
        pin = paid[max(0, paid.index(warned) - 1)] if warned in paid else ""
    elif choice == "higher":
        pin = paid[min(len(paid) - 1, paid.index(warned) + 1)] if warned in paid else ""
    elif choice == "review":
        pin = "__review__"
    store.set_flag(f"bypass:{bug['id']}:{warned}", "1")
    if pin in paid:
        store.set_flag(f"bypass:{bug['id']}:{pin}", "1")
    store.update_bug(bug["id"], user_pinned_tier=pin, status="open")
    store.unpark_incident(bug["incident_id"], bug["project_id"])
    return True


def set_mode(user_id: str, mode: str) -> bool:
    try:
        store.set_mode(user_id, mode)
        return True
    except ValueError:
        return False


def request_more(user_id: str, tier: str) -> dict:
    if tier not in ("sonnet", "opus"):
        return {"decision": "invalid"}
    return admin_tools.request_more_tries(user_id, tier)


def reopen_bug(bug_id: str, user_id: str) -> bool:
    """User retries a bug that stopped, after getting more tries."""
    bug = store.get_bug(bug_id)
    if not bug or bug["user_id"] != user_id or bug["status"] != "needs_human":
        return False
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE incidents SET status='diagnosing',resolved_at=NULL WHERE id=? AND project_id=?",
                           (bug["incident_id"], bug["project_id"]))
        portal_db._execute(conn, "UPDATE incident_jobs SET status='queued',attempts=0,locked_until=NULL,available_at=?,updated_at=? WHERE incident_id=?",
                           (store.now_s(), store.now_s(), bug["incident_id"]))
        conn.commit()
    finally:
        conn.close()
    store.update_bug(bug_id, status="open", closed_at=None, stop_reason="", user_pinned_tier="")
    return True


def incident_trail(incident_id: str, user_id: str) -> dict | None:
    """What the agent did for one incident, for the owner only. None when the engine never worked on it."""
    bug = store.get_bug_by_incident(incident_id)
    if not bug or bug["user_id"] != user_id:
        return None
    return {"bug": bug, "attempts": store.list_attempts(bug["id"])}


def paths_for_incidents(incident_ids) -> dict:
    return store.paths_for_incidents(incident_ids)
