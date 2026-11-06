"""Pricing rules: discounts, tax and shipping."""
TAX_RATE = 0.18


def apply_discount(price: float, pct: float) -> float:
    if pct < 0 or pct > 100:
        raise ValueError("discount must be between 0 and 100")
    return round(price - price * pct / 100, 2)


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
