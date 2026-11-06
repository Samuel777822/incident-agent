package com.shop;

import java.util.Arrays;

public class CouponsStoreTest {
    public static void run() {
        CouponsStore s = new CouponsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("coupons add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("coupons missing item throws", () -> new CouponsStore().get(99), CouponsStore.CouponsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("coupons search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("coupons active count", 3, s.count(true));
        TestKit.checkEquals("coupons total count", 4, s.count(false));
        TestKit.checkEquals("coupons summary", "total=4 active=3 events=5", s.summary());
    }
}
