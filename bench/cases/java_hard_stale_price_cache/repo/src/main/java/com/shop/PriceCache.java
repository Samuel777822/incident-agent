package com.shop;

import java.util.HashMap;
import java.util.Map;

/** Remembers unit prices so the catalogue is not searched on every order. */
public final class PriceCache {
    private static final Map<String, Double> BASE = new HashMap<>();
    private static final Map<String, Double> CACHE = new HashMap<>();

    static {
        reset();
    }

    private PriceCache() {
    }

    public static void reset() {
        BASE.clear();
        CACHE.clear();
        BASE.put("tea", 120.0);
        BASE.put("coffee", 250.0);
        BASE.put("mug", 399.0);
    }

    public static double priceOf(String sku) {
        Double cached = CACHE.get(sku);
        if (cached == null) {
            cached = BASE.get(sku);
            if (cached == null) {
                throw new IllegalArgumentException("no price for " + sku);
            }
            CACHE.put(sku, cached);
        }
        return cached;
    }

    public static void setPrice(String sku, double price) {
        BASE.put(sku, price);
    }
}
