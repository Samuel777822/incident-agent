package com.shop;

import java.util.Arrays;

public class InvoicesStoreTest {
    public static void run() {
        InvoicesStore s = new InvoicesStore();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("invoices add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("invoices missing item throws", () -> new InvoicesStore().get(99), InvoicesStore.InvoicesException.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("invoices search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("invoices active count", 3, s.count(true));
        TestKit.checkEquals("invoices total count", 4, s.count(false));
        TestKit.checkEquals("invoices summary", "total=4 active=3 events=5", s.summary());
    }
}
