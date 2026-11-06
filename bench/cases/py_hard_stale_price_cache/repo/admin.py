"""Admin actions: change prices and show them."""
import price_cache


def change_price(sku: str, new_price: float) -> float:
    if new_price <= 0:
        raise ValueError("price must be positive")
    price_cache.update_price(sku, new_price)
    return price_cache.price_of(sku)
