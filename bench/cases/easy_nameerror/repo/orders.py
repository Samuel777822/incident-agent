"""Order creation: checks stock, prices lines, reserves items."""
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
