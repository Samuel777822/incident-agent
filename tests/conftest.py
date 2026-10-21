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
