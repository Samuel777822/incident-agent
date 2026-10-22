import sys

import pytest

if sys.version_info < (3, 10):
    pytest.exit(
        f"Python 3.10 or newer is required, but this is Python {sys.version.split()[0]} ({sys.executable}). "
        "Install Python 3.12 or 3.13, create a new virtual environment with it, then run: "
        "python -m pip install -r requirements-test.txt", returncode=2)

"""Shared isolated database fixture for legacy daemon tests."""
import pytest
import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    previous_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "incidents.sqlite3")
    db.init_db()
    yield db.DB_PATH
    db.DB_PATH = previous_path


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch):
    """Tests never talk to real email, payment or admin configuration."""
    monkeypatch.setenv("NOTIFY_SYNC", "1")
    for name in ("BREVO_API_KEY", "RESEND_API_KEY", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM",
                 "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "RAZORPAY_MODE",
                 "ADMIN_EMAIL", "UPI_ID", "UPI_PAYEE_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ADMIN_EMAILS", "admin1@example.com,admin2@example.com")
