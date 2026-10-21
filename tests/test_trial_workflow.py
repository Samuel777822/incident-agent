import pytest
from types import SimpleNamespace

import portal_db
import web_app


@pytest.fixture
def trial_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "trial.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-at-least-32-chars")
    monkeypatch.setenv("ADMIN_EMAILS", "naveenachandra371@gmail.com,pranavvrao1@gmail.com")
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    portal_db.init_db()


def test_two_allowlisted_admins_are_recognized(trial_env):
    assert web_app._is_admin(SimpleNamespace(session={"email": "naveenachandra371@gmail.com"}))
    assert web_app._is_admin(SimpleNamespace(session={"email": "PRANAVVRAO1@gmail.com"}))
    assert not web_app._is_admin(SimpleNamespace(session={"email": "customer@example.com"}))


def test_trial_request_is_idempotent_and_admin_can_review(trial_env):
    user_id = portal_db.create_user("customer@example.com", "hash")
    first = portal_db.create_trial_request(user_id)
    second = portal_db.create_trial_request(user_id)
    assert first["id"] == second["id"]
    assert second["status"] == "pending"

    reviewed = portal_db.admin_review_trial_request(first["id"], "approved", "naveenachandra371@gmail.com")
    assert reviewed["status"] == "approved"
    assert portal_db.admin_review_trial_request(first["id"], "rejected", "pranavvrao1@gmail.com") is None

    until = portal_db.admin_grant_access(user_id, 1, "trial", "naveenachandra371@gmail.com")
    assert portal_db.user_has_active_access(user_id)
    assert until


def test_plan_amounts_default_to_requested_prices(trial_env, monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-secret")
    monkeypatch.delenv("RAZORPAY_AMOUNT_PAISE", raising=False)
    monkeypatch.delenv("RAZORPAY_MONTHLY_AMOUNT_PAISE", raising=False)
    monkeypatch.delenv("RAZORPAY_YEARLY_AMOUNT_PAISE", raising=False)
    assert web_app._razorpay_settings("monthly")[2] == 10000
    assert web_app._razorpay_settings("yearly")[2] == 100000


def test_payment_order_keeps_selected_plan_and_duration(trial_env):
    user_id = portal_db.create_user("payer@example.com", "hash")
    portal_db.create_payment_order(user_id, "order_month_123", 10000, "monthly")
    portal_db.create_payment_order(user_id, "order_year_123", 100000, "yearly")
    conn = portal_db.get_connection()
    try:
        rows = portal_db._execute(conn, "SELECT plan FROM payment_orders ORDER BY razorpay_order_id", ()).fetchall()
        assert [row["plan"] for row in rows] == ["monthly", "yearly"]
    finally:
        conn.close()
