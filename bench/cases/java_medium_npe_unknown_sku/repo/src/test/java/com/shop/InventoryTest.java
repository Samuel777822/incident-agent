package com.shop;

public class InventoryTest {
    public static void run() {
        Inventory.reset();
        TestKit.checkEquals("tea stock", 40, Inventory.getStock("tea"));
        TestKit.expectThrows("unknown sku", () -> Inventory.getStock("juice"), Inventory.InventoryException.class);
        Inventory.reserve("mug", 4);
        TestKit.checkEquals("reserve lowers stock", 6, Inventory.getStock("mug"));
        TestKit.expectThrows("cannot over-reserve", () -> Inventory.reserve("mug", 50), Inventory.InventoryException.class);
        Inventory.restock("mug", 4);
        TestKit.checkEquals("restock raises stock", 10, Inventory.getStock("mug"));
    }
}
