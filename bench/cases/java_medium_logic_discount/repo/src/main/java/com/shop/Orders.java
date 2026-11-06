package com.shop;

/** Order creation: checks stock, prices the line, reserves the items. */
public final class Orders {
    public record Order(String sku, int qty, double total, double totalWithTax) {
    }

    private Orders() {
    }

    public static Order createOrder(String sku, int qty, double discountPct) {
        if (Inventory.getStock(sku) < qty) {
            throw new Inventory.InventoryException("out of stock: " + sku);
        }
        double total = Pricing.lineTotal(PriceCache.priceOf(sku), qty, discountPct);
        Inventory.reserve(sku, qty);
        return new Order(sku, qty, total, Pricing.addTax(total));
    }
}
