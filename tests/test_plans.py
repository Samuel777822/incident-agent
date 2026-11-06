"""Plan v2 pricing: one source of truth (plans.py), used by payments, pages, terms and the chatbot."""
import pytest

import chatbot
import footer_pages
import plans
import portal_db


@pytest.fixture
def portal_database(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    portal_db.init_db()


def test_prices_follow_architecture_plan_v2():
    assert plans.PLAN_PRICES == {"monthly": 200, "yearly": 1500}
    assert plans.PLAN_DAYS == {"monthly": 30, "yearly": 365}
    assert plans.YEARLY_PER_MONTH == 125 and plans.YEARLY_SAVING == 900
    assert (plans.PACK_PRICE, plans.PACK_HIGH_TRIES, plans.PACK_EXTRA_TRIES) == (100, 5, 3)


def test_quotas_come_from_the_engine_config():
    assert plans.quotas() == {"normal": 30, "high": 6, "extra": 3}
    assert "30 Normal, 6 High and 3 Extra" in plans.quota_sentence()


def test_old_prices_are_refused_for_new_payments(portal_database):
    user_id = portal_db.create_user("payer@example.com", "hash")
    with pytest.raises(ValueError):
        portal_db.create_manual_payment_request(user_id, 100, "monthly", "412345678901")
    with pytest.raises(ValueError):
        portal_db.create_manual_payment_request(user_id, 1000, "yearly", "412345678902")
    assert portal_db.create_manual_payment_request(user_id, 200, "monthly", "412345678903")["amount"] == 200
    assert portal_db.create_manual_payment_request(user_id, 1500, "yearly", "412345678904")["amount"] == 1500


def test_a_payment_submitted_at_the_old_price_can_still_be_approved(portal_database):
    """Nobody who already paid before the price change is stranded; only an admin approval honours the old amount."""
    user_id = portal_db.create_user("early@example.com", "hash")
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, """INSERT INTO manual_payments
            (id,user_id,amount,plan,transaction_ref,ref_norm,status,created_at)
            VALUES('legacy1',?,100,'monthly','412345678999','412345678999','pending',?)""", (user_id, portal_db._now()))
        conn.commit()
    finally:
        conn.close()
    result = portal_db.approve_manual_payment("legacy1", "admin1@example.com")
    assert result["status"] == "approved" and result["days"] == 30
    assert portal_db.user_has_active_access(user_id)


def test_an_unknown_amount_is_never_approved(portal_database):
    user_id = portal_db.create_user("odd@example.com", "hash")
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, """INSERT INTO manual_payments
            (id,user_id,amount,plan,transaction_ref,ref_norm,status,created_at)
            VALUES('odd1',?,150,'monthly','412345678998','412345678998','pending',?)""", (user_id, portal_db._now()))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ValueError):
        portal_db.approve_manual_payment("odd1", "admin1@example.com")


def test_pricing_page_shows_plan_v2_prices_quotas_and_honest_wording():
    page = footer_pages.pricing_page_html()
    assert "&#8377;200" in page and "&#8377;1,500" in page and "Save &#8377;900" in page
    assert "about &#8377;125 a month" in page
    assert "30 Normal, 6 High and 3 Extra" in page
    assert "not a guaranteed fix" in page and "do not roll over" in page
    assert "&#8377;100 pack" in page
    for claim in ("Unlimited", "Priority worker", "WhatsApp", "&#8377;1,000", "Groq"):
        assert claim not in page, claim


def test_terms_state_prices_quotas_and_no_guarantee():
    terms = footer_pages.terms_of_service_page_html()
    assert "&#8377;200 (30 days)" in terms and "&#8377;1,500 (365 days)" in terms
    assert "30 Normal, 6 High and 3 Extra" in terms
    assert "do not roll over" in terms and "not a guaranteed fix" in terms
    assert "{plans" not in terms


def test_privacy_policy_names_third_party_ai_and_no_longer_claims_code_is_never_cloned():
    privacy = footer_pages.privacy_policy_page_html()
    assert "Third-Party AI Providers" in privacy and "Anthropic" in privacy and "Groq" in privacy
    assert "never clone or execute" not in privacy


def test_chatbot_knowledge_and_fallback_use_plan_v2_prices():
    knowledge = chatbot.DAEMON_KNOWLEDGE
    assert "@@" not in knowledge
    assert "₹200 for 30 days" in knowledge and "₹1,500 for 365 days" in knowledge
    assert "₹100 for 30 days" not in knowledge and "₹1,000" not in knowledge
    assert "30 Normal, 6 High and 3 Extra" in knowledge


def test_prices_can_be_changed_by_environment_without_a_code_change(monkeypatch):
    import importlib
    monkeypatch.setenv("PLAN_PRICE_MONTHLY_INR", "250")
    monkeypatch.setenv("PLAN_PRICE_YEARLY_INR", "not-a-number")
    try:
        importlib.reload(plans)
        assert plans.PLAN_PRICES == {"monthly": 250, "yearly": 1500}      # a bad value falls back to the plan default
    finally:
        monkeypatch.delenv("PLAN_PRICE_MONTHLY_INR", raising=False)
        monkeypatch.delenv("PLAN_PRICE_YEARLY_INR", raising=False)
        importlib.reload(plans)
    assert plans.PLAN_PRICES == {"monthly": 200, "yearly": 1500}
