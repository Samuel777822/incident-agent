import admin
import price_cache
import storefront


def setup_function():
    price_cache.reset()


def test_basket_total():
    assert storefront.basket_total([("tea", 2), ("mug", 1)]) == 639.0


def test_new_price_is_used_by_the_storefront():
    assert storefront.basket_total([("tea", 1)]) == 120.0
    admin.change_price("tea", 150.0)
    assert storefront.basket_total([("tea", 1)]) == 150.0
