"""Stock levels per product."""


class OutOfStock(Exception):
    pass


_STOCK: dict[str, int] = {"tea": 40, "coffee": 25, "mug": 10}


def fetch_stock(sku: str) -> int:
    if sku not in _STOCK:
        raise KeyError(sku)
    return _STOCK[sku]


def reserve(sku: str, qty: int) -> None:
    if fetch_stock(sku) < qty:
        raise OutOfStock(sku)
    _STOCK[sku] -= qty


def restock(sku: str, qty: int) -> None:
    _STOCK[sku] = _STOCK.get(sku, 0) + qty
