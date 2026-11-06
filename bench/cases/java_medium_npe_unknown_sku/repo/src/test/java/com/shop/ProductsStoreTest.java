package com.shop;

import java.util.Arrays;

public class ProductsStoreTest {
    public static void run() {
        ProductsStore s = new ProductsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("products add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("products missing item throws", () -> new ProductsStore().get(99), ProductsStore.ProductsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("products search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("products active count", 3, s.count(true));
        TestKit.checkEquals("products total count", 4, s.count(false));
        TestKit.checkEquals("products summary", "total=4 active=3 events=5", s.summary());
    }
}
