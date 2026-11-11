"""Rs 30 buys 20 more Normal tries for this month."""
import pytest

import plans
import portal_db
from fixengine import admin_tools, guard as fx_guard, store
from tests.test_push_guard import make_session
from test_web_app import _request, web_env  # noqa: F401  (fixture)


def test_the_normal_pack_is_rs_30_for_20_tries():
    assert plans.PRODUCTS["pack_normal"] == {"label": "20 Normal tries", "rupees": 30, "days": 0}
    assert "pack_normal" in plans.ADDON_PRODUCTS and plans.product_grant_text("pack_normal") == "add 20 Normal tries"


def test_paying_for_it_adds_20_normal_tries_this_month(web_env):
    user_id, csrf, cookie = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    with pytest.raises(ValueError):
        portal_db.create_manual_payment_request(user_id, 100, "pack_normal", "123456789020")        # the price is fixed
    pay = portal_db.create_manual_payment_request(user_id, 30, "pack_normal", "123456789021")
    result = portal_db.approve_manual_payment(pay["id"], "admin1@example.com")
    assert result["credited"] == {"tier": "haiku", "tries": 20}
    q = fx_guard.Guard().quota(user_id, "haiku")
    assert q["total"] == 50 and q["left"] == 50 and q["pack_left"] == 20


def test_the_pack_is_offered_on_usage_billing_and_pricing(web_env):
    user_id, csrf, cookie = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    _, _, usage = _request("/usage", cookie=cookie)
    assert "plan=pack_normal" in usage and "20 Normal tries · ₹30" in usage
    _, _, billing = _request("/billing", cookie=cookie)
    assert "plan=pack_normal" in billing and "Pay ₹30 by UPI" in billing
    _, _, upi = _request("/billing/pay?plan=pack_normal", cookie=cookie)
    assert "am=30.00" in upi and "20 Normal tries" in upi
    _, _, pricing = _request("/pricing")
    assert "Normal pack" in pricing and "20 more Normal tries" in pricing


def test_an_admin_can_credit_the_normal_pack_by_hand(fx_db):
    from tests import fx_helpers as H
    uid, _ = H.make_user_and_project()
    assert admin_tools.sell_pack(uid, "normal", "admin@example.com") == {"tier": "haiku", "tries": 20}
    assert store.grants_total(uid, "haiku", "pack") == 20


from tests.test_fixengine_core import fx_db  # noqa: E402,F401  (fixture)
