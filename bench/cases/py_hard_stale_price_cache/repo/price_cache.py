"""Remembers unit prices so the catalogue is not searched on every order."""
_BASE = {"tea": 120.0, "coffee": 250.0, "mug": 399.0}
_CACHE: dict[str, float] = {}


def price_of(sku: str) -> float:
    if sku not in _CACHE:
        _CACHE[sku] = _BASE[sku]
    return _CACHE[sku]


def update_price(sku: str, price: float) -> None:
    _BASE[sku] = price


def reset() -> None:
    _BASE.update({"tea": 120.0, "coffee": 250.0, "mug": 399.0})
    _CACHE.clear()
