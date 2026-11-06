"""Notification store for the shop. Plain dict-backed so it is easy to test."""
from __future__ import annotations

from datetime import datetime


class NotificationError(Exception):
    pass


class NotificationStore:
    def __init__(self):
        self._items: dict[int, dict] = {}
        self._next_id = 1
        self.audit: list[str] = []

    def _log(self, action: str, item_id: int) -> None:
        self.audit.append(f"{datetime.now().isoformat()} {action} {item_id}")

    def add(self, name: str, **fields) -> int:
        if not name or not name.strip():
            raise NotificationError("name is required")
        item_id = self._next_id
        self._next_id += 1
        self._items[item_id] = {"id": item_id, "name": name.strip(), "active": True, **fields}
        self._log("add", item_id)
        return item_id

    def get(self, item_id: int) -> dict:
        try:
            return dict(self._items[item_id])
        except KeyError:
            raise NotificationError(f"Notification {item_id} not found") from None

    def update(self, item_id: int, **fields) -> dict:
        item = self._items.get(item_id)
        if item is None:
            raise NotificationError(f"Notification {item_id} not found")
        item.update(fields)
        self._log("update", item_id)
        return dict(item)

    def deactivate(self, item_id: int) -> None:
        self.update(item_id, active=False)

    def delete(self, item_id: int) -> None:
        if item_id not in self._items:
            raise NotificationError(f"Notification {item_id} not found")
        del self._items[item_id]
        self._log("delete", item_id)

    def list(self, only_active: bool = True) -> list[dict]:
        rows = [dict(i) for i in self._items.values() if i["active"] or not only_active]
        return sorted(rows, key=lambda r: r["id"])

    def search(self, text: str) -> list[dict]:
        needle = text.strip().lower()
        return [r for r in self.list() if needle in r["name"].lower()]

    def count(self, only_active: bool = True) -> int:
        return len(self.list(only_active))

    def names(self) -> list[str]:
        return [r["name"] for r in self.list()]

    def bulk_add(self, names: list[str]) -> list[int]:
        return [self.add(n) for n in names]

    def export_rows(self) -> list[list]:
        return [[r["id"], r["name"], r["active"]] for r in self.list(False)]

    def summary(self) -> dict:
        return {"total": self.count(False), "active": self.count(True), "audit_events": len(self.audit)}
