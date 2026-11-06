package com.shop;

/** Tiny command line demo:  java com.shop.Main [sku] [qty] */
public final class Main {
    private Main() {
    }

    public static void main(String[] args) {
        String sku = args.length > 0 ? args[0] : "tea";
        int qty = args.length > 1 ? Integer.parseInt(args[1]) : 1;
        Orders.Order order = Orders.createOrder(sku, qty, 0);
        System.out.println("ordered " + order.qty() + " x " + order.sku() + " total " + order.total());
    }
}
