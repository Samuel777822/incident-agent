package com.shop;

import java.util.ArrayList;
import java.util.List;

/** A shopping cart that can drop lines the warehouse can no longer supply. */
public final class Cart {
    public record Line(String sku, int qty) {
    }

    private final List<Line> lines = new ArrayList<>();

    public void add(String sku, int qty) {
        lines.add(new Line(sku, qty));
    }

    public int size() {
        return lines.size();
    }

    public int removeUnavailable() {
        int before = lines.size();
        for (Line line : lines) {
            if (Inventory.getStock(line.sku()) < line.qty()) {
                lines.remove(line);
            }
        }
        return before - lines.size();
    }
}
