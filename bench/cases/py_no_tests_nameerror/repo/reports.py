"""Simple sales reports."""


def sales_total(orders: list[dict]) -> float:
    total = 0.0
    for order in orders:
        total += order["total"]
    return round(totl, 2)


def average_order(orders: list[dict]) -> float:
    return round(sales_total(orders) / len(orders), 2) if orders else 0.0
