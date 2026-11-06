package com.shop;

import java.util.Arrays;

public class ReviewsStoreTest {
    public static void run() {
        ReviewsStore s = new ReviewsStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("reviews add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("reviews missing item throws", () -> new ReviewsStore().get(99), ReviewsStore.ReviewsException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("reviews search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("reviews active count", 3, s.count(true));
        TestKit.checkEquals("reviews total count", 4, s.count(false));
        TestKit.checkEquals("reviews summary", "total=4 active=3 events=5", s.summary());
    }
}
