package com.shop;

/** Runs every test class and exits with a non-zero status when anything failed. */
public class AllTests {
    private static void runOne(String name, Runnable test) {
        try {
            test.run();
        } catch (Throwable t) {
            TestKit.failure(name, t);
        }
    }

    public static void main(String[] args) {
        runOne("PricingTest", PricingTest::run);
        runOne("InventoryTest", InventoryTest::run);
        runOne("OrdersTest", OrdersTest::run);
        runOne("CartTest", CartTest::run);
        runOne("ReportsTest", ReportsTest::run);
        runOne("UsersStoreTest", UsersStoreTest::run);
        runOne("ProductsStoreTest", ProductsStoreTest::run);
        runOne("ShippingRulesStoreTest", ShippingRulesStoreTest::run);
        runOne("ReviewsStoreTest", ReviewsStoreTest::run);
        runOne("CouponsStoreTest", CouponsStoreTest::run);
        runOne("SuppliersStoreTest", SuppliersStoreTest::run);
        runOne("CategoriesStoreTest", CategoriesStoreTest::run);
        runOne("WishlistsStoreTest", WishlistsStoreTest::run);
        runOne("ReturnsStoreTest", ReturnsStoreTest::run);
        runOne("InvoicesStoreTest", InvoicesStoreTest::run);
        runOne("NotificationsStoreTest", NotificationsStoreTest::run);
        runOne("AuditsStoreTest", AuditsStoreTest::run);
        TestKit.finish();
    }
}
