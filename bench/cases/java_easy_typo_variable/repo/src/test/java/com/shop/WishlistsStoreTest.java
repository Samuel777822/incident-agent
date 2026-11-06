package com.shop;

import java.util.Arrays;

public class WishlistsStoreTest {
    public static void run() {
        WishlistsStore s = new WishlistsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("wishlists add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("wishlists missing item throws", () -> new WishlistsStore().get(99), WishlistsStore.WishlistsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("wishlists search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("wishlists active count", 3, s.count(true));
        TestKit.checkEquals("wishlists total count", 4, s.count(false));
        TestKit.checkEquals("wishlists summary", "total=4 active=3 events=5", s.summary());
    }
}
