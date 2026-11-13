"""v6 plans and usage bars: Basic Rs 200 (Engineer bar), Pro Rs 500 (Engineer + Lead engineer), Rs 99 top-ups, old packs keep
their value, and a bar empty for one model never stops the other."""
import plans
import portal_db
from fixengine import guard as fx_guard, store
from tests.test_web_app import _request, web_env  # noqa: F401  (fixture)


def _user(email="u@example.com"):
    return portal_db.create_user(email, "hash", "U")


def _attempt(uid, tier, cost):
    pid = portal_db.create_project(uid, name="p", repo_owner="o", repo_name="r" + store.new_id()[:6], branch="main", mode="pr",
                                   token_ciphertext="x", ingest_key_hash="h" + store.new_id())
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id=store.new_id(), fingerprint_json={"hash": store.new_id()},
                           bug_class="easy", category="")
    a = store.add_attempt(bug=bug, tier=tier, model="m", used_strong_diag=False, info_hash=store.new_id())
    store.finish_attempt(a, result="fail", cost_inr=cost)


def test_the_plan_comes_from_the_subscription(web_env):
    uid = _user()
    assert plans.user_plan(uid) == "none"
    portal_db.admin_grant_access(uid, 1, "trial", "admin")
    assert plans.user_plan(uid) == "trial"
    portal_db.admin_grant_access(uid, 30, "paid", "admin")
    assert plans.user_plan(uid) == "basic"                      # paid without a plan = Basic (everyone who paid before v6)
    portal_db.admin_grant_access(uid, 30, "paid", "admin", plan="pro")
    assert plans.user_plan(uid) == "pro"


def test_a_pro_payment_gives_pro_and_its_two_bars(web_env):
    uid = _user()
    pay = portal_db.create_manual_payment_request(uid, 500, "pro", "123412341234")
    result = portal_db.approve_manual_payment(pay["id"], "admin@example.com")
    assert result["days"] == 30 and plans.user_plan(uid) == "pro"
    g = fx_guard.Guard()
    assert g.bar(uid, "haiku")["total"] == 230 and g.bar(uid, "sonnet")["total"] == 64


def test_basic_has_no_lead_bar_and_says_it_is_part_of_pro(web_env):
    uid = _user()
    portal_db.admin_grant_access(uid, 30, "paid", "admin")
    res = fx_guard.Guard().check(uid, "sonnet")
    assert not res.ok and res.code == "not_in_plan" and "Pro" in res.message
    assert fx_guard.Guard().check(uid, "haiku").ok


def test_an_empty_engineer_bar_never_stops_the_lead_and_a_top_up_refills_it(web_env):
    from fixengine import admin_tools
    uid = _user()
    portal_db.admin_grant_access(uid, 30, "paid", "admin", plan="pro")
    _attempt(uid, "haiku", 230.0)
    g = fx_guard.Guard()
    assert g.check(uid, "haiku").code == "exhausted" and g.check(uid, "sonnet").ok
    admin_tools.sell_topup(uid, "haiku")
    assert g.check(uid, "haiku").ok and g.bar(uid, "haiku")["left"] == 58.0


def test_old_packs_can_still_be_approved_and_count_as_bar_rupees(web_env):
    uid = _user()
    portal_db.admin_grant_access(uid, 30, "paid", "admin")
    assert plans.valid_amount("pack_normal", 30) and "pack_normal" not in plans.PRODUCTS     # not for sale any more
    conn = portal_db.get_connection()
    try:                                                         # a payment submitted for an old pack before v6
        portal_db._execute(conn, """INSERT INTO manual_payments(id,user_id,plan,amount,transaction_ref,status,created_at)
            VALUES(?,?,?,?,?,?,?)""", ("old1", uid, "pack_normal", 30, "111122223333", "pending", "2026-11-01T00:00:00+00:00"))
        conn.commit()
    finally:
        conn.close()
    result = portal_db.approve_manual_payment("old1", "admin@example.com")
    assert result["status"] == "approved"
    assert round(fx_guard.Guard().bar(uid, "haiku")["total"], 1) == 118 + 18.0         # 20 old Normal tries = Rs 18 of bar


def test_the_usage_page_shows_bars_not_rupees(web_env):
    from tests.test_fixengine_web import _login
    uid, cookie = _login()
    _, _, body = _request("/usage", cookie=cookie)
    assert "Your AI this month" in body and "small fixes left" in body and "Top up · ₹99" in body
    assert "Rs 118" not in body and "₹118" not in body
