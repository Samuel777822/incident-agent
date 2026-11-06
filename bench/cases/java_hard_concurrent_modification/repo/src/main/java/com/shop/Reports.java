package com.shop;

import java.util.List;

/** Simple sales reports. */
public final class Reports {
    private Reports() {
    }

    public static double salesTotal(List<Double> orders) {
        double total = 0.0;
        for (double amount : orders) {
            total += amount;
        }
        return Math.round(total * 100.0) / 100.0;
    }

    public static double averageOrder(List<Double> orders) {
        return orders.isEmpty() ? 0.0 : Math.round(salesTotal(orders) / orders.size() * 100.0) / 100.0;
    }
}
