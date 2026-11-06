package com.shop;

import java.util.Arrays;
import java.util.Collections;

public class ReportsTest {
    public static void run() {
        TestKit.checkEquals("sales total", 15.0, Reports.salesTotal(Arrays.asList(10.5, 4.5)));
        TestKit.checkEquals("average order", 7.5, Reports.averageOrder(Arrays.asList(10.5, 4.5)));
        TestKit.checkEquals("average of nothing", 0.0, Reports.averageOrder(Collections.emptyList()));
    }
}
