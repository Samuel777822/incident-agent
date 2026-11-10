from datetime import timedelta

import pytest

import web_app
from fixengine import store
from tests.test_web_app import _request, web_env  # noqa: F401  (reuse the portal's own request helper and fixture)


def _login(email="person@example.com"):
    user_id = web_app.portal_db.create_user(email, "")
    session_id = web_app.portal_db.create_session(user_id, "csrf-token-1", (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    web_app.portal_db.admin_grant_access(user_id, 30, "paid", "test") if not email.startswith("admin") else None
    return user_id, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def _project(user_id, name="shop"):
    return web_app.portal_db.create_project(user_id, name=name, repo_owner="acme", repo_name="shop", branch="main", mode="pr",
                                            token_ciphertext="c", ingest_key_hash="h" + user_id)


def test_usage_requires_sign_in(web_env):
    status, headers, _ = _request("/usage")
    assert status == "303 See Other" and dict(headers)["Location"] == "/login"


def test_usage_page_uses_plain_mode_names_and_never_model_names(web_env):
    user_id, cookie = _login()
    status, _, body = _request("/usage", cookie=cookie)
    assert status == "200 OK"
    for text in ("Your tries this month", "Normal", "High", "Extra", "0 of 30", "0 of 6", "0 of 3"):
        assert text in body
    assert "Low effort" not in body          # v4.1: the free model no longer fixes anything, so it is not shown
    for hidden in ("claude-", "haiku", "sonnet", "opus", "gpt-oss"):
        assert hidden not in body.lower()


def test_changing_the_mode_needs_a_valid_csrf_token(web_env):
    user_id, cookie = _login()
    status, _, _ = _request("/usage/mode", method="POST", cookie=cookie, form={"mode": "economy"})
    assert status == "403 Forbidden" and store.get_mode(user_id) == "auto"
    status, headers, _ = _request("/usage/mode", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "mode": "economy"})
    assert status == "303 See Other" and store.get_mode(user_id) == "economy"
    _request("/usage/mode", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "mode": "nonsense"})
    assert store.get_mode(user_id) == "economy"


def test_pending_decision_is_shown_and_can_be_answered(web_env):
    user_id, cookie = _login()
    project_id = _project(user_id)
    bug = store.create_bug(project_id=project_id, user_id=user_id, incident_id="inc-1", fingerprint_json={"hash": "x"}, bug_class="medium", category="")
    choice_id = store.create_choice(bug["id"], user_id, "sonnet", "You've used 3 of your 6 High-mode tries this month.", 30)
    _, _, body = _request("/usage", cookie=cookie)
    assert "Your decision" in body and "3 of your 6 High-mode tries" in body and "Send to human review" in body
    other_id, other_cookie = _login("other@example.com")
    _request("/usage/choice", method="POST", cookie=other_cookie, form={"csrf": "csrf-token-1", "choice_id": choice_id, "choice": "review"})
    assert store.get_choice(choice_id)["status"] == "waiting"            # someone else cannot answer it
    _request("/usage/choice", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "choice_id": choice_id, "choice": "review"})
    assert store.get_choice(choice_id)["status"] == "resolved" and store.get_bug(bug["id"])["user_pinned_tier"] == "__review__"


def test_asking_for_more_tries_creates_a_grant_or_a_hold(web_env, monkeypatch):
    monkeypatch.setattr("fixengine.notify._to_admins", lambda *a, **k: None)
    user_id, cookie = _login()
    _request("/usage/more", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "kind": "high"})
    assert store.grants_total(user_id, "sonnet", "bonus") == 2 or store.open_hold(user_id, "sonnet")
    _request("/usage/more", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "kind": "bogus"})


def test_bug_list_escapes_hostile_project_names(web_env):
    user_id, cookie = _login()
    project_id = _project(user_id, name="<script>alert(1)</script>")
    store.create_bug(project_id=project_id, user_id=user_id, incident_id="inc-2", fingerprint_json={"hash": "y"}, bug_class="easy", category="")
    _, _, body = _request("/usage", cookie=cookie)
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


def test_admin_budget_page_is_admin_only(web_env):
    _, cookie = _login("person@example.com")
    status, _, _ = _request("/admin/fix", cookie=cookie)
    assert status == "404 Not Found"
    admin_id, admin_cookie = _login("admin1@example.com")
    status, _, body = _request("/admin/fix", cookie=admin_cookie)
    assert status == "200 OK" and "AI spending and controls" in body and "Spending protection" in body and "Mode switches" in body and "Low effort" in body


def test_admin_can_pause_and_resume_a_mode_with_csrf(web_env):
    admin_id, cookie = _login("admin1@example.com")
    status, _, _ = _request("/admin/fix", method="POST", cookie=cookie, form={"action": "pause", "tier": "opus"})
    assert status == "403 Forbidden" and "opus" not in store.paused_tiers()
    _request("/admin/fix", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "action": "pause", "tier": "opus"})
    assert "opus" in store.paused_tiers()
    _, _, body = _request("/admin/fix", cookie=cookie)
    assert "Paused" in body
    _request("/admin/fix", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "action": "resume", "tier": "opus"})
    assert "opus" not in store.paused_tiers()
    _, _, body = _request("/admin/fix", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "action": "pause", "tier": "nope"})
    assert "not valid" in body


def test_admin_approves_a_held_request(web_env, monkeypatch):
    monkeypatch.setattr("fixengine.notify._to_admins", lambda *a, **k: None)
    user_id, _ = _login("person@example.com")
    hold_id = store.create_hold(user_id, "opus", 2, {"projected_fraction": 0.9})
    admin_id, cookie = _login("admin1@example.com")
    _, _, body = _request("/admin/fix", cookie=cookie)
    assert "person@example.com" in body and "Approve" in body
    _request("/admin/fix", method="POST", cookie=cookie, form={"csrf": "csrf-token-1", "action": "approve_hold", "hold_id": hold_id})
    assert store.get_hold(hold_id)["status"] == "granted" and store.grants_total(user_id, "opus", "admin") == 2


def test_dashboard_links_to_usage(web_env):
    user_id, cookie = _login()
    _, _, body = _request("/dashboard", cookie=cookie)
    assert "/usage" in body


def test_admin_can_credit_a_paid_pack(web_env):
    user_id, _ = _login("person@example.com")
    admin_id, cookie = _login("admin1@example.com")
    _, _, body = _request("/admin/fix", method="POST", cookie=cookie,
                          form={"csrf": "csrf-token-1", "action": "sell_pack", "email": "person@example.com", "kind": "extra"})
    assert "Pack credited" in body and store.grants_total(user_id, "opus", "pack") == 3
    _, _, body = _request("/admin/fix", method="POST", cookie=cookie,
                          form={"csrf": "csrf-token-1", "action": "sell_pack", "email": "nobody@example.com", "kind": "extra"})
    assert "No customer" in body
