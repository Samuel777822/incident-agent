package com.shop;

public class CartTest {
    public static void run() {
        Inventory.reset();
        Cart cart = new Cart();
        cart.add("mug", 99);
        cart.add("tea", 5);
        cart.add("coffee", 999);
        TestKit.checkEquals("two unavailable lines are removed", 2, cart.removeUnavailable());
        TestKit.checkEquals("one line is left", 1, cart.size());
    }
}
