package com.shop;

import java.util.Arrays;

public class ReturnsStoreTest {
    public static void run() {
        ReturnsStore s = new ReturnsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("returns add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("returns missing item throws", () -> new ReturnsStore().get(99), ReturnsStore.ReturnsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("returns search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("returns active count", 3, s.count(true));
        TestKit.checkEquals("returns total count", 4, s.count(false));
        TestKit.checkEquals("returns summary", "total=4 active=3 events=5", s.summary());
    }
}
