package com.shop;

import java.util.Arrays;

public class SuppliersStoreTest {
    public static void run() {
        SuppliersStore s = new SuppliersStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("suppliers add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("suppliers missing item throws", () -> new SuppliersStore().get(99), SuppliersStore.SuppliersException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("suppliers search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("suppliers active count", 3, s.count(true));
        TestKit.checkEquals("suppliers total count", 4, s.count(false));
        TestKit.checkEquals("suppliers summary", "total=4 active=3 events=5", s.summary());
    }
}
