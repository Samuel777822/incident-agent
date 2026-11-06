package com.shop;

import java.util.Arrays;

public class ShippingRulesStoreTest {
    public static void run() {
        ShippingRulesStore s = new ShippingRulesStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("shippingrules add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("shippingrules missing item throws", () -> new ShippingRulesStore().get(99), ShippingRulesStore.ShippingRulesException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("shippingrules search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("shippingrules active count", 3, s.count(true));
        TestKit.checkEquals("shippingrules total count", 4, s.count(false));
        TestKit.checkEquals("shippingrules summary", "total=4 active=3 events=5", s.summary());
    }
}
