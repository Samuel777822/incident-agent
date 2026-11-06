import pytest

from notifications import NotificationError, NotificationStore


def test_add_and_get():
    s = NotificationStore()
    i = s.add("  Alpha ")
    assert s.get(i)["name"] == "Alpha"


def test_missing_item_raises():
    with pytest.raises(NotificationError):
        NotificationStore().get(99)


def test_search_and_counts():
    s = NotificationStore()
    s.bulk_add(["red", "green", "redder"])
    assert [r["name"] for r in s.search("red")] == ["red", "redder"]
    s.deactivate(1)
    assert s.count() == 2 and s.count(False) == 3
    assert s.summary()["total"] == 3
