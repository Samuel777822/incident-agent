package com.shop;

import java.util.Arrays;

public class NotificationsStoreTest {
    public static void run() {
        NotificationsStore s = new NotificationsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("notifications add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("notifications missing item throws", () -> new NotificationsStore().get(99), NotificationsStore.NotificationsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("notifications search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("notifications active count", 3, s.count(true));
        TestKit.checkEquals("notifications total count", 4, s.count(false));
        TestKit.checkEquals("notifications summary", "total=4 active=3 events=5", s.summary());
    }
}
