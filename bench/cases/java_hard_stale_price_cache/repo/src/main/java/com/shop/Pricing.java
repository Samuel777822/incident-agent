package com.shop;

/** Pricing rules: discounts, tax and shipping. */
public final class Pricing {
    public static final double TAX_RATE = 0.18;

    private Pricing() {
    }

    public static double applyDiscount(double price, double pct) {
        if (pct < 0 || pct > 100) {
            throw new IllegalArgumentException("discount must be between 0 and 100");
        }
        return round2(price - price * pct / 100);
    }

    public static double addTax(double price) {
        return round2(price * (1 + TAX_RATE));
    }

    public static double shippingCost(double weightKg) {
        if (weightKg <= 0) {
            throw new IllegalArgumentException("weight must be positive");
        }
        if (weightKg <= 1) {
            return 40.0;
        }
        return 40.0 + 25.0 * (weightKg - 1);
    }

    public static double lineTotal(double unitPrice, int qty, double discountPct) {
        return round2(applyDiscount(unitPrice, discountPct) * qty);
    }

    static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
