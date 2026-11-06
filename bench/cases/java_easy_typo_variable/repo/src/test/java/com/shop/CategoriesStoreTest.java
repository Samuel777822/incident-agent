package com.shop;

import java.util.Arrays;

public class CategoriesStoreTest {
    public static void run() {
        CategoriesStore s = new CategoriesStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("categories add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("categories missing item throws", () -> new CategoriesStore().get(99), CategoriesStore.CategoriesException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("categories search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("categories active count", 3, s.count(true));
        TestKit.checkEquals("categories total count", 4, s.count(false));
        TestKit.checkEquals("categories summary", "total=4 active=3 events=5", s.summary());
    }
}
