package com.shop;

import java.util.Arrays;

public class AuditsStoreTest {
    public static void run() {
        AuditsStore s = new AuditsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("audits add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("audits missing item throws", () -> new AuditsStore().get(99), AuditsStore.AuditsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("audits search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("audits active count", 3, s.count(true));
        TestKit.checkEquals("audits total count", 4, s.count(false));
        TestKit.checkEquals("audits summary", "total=4 active=3 events=5", s.summary());
    }
}
