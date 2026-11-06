package com.shop;

import java.util.Arrays;

public class UsersStoreTest {
    public static void run() {
        UsersStore s = new UsersStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("users add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("users missing item throws", () -> new UsersStore().get(99), UsersStore.UsersException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("users search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("users active count", 3, s.count(true));
        TestKit.checkEquals("users total count", 4, s.count(false));
        TestKit.checkEquals("users summary", "total=4 active=3 events=5", s.summary());
    }
}
