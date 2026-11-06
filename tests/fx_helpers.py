"""Shared helpers for the fix-engine tests."""
from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path

import portal_db

BUGGY_PRICING = '''def apply_discount(price, pct):
    result = price - price * pct / 10
    if result < 0:
        raise ValueError("negative price computed")
    return result
'''
BUGGY_TEST = '''from pricing import apply_discount


def test_ten_percent_off():
    assert apply_discount(200, 10) == 180
'''
GOOD_EDIT = {"file_path": "pricing.py", "old_text": "price * pct / 10\n", "new_text": "price * pct / 100\n"}
WRONG_EDIT = {"file_path": "pricing.py", "old_text": "price * pct / 10\n", "new_text": "price * pct / 50\n"}
TRACEBACK = ('Traceback (most recent call last):\n  File "/app/pricing.py", line 4, in apply_discount\n'
             '    raise ValueError("negative price computed")\nValueError: negative price computed\n')


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "customer_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pricing.py").write_text(BUGGY_PRICING)
    (repo / "tests" / "test_pricing.py").write_text(BUGGY_TEST)
    (repo / "requirements.txt").write_text("")
    return repo


def repo_provider(repo: Path):
    @contextlib.contextmanager
    def provider(project):
        tmp = Path(tempfile.mkdtemp(prefix="fx-test-repo-"))
        try:
            shutil.copytree(repo, tmp / "r")
            yield tmp / "r"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return provider


def make_user_and_project(email="dev@example.com", mode="pr"):
    user_id = portal_db.create_user(email, "hash", "Dev")
    project_id = portal_db.create_project(user_id, name="shop", repo_owner="acme", repo_name="shop", branch="main", mode=mode,
                                          token_ciphertext="x", ingest_key_hash="h" + email, ai_consent_at="2026-01-01T00:00:00+00:00")
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE projects SET active_until='2099-01-01T00:00:00+00:00' WHERE id=?", (project_id,))
        conn.commit()
    finally:
        conn.close()
    return user_id, project_id


def make_incident(project_id, message="negative price computed", traceback=TRACEBACK, ts="2020-01-01T10:00:00Z"):
    incident_id, _ = portal_db.ingest_event(project_id, timestamp=ts, level="ERROR", message=message, traceback=traceback,
                                            signature="ValueError:pricing.py:4")
    return incident_id


def claim():
    return portal_db.claim_next_incident(min_occurrences=1, min_age_seconds=0)
