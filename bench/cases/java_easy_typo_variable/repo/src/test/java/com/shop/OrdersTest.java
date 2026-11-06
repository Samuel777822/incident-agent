package com.shop;

public class OrdersTest {
    public static void run() {
        Inventory.reset();
        PriceCache.reset();
        Orders.Order order = Orders.createOrder("tea", 2, 10);
        TestKit.checkEquals("order total with discount", 216.0, order.total());
        TestKit.checkEquals("order total with tax", 254.88, order.totalWithTax());
        TestKit.expectThrows("unknown sku in an order", () -> Orders.createOrder("juice", 1, 0), Inventory.InventoryException.class);
        PriceCache.reset();
        Orders.createOrder("coffee", 1, 0);
        PriceCache.setPrice("coffee", 300.0);
        TestKit.checkEquals("a changed price is used by the next order", 300.0, Orders.createOrder("coffee", 1, 0).total());
    }
}
