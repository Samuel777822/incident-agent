package com.shop;

import java.util.HashMap;
import java.util.Map;

/** Stock levels per product. */
public final class Inventory {
    public static class InventoryException extends RuntimeException {
        public InventoryException(String message) {
            super(message);
        }
    }

    private static final Map<String, Integer> STOCK = new HashMap<>();

    static {
        reset();
    }

    private Inventory() {
    }

    public static void reset() {
        STOCK.clear();
        STOCK.put("tea", 40);
        STOCK.put("coffee", 25);
        STOCK.put("mug", 10);
    }

    public static int getStock(String sku) {
        return STOCK.get(sku);
    }

    public static void reserve(String sku, int qty) {
        if (getStock(sku) < qty) {
            throw new InventoryException("out of stock: " + sku);
        }
        STOCK.put(sku, getStock(sku) - qty);
    }

    public static void restock(String sku, int qty) {
        STOCK.put(sku, STOCK.getOrDefault(sku, 0) + qty);
    }
}
