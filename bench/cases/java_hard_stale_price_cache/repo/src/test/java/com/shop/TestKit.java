package com.shop;

/** A very small test helper so the project needs no downloaded test library. */
public final class TestKit {
    private static int passed;
    private static int failed;

    private TestKit() {
    }

    public static void check(boolean condition, String name) {
        if (condition) {
            passed++;
        } else {
            failed++;
            System.out.println("FAIL " + name);
        }
    }

    public static void checkEquals(String name, Object expected, Object actual) {
        if (expected.equals(actual)) {
            passed++;
        } else {
            failed++;
            System.out.println("FAIL " + name + ": expected " + expected + " but was " + actual);
        }
    }

    public static void expectThrows(String name, Runnable action, Class<? extends Throwable> type) {
        try {
            action.run();
            failed++;
            System.out.println("FAIL " + name + ": expected " + type.getSimpleName() + " but nothing was thrown");
        } catch (Throwable t) {
            if (type.isInstance(t)) {
                passed++;
            } else {
                failed++;
                System.out.println("FAIL " + name + ": expected " + type.getSimpleName() + " but got " + t);
            }
        }
    }

    public static void failure(String name, Throwable t) {
        failed++;
        System.out.println("ERROR in " + name);
        t.printStackTrace(System.out);
    }

    public static void finish() {
        System.out.println(failed + " failed, " + passed + " passed");
        if (failed > 0) {
            System.exit(1);
        }
    }
}
