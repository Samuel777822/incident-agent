package com.shop;

public class PricingTest {
    public static void run() {
        TestKit.checkEquals("ten percent off 200", 180.0, Pricing.applyDiscount(200, 10));
        TestKit.checkEquals("line total with discount", 270.0, Pricing.lineTotal(100, 3, 10));
        TestKit.checkEquals("tax is 18 percent", 118.0, Pricing.addTax(100));
        TestKit.checkEquals("shipping for two kilos", 65.0, Pricing.shippingCost(2));
        TestKit.expectThrows("bad discount", () -> Pricing.applyDiscount(10, 120), IllegalArgumentException.class);
    }
}
