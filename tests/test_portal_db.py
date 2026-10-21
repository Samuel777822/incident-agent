import pytest

import portal_db


@pytest.fixture
def portal_database(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    portal_db.init_db()


def _project(user_id, suffix="one"):
    return portal_db.create_project(
        user_id,
        name=f"project {suffix}",
        repo_owner="example",
        repo_name=f"app-{suffix}",
        branch="main",
        mode="pr",
        token_ciphertext="encrypted-token",
        ingest_key_hash=f"hash-{suffix}",
    )


def test_projects_are_scoped_to_the_owner(portal_database):
    owner = portal_db.create_user("owner@example.com", "hash")
    other = portal_db.create_user("other@example.com", "hash")
    project_id = _project(owner)

    assert portal_db.get_project(project_id, owner)["repo_name"] == "app-one"
    assert portal_db.get_project(project_id, other) is None
    assert portal_db.list_projects(other) == []


def test_ingest_deduplicates_and_groups_by_project(portal_database):
    owner = portal_db.create_user("owner@example.com", "hash")
    first_project = _project(owner, "one")
    second_project = _project(owner, "two")
    event = {
        "timestamp": "2026-10-21T10:00:00Z",
        "level": "ERROR",
        "message": "checkout failed",
        "traceback": "KeyError: price",
        "signature": "KeyError:main.py:10",
    }

    incident_id, inserted = portal_db.ingest_event(first_project, **event)
    duplicate_id, duplicate_inserted = portal_db.ingest_event(first_project, **event)
    other_incident_id, other_inserted = portal_db.ingest_event(second_project, **event)

    assert inserted is True and incident_id
    assert duplicate_inserted is False and duplicate_id is None
    assert other_inserted is True and other_incident_id != incident_id
    assert portal_db.list_incidents(first_project)[0]["occurrences"] == 1
    assert portal_db.list_incidents(second_project)[0]["occurrences"] == 1


def test_login_rate_limit_is_per_key(portal_database):
    assert all(portal_db.check_login_rate_limit("ip-a", maximum=2) for _ in range(2))
    assert portal_db.check_login_rate_limit("ip-a", maximum=2) is False
    assert portal_db.check_login_rate_limit("ip-b", maximum=2) is True


def test_payment_is_applied_once_and_activates_projects(portal_database):
    user_id = portal_db.create_user("payer@example.com", "hash")
    project_id = _project(user_id)
    portal_db.create_payment_order(user_id, "order_123abc", 49900)

    assert portal_db.complete_payment_order("order_123abc", "pay_123abc", 49900) is True
    assert portal_db.complete_payment_order("order_123abc", "pay_123abc", 49900) is False
    assert portal_db.get_project(project_id, user_id)["active_until"]
    later_project_id = _project(user_id, "later")
    assert portal_db.get_project(later_project_id, user_id)["active_until"] == portal_db.get_subscription_active_until(user_id)


def test_ingest_key_rotation_and_project_deletion_are_owner_scoped(portal_database):
    owner = portal_db.create_user("owner@example.com", "hash")
    other = portal_db.create_user("other@example.com", "hash")
    project_id = _project(owner)
    portal_db.ingest_event(project_id, timestamp="2026-10-21T10:00:00Z", level="ERROR",
        message="failure", traceback="ValueError", signature="ValueError:app.py:1")

    assert portal_db.rotate_project_ingest_key(project_id, other, "wrong-owner-hash") is False
    assert portal_db.rotate_project_ingest_key(project_id, owner, "rotated-hash") is True
    assert portal_db.get_project_by_ingest_hash("hash-one") is None
    assert portal_db.get_project_by_ingest_hash("rotated-hash")["id"] == project_id
    assert portal_db.delete_project(project_id, other) is False
    assert portal_db.delete_project(project_id, owner) is True
    assert portal_db.get_project(project_id, owner) is None
    assert portal_db.list_incidents(project_id) == []
