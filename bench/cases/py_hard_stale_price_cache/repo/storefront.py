"""Storefront: what a customer pays for a basket."""
import price_cache


def basket_total(items: list[tuple[str, int]]) -> float:
    return round(sum(price_cache.price_of(sku) * qty for sku, qty in items), 2)
