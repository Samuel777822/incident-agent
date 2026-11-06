"""Generate realistic 'vibe-coded' test repos (about 1,000+ lines, with tests) containing one real bug each.

    python bench/make_cases.py            # writes bench/cases/<name>/repo and incident.json

The incident's traceback is captured by actually running the broken code, so it looks like a real production error.
Add your own cases by dropping a folder with repo/ and incident.json ({"message": ..., "traceback": ...}) next to these.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases"

GENERIC = '''"""{title} store for the shop. Plain dict-backed so it is easy to test."""
from __future__ import annotations

from datetime import datetime


class {cls}Error(Exception):
    pass


class {cls}Store:
    def __init__(self):
        self._items: dict[int, dict] = {{}}
        self._next_id = 1
        self.audit: list[str] = []

    def _log(self, action: str, item_id: int) -> None:
        self.audit.append(f"{{datetime.now().isoformat()}} {{action}} {{item_id}}")

    def add(self, name: str, **fields) -> int:
        if not name or not name.strip():
            raise {cls}Error("name is required")
        item_id = self._next_id
        self._next_id += 1
        self._items[item_id] = {{"id": item_id, "name": name.strip(), "active": True, **fields}}
        self._log("add", item_id)
        return item_id

    def get(self, item_id: int) -> dict:
        try:
            return dict(self._items[item_id])
        except KeyError:
            raise {cls}Error(f"{title} {{item_id}} not found") from None

    def update(self, item_id: int, **fields) -> dict:
        item = self._items.get(item_id)
        if item is None:
            raise {cls}Error(f"{title} {{item_id}} not found")
        item.update(fields)
        self._log("update", item_id)
        return dict(item)

    def deactivate(self, item_id: int) -> None:
        self.update(item_id, active=False)

    def delete(self, item_id: int) -> None:
        if item_id not in self._items:
            raise {cls}Error(f"{title} {{item_id}} not found")
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
        return {{"total": self.count(False), "active": self.count(True), "audit_events": len(self.audit)}}
'''

GENERIC_TEST = '''import pytest

from {mod} import {cls}Error, {cls}Store


def test_add_and_get():
    s = {cls}Store()
    i = s.add("  Alpha ")
    assert s.get(i)["name"] == "Alpha"


def test_missing_item_raises():
    with pytest.raises({cls}Error):
        {cls}Store().get(99)


def test_search_and_counts():
    s = {cls}Store()
    s.bulk_add(["red", "green", "redder"])
    assert [r["name"] for r in s.search("red")] == ["red", "redder"]
    s.deactivate(1)
    assert s.count() == 2 and s.count(False) == 3
    assert s.summary()["total"] == 3
'''

PRICING = '''"""Pricing rules: discounts, tax and shipping."""
TAX_RATE = 0.18


def apply_discount(price: float, pct: float) -> float:
    if pct < 0 or pct > 100:
        raise ValueError("discount must be between 0 and 100")
    return round(price - price * pct / {div}, 2)


def add_tax(price: float) -> float:
    return round(price * (1 + TAX_RATE), 2)


def shipping_cost(weight_kg: float) -> float:
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    if weight_kg <= 1:
        return 40.0
    return 40.0 + 25.0 * (weight_kg - 1)


def line_total(unit_price: float, qty: int, discount_pct: float = 0) -> float:
    return round(apply_discount(unit_price, discount_pct) * qty, 2)
'''

INVENTORY = '''"""Stock levels per product."""


class OutOfStock(Exception):
    pass


_STOCK: dict[str, int] = {{"tea": 40, "coffee": 25, "mug": 10}}


def {getter}(sku: str) -> int:
    if sku not in _STOCK:
        raise KeyError(sku)
    return _STOCK[sku]


def reserve(sku: str, qty: int) -> None:
    if {getter}(sku) < qty:
        raise OutOfStock(sku)
    _STOCK[sku] -= qty


def restock(sku: str, qty: int) -> None:
    _STOCK[sku] = _STOCK.get(sku, 0) + qty
'''

ORDERS = '''"""Order creation: checks stock, prices lines, reserves items."""
import inventory
import pricing

PRICES = {"tea": 120.0, "coffee": 250.0, "mug": 399.0}


def create_order(items: list[tuple[str, int]], discount_pct: float = 0) -> dict:
    lines, total = [], 0.0
    for sku, qty in items:
        if inventory.get_stock(sku) < qty:
            raise inventory.OutOfStock(sku)
        amount = pricing.line_total(PRICES[sku], qty, discount_pct)
        lines.append({"sku": sku, "qty": qty, "amount": amount})
        total += amount
    for sku, qty in items:
        inventory.reserve(sku, qty)
    return {"lines": lines, "total": round(total, 2), "total_with_tax": pricing.add_tax(total)}
'''

REPORTS = '''"""Simple sales reports."""


def sales_total(orders: list[dict]) -> float:
    total = 0.0
    for order in orders:
        total += order["total"]
    return round({var}, 2)


def average_order(orders: list[dict]) -> float:
    return round(sales_total(orders) / len(orders), 2) if orders else 0.0
'''

BULK = [("users", "User"), ("products", "Product"), ("shipping_rules", "ShippingRule"), ("reviews", "Review"),
        ("coupons", "Coupon"), ("suppliers", "Supplier"), ("categories", "Category"), ("wishlists", "Wishlist"),
        ("returns", "Return"), ("invoices", "Invoice"), ("notifications", "Notification"), ("audit", "Audit")]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def base_repo(repo: Path, *, div="100", getter="get_stock", var="total") -> None:
    for mod, cls in BULK:
        write(repo / f"{mod}.py", GENERIC.format(title=cls, cls=cls))
        write(repo / "tests" / f"test_{mod}.py", GENERIC_TEST.format(mod=mod, cls=cls))
    write(repo / "pricing.py", PRICING.format(div=div))
    write(repo / "inventory.py", INVENTORY.format(getter=getter))
    write(repo / "orders.py", ORDERS)
    write(repo / "reports.py", REPORTS.format(var=var))
    write(repo / "tests" / "test_pricing.py", "from pricing import apply_discount, line_total\n\n\ndef test_discount():\n    assert apply_discount(200, 10) == 180\n\n\ndef test_line():\n    assert line_total(100, 3, 10) == 270\n")
    write(repo / "tests" / "test_orders.py", "import orders\n\n\ndef test_order_total():\n    o = orders.create_order([('tea', 2)], 10)\n    assert o['total'] == 216.0\n")
    write(repo / "tests" / "test_reports.py", "from reports import sales_total\n\n\ndef test_sales_total():\n    assert sales_total([{'total': 10.5}, {'total': 4.5}]) == 15.0\n")
    write(repo / "requirements.txt", "")


def traceback_for(repo: Path, snippet: str) -> str:
    if snippet.startswith("pytest:"):          # a failing assertion, the way a CI log or a support report would show it
        proc = subprocess.run([sys.executable, "-m", "pytest", snippet[7:], "-x", "-q", "--tb=long"], cwd=repo, capture_output=True,
                              text=True, env={"PYTHONPATH": str(repo), "PATH": "/usr/bin:/bin"})
        return proc.stdout.replace(str(repo), "/app")
    proc = subprocess.run([sys.executable, "-c", textwrap.dedent(snippet)], cwd=repo, capture_output=True, text=True)
    return proc.stderr.replace(str(repo), "/app")


CASES = {
    "easy_nameerror": dict(kw=dict(var="totl"), snippet="import reports\nreports.sales_total([{'total': 5}])",
                           message="NameError: name 'totl' is not defined"),
    "medium_logic_discount": dict(kw=dict(div="10"), snippet="pytest:tests/test_pricing.py",
                                  message="Customers were charged 20 instead of 180 for a 10% discount (reported by support)"),
    "medium_cross_file_rename": dict(kw=dict(getter="fetch_stock"), snippet="import orders\norders.create_order([('tea', 1)])",
                                     message="AttributeError: module 'inventory' has no attribute 'get_stock'"),
}


def main() -> None:
    for name in CASES:                      # only remove this generator's own cases (make_cases_v2.py adds others)
        shutil.rmtree(ROOT / name, ignore_errors=True)
    for name, spec in CASES.items():
        repo = ROOT / name / "repo"
        base_repo(repo, **spec["kw"])
        tb = traceback_for(repo, spec["snippet"]) or "Traceback (most recent call last):\n  File \"/app/pricing.py\", line 7, in apply_discount\nValueError: wrong discount\n"
        write(ROOT / name / "incident.json", json.dumps({"message": spec["message"], "traceback": tb}, indent=2))
        lines = sum(len(p.read_text().splitlines()) for p in repo.rglob("*.py"))
        print(f"{name}: {lines} lines of Python")


if __name__ == "__main__":
    main()
