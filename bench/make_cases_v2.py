"""Generate the extra benchmark cases: Java, JavaScript, TypeScript, a static HTML/CSS/JS site, and harder Python.

    python bench/make_cases_v2.py        # adds cases to bench/cases/ (does NOT delete the Python cases from make_cases.py)
    python bench/make_all_cases.py       # runs both generators and writes bench/ANSWER_KEY.md

Each project is a realistic ~500-1,400 line "vibe-coded" shop with a passing test suite (or, for the static site, a clean
site check). Every case is the SAME clean project with exactly ONE bug injected, so a fix can be verified by the project's
own tests. The incident text is captured by really running the broken code when the tool is installed (node, tsc, a JDK);
otherwise a realistic stand-in message is written. The answer key lists every planted bug, its file and its difficulty.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "cases"
sys.path.insert(0, str(HERE))
KEY: list[dict] = []          # rows for ANSWER_KEY.md


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace(f"__{k}__", v)
    return template


def run(argv, cwd: Path, timeout=120, env=None) -> str:
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"[could not run {argv[0]}: {exc}]"


def clean_paths(text: str, repo: Path) -> str:
    return text.replace(str(repo), "/app").replace(str(repo.resolve()), "/app")


def line_of(path: Path, snippet: str) -> int:
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if snippet in line:
            return i
    return 1


def apply_bug(repo: Path, bug: dict) -> None:
    target = repo / bug["file"]
    text = target.read_text(encoding="utf-8")
    if bug["old"] not in text:
        raise SystemExit(f"bug '{bug['name']}': text to replace not found in {bug['file']}")
    new = text.replace(bug["old"], bug["new"]) if bug.get("all") else text.replace(bug["old"], bug["new"], 1)
    target.write_text(new, encoding="utf-8")


def emit_case(name: str, lang: str, make_base, bug: dict, capture) -> None:
    """Write bench/cases/<name>/repo (clean project + one bug) and incident.json."""
    repo = ROOT / name / "repo"
    if (ROOT / name).exists():
        shutil.rmtree(ROOT / name)
    make_base(repo)
    apply_bug(repo, bug)
    captured = capture(repo, bug)
    traceback = clean_paths(captured or bug["fallback"], repo).strip() + "\n"
    write(ROOT / name / "incident.json", json.dumps({"message": bug["message"], "traceback": traceback}, indent=2))
    lines = sum(len(p.read_text(errors="replace").splitlines()) for p in repo.rglob("*") if p.is_file() and p.suffix in
                (".py", ".java", ".js", ".ts", ".html", ".css", ".json"))
    KEY.append({"case": name, "language": lang, "difficulty": bug["difficulty"], "file": bug["file"], "bug": bug["describe"],
                "fix": bug["fix"], "lines": lines, "captured": "yes" if captured else "no (stand-in text)"})
    print(f"{name}: {lines} lines ({lang}, {bug['difficulty']})")


# ================================================================================================================ JAVA
JAVA_STORE = '''package com.shop;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** __TITLE__ store for the shop. Plain map-backed so it is easy to test. */
public class __CLS__Store {
    public static class __CLS__Exception extends RuntimeException {
        public __CLS__Exception(String message) {
            super(message);
        }
    }

    private final Map<Integer, Map<String, Object>> items = new HashMap<>();
    private final List<String> audit = new ArrayList<>();
    private int nextId = 1;

    private void log(String action, int id) {
        audit.add(action + " " + id);
    }

    public int add(String name) {
        if (name == null || name.trim().isEmpty()) {
            throw new __CLS__Exception("name is required");
        }
        int id = nextId++;
        Map<String, Object> row = new HashMap<>();
        row.put("id", id);
        row.put("name", name.trim());
        row.put("active", Boolean.TRUE);
        items.put(id, row);
        log("add", id);
        return id;
    }

    public Map<String, Object> get(int id) {
        Map<String, Object> row = items.get(id);
        if (row == null) {
            throw new __CLS__Exception("__TITLE__ " + id + " not found");
        }
        return new HashMap<>(row);
    }

    public Map<String, Object> update(int id, String key, Object value) {
        Map<String, Object> row = items.get(id);
        if (row == null) {
            throw new __CLS__Exception("__TITLE__ " + id + " not found");
        }
        row.put(key, value);
        log("update", id);
        return new HashMap<>(row);
    }

    public void deactivate(int id) {
        update(id, "active", Boolean.FALSE);
    }

    public void delete(int id) {
        if (!items.containsKey(id)) {
            throw new __CLS__Exception("__TITLE__ " + id + " not found");
        }
        items.remove(id);
        log("delete", id);
    }

    public List<Map<String, Object>> list(boolean onlyActive) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map<String, Object> row : items.values()) {
            if (!onlyActive || Boolean.TRUE.equals(row.get("active"))) {
                rows.add(new HashMap<>(row));
            }
        }
        rows.sort(Comparator.comparingInt(r -> (Integer) r.get("id")));
        return rows;
    }

    public List<Map<String, Object>> search(String text) {
        String needle = text.trim().toLowerCase();
        List<Map<String, Object>> found = new ArrayList<>();
        for (Map<String, Object> row : list(true)) {
            if (((String) row.get("name")).toLowerCase().contains(needle)) {
                found.add(row);
            }
        }
        return found;
    }

    public int count(boolean onlyActive) {
        return list(onlyActive).size();
    }

    public List<String> names() {
        List<String> out = new ArrayList<>();
        for (Map<String, Object> row : list(true)) {
            out.add((String) row.get("name"));
        }
        return out;
    }

    public List<Integer> bulkAdd(List<String> names) {
        List<Integer> ids = new ArrayList<>();
        for (String n : names) {
            ids.add(add(n));
        }
        return ids;
    }

    public String summary() {
        return "total=" + count(false) + " active=" + count(true) + " events=" + audit.size();
    }

    public List<String> auditLog() {
        return new ArrayList<>(audit);
    }
}
'''

JAVA_STORE_TEST = '''package com.shop;

import java.util.Arrays;

public class __CLS__StoreTest {
    public static void run() {
        __CLS__Store s = new __CLS__Store();
        int id = s.add("  Alpha ");
        TestKit.checkEquals("__cls__ add trims the name", "Alpha", s.get(id).get("name"));
        TestKit.expectThrows("__cls__ missing item throws", () -> new __CLS__Store().get(99), __CLS__Store.__CLS__Exception.class);
        s.bulkAdd(Arrays.asList("red", "green", "redder"));
        TestKit.checkEquals("__cls__ search finds both reds", 2, s.search("red").size());
        s.deactivate(id);
        TestKit.checkEquals("__cls__ active count", 3, s.count(true));
        TestKit.checkEquals("__cls__ total count", 4, s.count(false));
        TestKit.checkEquals("__cls__ summary", "total=4 active=3 events=5", s.summary());
    }
}
'''

JAVA_FILES = {
    "src/main/java/com/shop/Pricing.java": '''package com.shop;

/** Pricing rules: discounts, tax and shipping. */
public final class Pricing {
    public static final double TAX_RATE = 0.18;

    private Pricing() {
    }

    public static double applyDiscount(double price, double pct) {
        if (pct < 0 || pct > 100) {
            throw new IllegalArgumentException("discount must be between 0 and 100");
        }
        return round2(price - price * pct / 100);
    }

    public static double addTax(double price) {
        return round2(price * (1 + TAX_RATE));
    }

    public static double shippingCost(double weightKg) {
        if (weightKg <= 0) {
            throw new IllegalArgumentException("weight must be positive");
        }
        if (weightKg <= 1) {
            return 40.0;
        }
        return 40.0 + 25.0 * (weightKg - 1);
    }

    public static double lineTotal(double unitPrice, int qty, double discountPct) {
        return round2(applyDiscount(unitPrice, discountPct) * qty);
    }

    static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
''',
    "src/main/java/com/shop/Inventory.java": '''package com.shop;

import java.util.HashMap;
import java.util.Map;

/** Stock levels per product. */
public final class Inventory {
    public static class InventoryException extends RuntimeException {
        public InventoryException(String message) {
            super(message);
        }
    }

    private static final Map<String, Integer> STOCK = new HashMap<>();

    static {
        reset();
    }

    private Inventory() {
    }

    public static void reset() {
        STOCK.clear();
        STOCK.put("tea", 40);
        STOCK.put("coffee", 25);
        STOCK.put("mug", 10);
    }

    public static int getStock(String sku) {
        Integer have = STOCK.get(sku);
        if (have == null) {
            throw new InventoryException("unknown sku: " + sku);
        }
        return have;
    }

    public static void reserve(String sku, int qty) {
        if (getStock(sku) < qty) {
            throw new InventoryException("out of stock: " + sku);
        }
        STOCK.put(sku, getStock(sku) - qty);
    }

    public static void restock(String sku, int qty) {
        STOCK.put(sku, STOCK.getOrDefault(sku, 0) + qty);
    }
}
''',
    "src/main/java/com/shop/PriceCache.java": '''package com.shop;

import java.util.HashMap;
import java.util.Map;

/** Remembers unit prices so the catalogue is not searched on every order. */
public final class PriceCache {
    private static final Map<String, Double> BASE = new HashMap<>();
    private static final Map<String, Double> CACHE = new HashMap<>();

    static {
        reset();
    }

    private PriceCache() {
    }

    public static void reset() {
        BASE.clear();
        CACHE.clear();
        BASE.put("tea", 120.0);
        BASE.put("coffee", 250.0);
        BASE.put("mug", 399.0);
    }

    public static double priceOf(String sku) {
        Double cached = CACHE.get(sku);
        if (cached == null) {
            cached = BASE.get(sku);
            if (cached == null) {
                throw new IllegalArgumentException("no price for " + sku);
            }
            CACHE.put(sku, cached);
        }
        return cached;
    }

    public static void setPrice(String sku, double price) {
        BASE.put(sku, price);
        CACHE.remove(sku);
    }
}
''',
    "src/main/java/com/shop/Orders.java": '''package com.shop;

/** Order creation: checks stock, prices the line, reserves the items. */
public final class Orders {
    public record Order(String sku, int qty, double total, double totalWithTax) {
    }

    private Orders() {
    }

    public static Order createOrder(String sku, int qty, double discountPct) {
        if (Inventory.getStock(sku) < qty) {
            throw new Inventory.InventoryException("out of stock: " + sku);
        }
        double total = Pricing.lineTotal(PriceCache.priceOf(sku), qty, discountPct);
        Inventory.reserve(sku, qty);
        return new Order(sku, qty, total, Pricing.addTax(total));
    }
}
''',
    "src/main/java/com/shop/Cart.java": '''package com.shop;

import java.util.ArrayList;
import java.util.List;

/** A shopping cart that can drop lines the warehouse can no longer supply. */
public final class Cart {
    public record Line(String sku, int qty) {
    }

    private final List<Line> lines = new ArrayList<>();

    public void add(String sku, int qty) {
        lines.add(new Line(sku, qty));
    }

    public int size() {
        return lines.size();
    }

    public int removeUnavailable() {
        int before = lines.size();
        lines.removeIf(line -> Inventory.getStock(line.sku()) < line.qty());
        return before - lines.size();
    }
}
''',
    "src/main/java/com/shop/Reports.java": '''package com.shop;

import java.util.List;

/** Simple sales reports. */
public final class Reports {
    private Reports() {
    }

    public static double salesTotal(List<Double> orders) {
        double total = 0.0;
        for (double amount : orders) {
            total += amount;
        }
        return Math.round(total * 100.0) / 100.0;
    }

    public static double averageOrder(List<Double> orders) {
        return orders.isEmpty() ? 0.0 : Math.round(salesTotal(orders) / orders.size() * 100.0) / 100.0;
    }
}
''',
    "src/main/java/com/shop/Main.java": '''package com.shop;

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
''',
    "src/test/java/com/shop/TestKit.java": '''package com.shop;

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
''',
    "src/test/java/com/shop/PricingTest.java": '''package com.shop;

public class PricingTest {
    public static void run() {
        TestKit.checkEquals("ten percent off 200", 180.0, Pricing.applyDiscount(200, 10));
        TestKit.checkEquals("line total with discount", 270.0, Pricing.lineTotal(100, 3, 10));
        TestKit.checkEquals("tax is 18 percent", 118.0, Pricing.addTax(100));
        TestKit.checkEquals("shipping for two kilos", 65.0, Pricing.shippingCost(2));
        TestKit.expectThrows("bad discount", () -> Pricing.applyDiscount(10, 120), IllegalArgumentException.class);
    }
}
''',
    "src/test/java/com/shop/InventoryTest.java": '''package com.shop;

public class InventoryTest {
    public static void run() {
        Inventory.reset();
        TestKit.checkEquals("tea stock", 40, Inventory.getStock("tea"));
        TestKit.expectThrows("unknown sku", () -> Inventory.getStock("juice"), Inventory.InventoryException.class);
        Inventory.reserve("mug", 4);
        TestKit.checkEquals("reserve lowers stock", 6, Inventory.getStock("mug"));
        TestKit.expectThrows("cannot over-reserve", () -> Inventory.reserve("mug", 50), Inventory.InventoryException.class);
        Inventory.restock("mug", 4);
        TestKit.checkEquals("restock raises stock", 10, Inventory.getStock("mug"));
    }
}
''',
    "src/test/java/com/shop/OrdersTest.java": '''package com.shop;

public class OrdersTest {
    public static void run() {
        Inventory.reset();
        PriceCache.reset();
        Orders.Order order = Orders.createOrder("tea", 2, 10);
        TestKit.checkEquals("order total with discount", 216.0, order.total());
        TestKit.checkEquals("order total with tax", 254.88, order.totalWithTax());
        TestKit.expectThrows("unknown sku in an order", () -> Orders.createOrder("juice", 1, 0), Inventory.InventoryException.class);
        PriceCache.reset();
        Orders.createOrder("coffee", 1, 0);
        PriceCache.setPrice("coffee", 300.0);
        TestKit.checkEquals("a changed price is used by the next order", 300.0, Orders.createOrder("coffee", 1, 0).total());
    }
}
''',
    "src/test/java/com/shop/CartTest.java": '''package com.shop;

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
''',
    "src/test/java/com/shop/ReportsTest.java": '''package com.shop;

import java.util.Arrays;
import java.util.Collections;

public class ReportsTest {
    public static void run() {
        TestKit.checkEquals("sales total", 15.0, Reports.salesTotal(Arrays.asList(10.5, 4.5)));
        TestKit.checkEquals("average order", 7.5, Reports.averageOrder(Arrays.asList(10.5, 4.5)));
        TestKit.checkEquals("average of nothing", 0.0, Reports.averageOrder(Collections.emptyList()));
    }
}
''',
}
JAVA_BULK = [("Users", "User"), ("Products", "Product"), ("ShippingRules", "Shipping rule"), ("Reviews", "Review"),
             ("Coupons", "Coupon"), ("Suppliers", "Supplier"), ("Categories", "Category"), ("Wishlists", "Wishlist"),
             ("Returns", "Return"), ("Invoices", "Invoice"), ("Notifications", "Notification"), ("Audits", "Audit")]


def java_base(repo: Path) -> None:
    for rel, text in JAVA_FILES.items():
        write(repo / rel, text)
    names = []
    for cls, title in JAVA_BULK:
        write(repo / f"src/main/java/com/shop/{cls}Store.java", fill(JAVA_STORE, CLS=cls, TITLE=title))
        write(repo / f"src/test/java/com/shop/{cls}StoreTest.java", fill(JAVA_STORE_TEST, CLS=cls, cls=cls.lower()))
        names.append(f"{cls}StoreTest")
    tests = ["PricingTest", "InventoryTest", "OrdersTest", "CartTest", "ReportsTest"] + names
    body = "\n".join(f'        runOne("{t}", {t}::run);' for t in tests)
    write(repo / "src/test/java/com/shop/AllTests.java", f'''package com.shop;

/** Runs every test class and exits with a non-zero status when anything failed. */
public class AllTests {{
    private static void runOne(String name, Runnable test) {{
        try {{
            test.run();
        }} catch (Throwable t) {{
            TestKit.failure(name, t);
        }}
    }}

    public static void main(String[] args) {{
{body}
        TestKit.finish();
    }}
}}
''')
    write(repo / "README.md", "# Shop (Java)\n\nPlain javac project. Build and test: see the sandbox profile (javac, then `java -cp out com.shop.AllTests`).\n")


def javac_argv() -> list[str] | None:
    if shutil.which("javac"):
        return ["javac"]
    if shutil.which("java"):
        probe = subprocess.run(["java", "--list-modules"], capture_output=True, text=True)
        if "jdk.compiler" in probe.stdout:
            return ["java", "-m", "jdk.compiler/com.sun.tools.javac.Main"]
    return None


def java_compile(repo: Path) -> tuple[bool, str]:
    jc = javac_argv()
    if not jc:
        return False, ""
    (repo / ".fx_out").mkdir(exist_ok=True)
    srcs = sorted(str(p.relative_to(repo)) for p in repo.rglob("*.java"))
    out = run(jc + ["-encoding", "UTF-8", "-Xlint:none", "-d", ".fx_out"] + srcs, repo)
    return (not out.strip() or "error" not in out), out


def java_capture(repo: Path, bug: dict) -> str:
    ok, out = java_compile(repo)
    if not javac_argv():
        return ""
    try:
        if not ok:
            return out
        if bug["run"] == "tests":
            return run(["java", "-cp", ".fx_out", "com.shop.AllTests"], repo)
        return run(["java", "-cp", ".fx_out", "com.shop.Main"] + bug["run"].split(), repo)
    finally:
        shutil.rmtree(repo / ".fx_out", ignore_errors=True)


JAVA_BUGS = [
    dict(name="java_easy_typo_variable", difficulty="easy", file="src/main/java/com/shop/Reports.java",
         old="return Math.round(total * 100.0) / 100.0;\n    }\n\n    public static double averageOrder",
         new="return Math.round(totl * 100.0) / 100.0;\n    }\n\n    public static double averageOrder", run="tests",
         message="The nightly build is red: the sales report class no longer compiles.",
         describe="variable `total` misspelled as `totl` in salesTotal (compile error)", fix="rename totl -> total",
         fallback="src/main/java/com/shop/Reports.java:14: error: cannot find symbol\n        return Math.round(totl * 100.0) / 100.0;\n"
                  "                          ^\n  symbol:   variable totl\n  location: class Reports\n1 error"),
    dict(name="java_medium_logic_discount", difficulty="medium", file="src/main/java/com/shop/Pricing.java",
         old="price * pct / 100)", new="price * pct / 10)", run="tests",
         message="Customers who use a 10% discount code get the item for free: a 200 item shows 0 instead of 180 (reported by support).",
         describe="discount divided by 10 instead of 100 in applyDiscount", fix="price * pct / 100",
         fallback="FAIL ten percent off 200: expected 180.0 but was 0.0\nFAIL line total with discount: expected 270.0 but was 0.0\n"
                  "FAIL order total with discount: expected 216.0 but was 0.0\n4 failed, 87 passed"),
    dict(name="java_medium_npe_unknown_sku", difficulty="medium", file="src/main/java/com/shop/Inventory.java",
         old='        Integer have = STOCK.get(sku);\n        if (have == null) {\n            throw new InventoryException("unknown sku: " + sku);\n        }\n        return have;',
         new="        return STOCK.get(sku);", run="juice 1",
         message="Ordering a product we do not stock crashes the checkout with a NullPointerException.",
         describe="getStock unboxes a null Integer for unknown SKUs instead of throwing InventoryException", fix="restore the null check and InventoryException",
         fallback='Exception in thread "main" java.lang.NullPointerException: Cannot invoke "java.lang.Integer.intValue()" because the return value of '
                  '"java.util.Map.get(Object)" is null\n\tat com.shop.Inventory.getStock(Inventory.java:29)\n\tat com.shop.Orders.createOrder(Orders.java:11)\n\tat com.shop.Main.main(Main.java:11)'),
    dict(name="java_medium_cross_file_rename", difficulty="medium", file="src/main/java/com/shop/Inventory.java",
         old="getStock", new="stockFor", all=True, run="tests",
         message="After yesterday's refactor of the inventory class the build fails.",
         describe="Inventory.getStock renamed to stockFor, but Orders and Cart still call getStock (compile error in OTHER files)", fix="revert the rename in Inventory.java",
         fallback="src/main/java/com/shop/Orders.java:11: error: cannot find symbol\n        if (Inventory.getStock(sku) < qty) {\n                     ^\n"
                  "  symbol:   method getStock(String)\n  location: class Inventory\nsrc/main/java/com/shop/Cart.java:24: error: cannot find symbol\n2 errors"),
    dict(name="java_hard_concurrent_modification", difficulty="hard", file="src/main/java/com/shop/Cart.java",
         old="lines.removeIf(line -> Inventory.getStock(line.sku()) < line.qty());",
         new="for (Line line : lines) {\n            if (Inventory.getStock(line.sku()) < line.qty()) {\n                lines.remove(line);\n            }\n        }", run="tests",
         message="Checkout sometimes crashes when the cart contains sold-out items; it works when only one item is sold out.",
         describe="removing from a list inside a for-each loop (ConcurrentModificationException)", fix="use removeIf or an iterator",
         fallback="ERROR in CartTest\njava.util.ConcurrentModificationException\n\tat java.base/java.util.ArrayList$Itr.checkForComodification(ArrayList.java:1096)\n"
                  "\tat java.base/java.util.ArrayList$Itr.next(ArrayList.java:1050)\n\tat com.shop.Cart.removeUnavailable(Cart.java:24)\n\tat com.shop.CartTest.run(CartTest.java:12)"),
    dict(name="java_hard_stale_price_cache", difficulty="hard", file="src/main/java/com/shop/PriceCache.java",
         old="        BASE.put(sku, price);\n        CACHE.remove(sku);", new="        BASE.put(sku, price);", run="tests",
         message="After the admin changes a price, new orders keep using the OLD price until the server is restarted (stale cache).",
         describe="setPrice forgets to invalidate the cached price", fix="CACHE.remove(sku) after updating BASE",
         fallback="FAIL a changed price is used by the next order: expected 300.0 but was 250.0\n1 failed, 40 passed"),
]


def build_java_cases() -> None:
    for bug in JAVA_BUGS:
        emit_case(bug["name"], "Java", java_base, bug, lambda repo, b: java_capture(repo, b))


# ====================================================================================================== JAVASCRIPT (ESM)
JS_STORE = '''// __TITLE__ store for the shop. Plain Map-backed so it is easy to test.
export class __CLS__Error extends Error {}

export class __CLS__Store {
  #items = new Map();
  #nextId = 1;
  audit = [];

  #log(action, id) {
    this.audit.push(`${action} ${id}`);
  }

  add(name) {
    if (!name || !String(name).trim()) {
      throw new __CLS__Error('name is required');
    }
    const id = this.#nextId++;
    this.#items.set(id, { id, name: String(name).trim(), active: true });
    this.#log('add', id);
    return id;
  }

  get(id) {
    const row = this.#items.get(id);
    if (!row) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    return { ...row };
  }

  update(id, fields) {
    const row = this.#items.get(id);
    if (!row) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    Object.assign(row, fields);
    this.#log('update', id);
    return { ...row };
  }

  deactivate(id) {
    return this.update(id, { active: false });
  }

  delete(id) {
    if (!this.#items.has(id)) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    this.#items.delete(id);
    this.#log('delete', id);
  }

  list(onlyActive = true) {
    return [...this.#items.values()]
      .filter((row) => row.active || !onlyActive)
      .map((row) => ({ ...row }))
      .sort((a, b) => a.id - b.id);
  }

  search(text) {
    const needle = String(text).trim().toLowerCase();
    return this.list().filter((row) => row.name.toLowerCase().includes(needle));
  }

  count(onlyActive = true) {
    return this.list(onlyActive).length;
  }

  names() {
    return this.list().map((row) => row.name);
  }

  bulkAdd(names) {
    return names.map((n) => this.add(n));
  }

  summary() {
    return { total: this.count(false), active: this.count(true), auditEvents: this.audit.length };
  }
}
'''

JS_STORE_TEST = '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { __CLS__Error, __CLS__Store } from '../src/__file__.js';

test('__file__: add trims the name', () => {
  const s = new __CLS__Store();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('__file__: a missing item throws', () => {
  assert.throws(() => new __CLS__Store().get(99), __CLS__Error);
});

test('__file__: search and counts', () => {
  const s = new __CLS__Store();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
'''

JS_BULK = [("users", "User"), ("products", "Product"), ("shippingRules", "ShippingRule"), ("reviews", "Review"),
           ("coupons", "Coupon"), ("suppliers", "Supplier"), ("categories", "Category"), ("wishlists", "Wishlist"),
           ("returns", "Return"), ("invoices", "Invoice")]

JS_CORE = {
    "src/pricing.js": '''// Pricing rules: discounts, tax and shipping.
export const TAX_RATE = 0.18;

export function round2(value) {
  return Math.round(value * 100) / 100;
}

export function applyDiscount(price, pct) {
  if (pct < 0 || pct > 100) {
    throw new RangeError('discount must be between 0 and 100');
  }
  return round2(price - (price * pct) / 100);
}

export function addTax(price) {
  return round2(price * (1 + TAX_RATE));
}

export function shippingCost(weightKg) {
  if (weightKg <= 0) {
    throw new RangeError('weight must be positive');
  }
  return weightKg <= 1 ? 40 : 40 + 25 * (weightKg - 1);
}

export function lineTotal(unitPrice, qty, discountPct = 0) {
  return round2(applyDiscount(unitPrice, discountPct) * qty);
}
''',
    "src/inventory.js": '''// Stock levels per product.
export class OutOfStock extends Error {}

const STOCK = new Map();

export function resetStock() {
  STOCK.clear();
  STOCK.set('tea', 40);
  STOCK.set('coffee', 25);
  STOCK.set('mug', 10);
}
resetStock();

export function getStock(sku) {
  if (!STOCK.has(sku)) {
    throw new OutOfStock(`unknown sku: ${sku}`);
  }
  return STOCK.get(sku);
}

export function reserve(sku, qty) {
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  STOCK.set(sku, getStock(sku) - qty);
}

export function restock(sku, qty) {
  STOCK.set(sku, (STOCK.get(sku) ?? 0) + qty);
}
''',
    "src/catalog.js": '''// The product catalogue.
export const CATALOG = [
  { sku: 'tea', price: 120 },
  { sku: 'coffee', price: 250 },
  { sku: 'mug', price: 399 },
];
''',
    "src/orders.js": '''// Order creation: checks stock, prices the line, reserves the items.
import { CATALOG } from './catalog.js';
import { getStock, OutOfStock, reserve } from './inventory.js';
import { addTax, lineTotal } from './pricing.js';

export class OrderError extends Error {}

export function createOrder(sku, qty, discountPct = 0) {
  const entry = CATALOG.find((p) => p.sku === sku);
  if (!entry) {
    throw new OrderError(`unknown product: ${sku}`);
  }
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  const total = lineTotal(entry.price, qty, discountPct);
  reserve(sku, qty);
  return { sku, qty, total, totalWithTax: addTax(total) };
}
''',
    "src/reports.js": '''// Simple sales reports.
export function salesTotal(orders) {
  let total = 0;
  for (const order of orders) {
    total += order.total;
  }
  return Math.round(total * 100) / 100;
}

export function averageOrder(orders) {
  return orders.length ? Math.round((salesTotal(orders) / orders.length) * 100) / 100 : 0;
}
''',
    "src/server.js": '''// A tiny HTTP server so the sandbox can check that the app starts.
import http from 'node:http';
import { createOrder } from './orders.js';

const port = Number(process.env.PORT || 3000);

const server = http.createServer((req, res) => {
  if (req.url === '/') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, shop: 'tea-and-mugs' }));
    return;
  }
  if (req.url.startsWith('/order/')) {
    try {
      const order = createOrder(req.url.split('/')[2], 1);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(order));
    } catch (err) {
      res.writeHead(400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }
  res.writeHead(404);
  res.end();
});

server.listen(port, '0.0.0.0', () => console.log(`listening on ${port}`));
''',
    "test/pricing.test.js": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addTax, applyDiscount, lineTotal, shippingCost } from '../src/pricing.js';

test('ten percent off 200 is 180', () => {
  assert.equal(applyDiscount(200, 10), 180);
});

test('a line with a discount', () => {
  assert.equal(lineTotal(100, 3, 10), 270);
});

test('tax is 18 percent', () => {
  assert.equal(addTax(100), 118);
});

test('shipping for two kilos', () => {
  assert.equal(shippingCost(2), 65);
});

test('a discount over 100 is rejected', () => {
  assert.throws(() => applyDiscount(10, 120), RangeError);
});
''',
    "test/inventory.test.js": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getStock, OutOfStock, reserve, resetStock, restock } from '../src/inventory.js';

test('tea stock', () => {
  resetStock();
  assert.equal(getStock('tea'), 40);
});

test('an unknown sku throws OutOfStock', () => {
  assert.throws(() => getStock('juice'), OutOfStock);
});

test('reserve and restock', () => {
  resetStock();
  reserve('mug', 4);
  assert.equal(getStock('mug'), 6);
  assert.throws(() => reserve('mug', 50), OutOfStock);
  restock('mug', 4);
  assert.equal(getStock('mug'), 10);
});
''',
    "test/orders.test.js": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resetStock } from '../src/inventory.js';
import { createOrder, OrderError } from '../src/orders.js';

test('an order is priced with the discount', () => {
  resetStock();
  const order = createOrder('tea', 2, 10);
  assert.equal(order.total, 216);
  assert.equal(order.totalWithTax, 254.88);
});

test('an unknown product is an OrderError', () => {
  resetStock();
  assert.throws(() => createOrder('juice', 1), OrderError);
});

test('ordering more than we have is refused', () => {
  resetStock();
  assert.throws(() => createOrder('mug', 99), /out of stock/);
});
''',
    "test/reports.test.js": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { averageOrder, salesTotal } from '../src/reports.js';

test('sales total', () => {
  assert.equal(salesTotal([{ total: 10.5 }, { total: 4.5 }]), 15);
});

test('average order', () => {
  assert.equal(averageOrder([{ total: 10.5 }, { total: 4.5 }]), 7.5);
  assert.equal(averageOrder([]), 0);
});
''',
}


def js_base(repo: Path) -> None:
    for rel, text in JS_CORE.items():
        write(repo / rel, text)
    for file, cls in JS_BULK:
        write(repo / f"src/{file}.js", fill(JS_STORE, CLS=cls[0].upper() + cls[1:], TITLE=cls))
        write(repo / f"test/{file}.test.js", fill(JS_STORE_TEST, CLS=cls[0].upper() + cls[1:], file=file))
    write(repo / "package.json", json.dumps({"name": "shop-js", "version": "1.0.0", "type": "module",
                                             "scripts": {"test": "node --test", "start": "node src/server.js"}}, indent=2) + "\n")
    write(repo / "README.md", "# Shop (JavaScript)\n\n`npm test` runs the node:test suite. `npm start` starts a tiny server.\n")


def node_capture(repo: Path, bug: dict) -> str:
    if not shutil.which("node"):
        return ""
    if bug["run"] == "tests":
        return run(["node", "--test"], repo)
    return run(["node", "--input-type=module", "-e", bug["run"]], repo)


JS_BUGS = [
    dict(name="js_easy_reference_error", difficulty="easy", file="src/reports.js",
         old="return Math.round(total * 100) / 100;\n}\n\nexport function averageOrder", new="return Math.round(totl * 100) / 100;\n}\n\nexport function averageOrder",
         run="import('./src/reports.js').then(m => m.salesTotal([{total: 5}]))",
         message="ReferenceError: totl is not defined (the sales dashboard shows a blank page).",
         describe="variable `total` misspelled `totl` in salesTotal", fix="rename totl -> total",
         fallback="ReferenceError: totl is not defined\n    at salesTotal (/app/src/reports.js:7:22)\n    at file:///app/[eval1]:1:48"),
    dict(name="js_medium_logic_discount", difficulty="medium", file="src/pricing.js",
         old="(price * pct) / 100)", new="(price * pct) / 10)", run="tests",
         message="Customers who use a 10% discount code get the item for free: a 200 item shows 0 instead of 180 (reported by support).",
         describe="discount divided by 10 instead of 100", fix="(price * pct) / 100",
         fallback="not ok 1 - ten percent off 200 is 180\n  expected: 180\n  actual: 0\n# fail 3"),
    dict(name="js_medium_export_rename", difficulty="medium", file="src/inventory.js",
         old="getStock", new="stockFor", all=True, run="import('./src/orders.js')",
         message="The app crashes on start-up since yesterday's inventory refactor.",
         describe="getStock renamed to stockFor in inventory.js while orders.js still imports getStock (error shows in ANOTHER file)", fix="revert the rename in inventory.js",
         fallback="SyntaxError: The requested module './inventory.js' does not provide an export named 'getStock'\n    at ModuleJob._instantiate (node:internal/modules/esm/module_job:180:21)"),
    dict(name="js_hard_missing_await", difficulty="hard", file="src/inventory.js",
         old="export function getStock(sku) {", new="export async function getStock(sku) {", run="tests",
         message="We oversold mugs: orders for more than we have are accepted without an error.",
         describe="getStock became async (returns a Promise) but callers compare it as a number, so the stock check silently never fires", fix="make getStock synchronous again (or await it everywhere)",
         fallback="not ok 8 - ordering more than we have is refused\n  error: Missing expected rejection (/out of stock/)\n# fail 3"),
    dict(name="js_medium_typeerror_unknown", difficulty="medium", file="src/orders.js",
         old="  if (!entry) {\n    throw new OrderError(`unknown product: ${sku}`);\n  }\n", new="", run="import('./src/orders.js').then(m => m.createOrder('juice', 1))",
         message="TypeError: Cannot read properties of undefined (reading 'price') when someone orders a product that does not exist.",
         describe="the guard for an unknown product was deleted", fix="restore the `if (!entry) throw new OrderError(...)` guard",
         fallback="TypeError: Cannot read properties of undefined (reading 'price')\n    at createOrder (/app/src/orders.js:14:31)"),
]


def build_js_cases() -> None:
    for bug in JS_BUGS:
        emit_case(bug["name"], "JavaScript", js_base, bug, node_capture)


# ============================================================================================================= TYPESCRIPT
TS_STORE = '''// __TITLE__ store for the shop. Plain Map-backed so it is easy to test.
export class __CLS__Error extends Error {}

export interface __CLS__Row {
  id: number;
  name: string;
  active: boolean;
}

export class __CLS__Store {
  private items = new Map<number, __CLS__Row>();
  private nextId = 1;
  public audit: string[] = [];

  private log(action: string, id: number): void {
    this.audit.push(`${action} ${id}`);
  }

  add(name: string): number {
    if (!name || !name.trim()) {
      throw new __CLS__Error('name is required');
    }
    const id = this.nextId++;
    this.items.set(id, { id, name: name.trim(), active: true });
    this.log('add', id);
    return id;
  }

  get(id: number): __CLS__Row {
    const row = this.items.get(id);
    if (!row) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    return { ...row };
  }

  update(id: number, fields: Partial<__CLS__Row>): __CLS__Row {
    const row = this.items.get(id);
    if (!row) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    Object.assign(row, fields);
    this.log('update', id);
    return { ...row };
  }

  deactivate(id: number): __CLS__Row {
    return this.update(id, { active: false });
  }

  delete(id: number): void {
    if (!this.items.has(id)) {
      throw new __CLS__Error(`__TITLE__ ${id} not found`);
    }
    this.items.delete(id);
    this.log('delete', id);
  }

  list(onlyActive = true): __CLS__Row[] {
    return [...this.items.values()]
      .filter((row) => row.active || !onlyActive)
      .map((row) => ({ ...row }))
      .sort((a, b) => a.id - b.id);
  }

  search(text: string): __CLS__Row[] {
    const needle = text.trim().toLowerCase();
    return this.list().filter((row) => row.name.toLowerCase().includes(needle));
  }

  count(onlyActive = true): number {
    return this.list(onlyActive).length;
  }

  names(): string[] {
    return this.list().map((row) => row.name);
  }

  bulkAdd(names: string[]): number[] {
    return names.map((n) => this.add(n));
  }

  summary(): { total: number; active: number; auditEvents: number } {
    return { total: this.count(false), active: this.count(true), auditEvents: this.audit.length };
  }
}
'''

TS_STORE_TEST = '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { __CLS__Error, __CLS__Store } from '../src/__file__.ts';

test('__file__: add trims the name', () => {
  const s = new __CLS__Store();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('__file__: a missing item throws', () => {
  assert.throws(() => new __CLS__Store().get(99), __CLS__Error);
});

test('__file__: search and counts', () => {
  const s = new __CLS__Store();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
'''

TS_CORE = {
    "src/pricing.ts": '''// Pricing rules: discounts, tax and shipping.
export const TAX_RATE = 0.18;

export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function applyDiscount(price: number, pct: number): number {
  if (pct < 0 || pct > 100) {
    throw new RangeError('discount must be between 0 and 100');
  }
  return round2(price - (price * pct) / 100);
}

export function addTax(price: number): number {
  return round2(price * (1 + TAX_RATE));
}

export function shippingCost(weightKg: number): number {
  if (weightKg <= 0) {
    throw new RangeError('weight must be positive');
  }
  return weightKg <= 1 ? 40 : 40 + 25 * (weightKg - 1);
}

export function lineTotal(unitPrice: number, qty: number, discountPct = 0): number {
  return round2(applyDiscount(unitPrice, discountPct) * qty);
}
''',
    "src/inventory.ts": '''// Stock levels per product.
export class OutOfStock extends Error {}

const STOCK = new Map<string, number>();

export function resetStock(): void {
  STOCK.clear();
  STOCK.set('tea', 40);
  STOCK.set('coffee', 25);
  STOCK.set('mug', 10);
}
resetStock();

export function getStock(sku: string): number {
  const have = STOCK.get(sku);
  if (have === undefined) {
    throw new OutOfStock(`unknown sku: ${sku}`);
  }
  return have;
}

export function reserve(sku: string, qty: number): void {
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  STOCK.set(sku, getStock(sku) - qty);
}

export function restock(sku: string, qty: number): void {
  STOCK.set(sku, (STOCK.get(sku) ?? 0) + qty);
}
''',
    "src/catalog.ts": '''// The product catalogue.
export interface Product {
  sku: string;
  price: number;
}

export const CATALOG: Product[] = [
  { sku: 'tea', price: 120 },
  { sku: 'coffee', price: 250 },
  { sku: 'mug', price: 399 },
];
''',
    "src/orders.ts": '''// Order creation: checks stock, prices the line, reserves the items.
import { CATALOG } from './catalog.ts';
import { getStock, OutOfStock, reserve } from './inventory.ts';
import { addTax, lineTotal } from './pricing.ts';

export class OrderError extends Error {}

export interface Order {
  sku: string;
  qty: number;
  total: number;
  totalWithTax: number;
}

export function createOrder(sku: string, qty: number, discountPct = 0): Order {
  const entry = CATALOG.find((p) => p.sku === sku);
  if (!entry) {
    throw new OrderError(`unknown product: ${sku}`);
  }
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  const total = lineTotal(entry.price, qty, discountPct);
  reserve(sku, qty);
  return { sku, qty, total, totalWithTax: addTax(total) };
}
''',
    "src/reports.ts": '''// Simple sales reports.
import type { Order } from './orders.ts';

export function salesTotal(orders: Pick<Order, 'total'>[]): number {
  let total = 0;
  for (const order of orders) {
    total += order.total;
  }
  return Math.round(total * 100) / 100;
}

export function averageOrder(orders: Pick<Order, 'total'>[]): number {
  return orders.length ? Math.round((salesTotal(orders) / orders.length) * 100) / 100 : 0;
}
''',
    "test/pricing.test.ts": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addTax, applyDiscount, lineTotal, shippingCost } from '../src/pricing.ts';

test('ten percent off 200 is 180', () => {
  assert.equal(applyDiscount(200, 10), 180);
});

test('a line with a discount', () => {
  assert.equal(lineTotal(100, 3, 10), 270);
});

test('tax is 18 percent', () => {
  assert.equal(addTax(100), 118);
});

test('shipping for two kilos', () => {
  assert.equal(shippingCost(2), 65);
});

test('a discount over 100 is rejected', () => {
  assert.throws(() => applyDiscount(10, 120), RangeError);
});
''',
    "test/orders.test.ts": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resetStock } from '../src/inventory.ts';
import { createOrder, OrderError } from '../src/orders.ts';

test('an order is priced with the discount', () => {
  resetStock();
  const order = createOrder('tea', 2, 10);
  assert.equal(order.total, 216);
  assert.equal(order.totalWithTax, 254.88);
});

test('an unknown product is an OrderError', () => {
  resetStock();
  assert.throws(() => createOrder('juice', 1), OrderError);
});

test('ordering more than we have is refused', () => {
  resetStock();
  assert.throws(() => createOrder('mug', 99), /out of stock/);
});
''',
    "test/reports.test.ts": '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { averageOrder, salesTotal } from '../src/reports.ts';

test('sales total', () => {
  assert.equal(salesTotal([{ total: 10.5 }, { total: 4.5 }]), 15);
});

test('average order', () => {
  assert.equal(averageOrder([{ total: 10.5 }, { total: 4.5 }]), 7.5);
  assert.equal(averageOrder([]), 0);
});
''',
}


def ts_base(repo: Path) -> None:
    for rel, text in TS_CORE.items():
        write(repo / rel, text)
    for file, cls in JS_BULK[:8]:
        name = cls[0].upper() + cls[1:]
        write(repo / f"src/{file}.ts", fill(TS_STORE, CLS=name, TITLE=cls))
        write(repo / f"test/{file}.test.ts", fill(TS_STORE_TEST, CLS=name, file=file))
    write(repo / "package.json", json.dumps({
        "name": "shop-ts", "version": "1.0.0", "type": "module",
        "scripts": {"build": "tsc --noEmit", "test": "node --experimental-strip-types --disable-warning=ExperimentalWarning --test test/*.test.ts"},
        "devDependencies": {"typescript": "^5.6.0"}}, indent=2) + "\n")
    write(repo / "tsconfig.json", json.dumps({"compilerOptions": {
        "target": "es2022", "module": "nodenext", "moduleResolution": "nodenext", "strict": True, "noEmit": True,
        "allowImportingTsExtensions": True, "skipLibCheck": True, "lib": ["es2022"], "types": []}, "include": ["src"]}, indent=2) + "\n")
    write(repo / "README.md", "# Shop (TypeScript)\n\n`npm run build` type-checks, `npm test` runs the node:test suite on the .ts files.\n")


def ts_capture(repo: Path, bug: dict) -> str:
    if not shutil.which("node"):
        return ""
    if bug["run"] == "tsc":
        if not shutil.which("tsc"):
            return ""
        return run(["tsc", "--noEmit", "-p", "."], repo)
    return run(["node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", "--test"] +
               sorted(str(p.relative_to(repo)) for p in (repo / "test").glob("*.test.ts")), repo)


TS_BUGS = [
    dict(name="ts_easy_wrong_argument_type", difficulty="easy", file="src/orders.ts",
         old="lineTotal(entry.price, qty, discountPct)", new="lineTotal(entry.price, String(qty), discountPct)", run="tsc",
         message="CI is failing on the type-check step after the latest commit.",
         describe="qty converted to a string before being passed to lineTotal (TS2345)", fix="pass qty as a number",
         fallback="src/orders.ts(25,43): error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'."),
    dict(name="ts_medium_property_rename", difficulty="medium", file="src/catalog.ts",
         old="  price: number;", new="  cost: number;", all=False, run="tsc",
         message="The type-check fails in the orders file, but nobody touched it.",
         describe="Product.price renamed to cost in catalog.ts; orders.ts still reads entry.price and the catalog still uses price (errors show in OTHER places)", fix="revert the rename in catalog.ts",
         fallback="src/catalog.ts(10,29): error TS2353: Object literal may only specify known properties, and 'price' does not exist in type 'Product'.\n"
                  "src/orders.ts(25,50): error TS2339: Property 'price' does not exist on type 'Product'."),
    dict(name="ts_medium_logic_discount", difficulty="medium", file="src/pricing.ts",
         old="(price * pct) / 100)", new="(price * pct) / 10)", run="tests",
         message="Customers who use a 10% discount code get the item for free: a 200 item shows 0 instead of 180 (reported by support).",
         describe="discount divided by 10 instead of 100 (compiles fine, only the tests catch it)", fix="(price * pct) / 100",
         fallback="not ok 1 - ten percent off 200 is 180\n  expected: 180\n  actual: 0\n# fail 3"),
    dict(name="ts_hard_promise_in_comparison", difficulty="hard", file="src/inventory.ts",
         old="export function getStock(sku: string): number {", new="export async function getStock(sku: string): Promise<number> {", run="tsc",
         message="The type-check fails in several files after someone made the stock lookup async.",
         describe="getStock made async; its callers compare the Promise to a number (errors in inventory.ts AND orders.ts)", fix="make getStock synchronous again",
         fallback="src/inventory.ts(23,7): error TS2365: Operator '<' cannot be applied to types 'Promise<number>' and 'number'.\n"
                  "src/orders.ts(21,7): error TS2365: Operator '<' cannot be applied to types 'Promise<number>' and 'number'."),
    dict(name="ts_medium_removed_guard", difficulty="medium", file="src/orders.ts",
         old="  if (!entry) {\n    throw new OrderError(`unknown product: ${sku}`);\n  }\n  if (getStock(sku) < qty) {\n    throw new OutOfStock(`out of stock: ${sku}`);\n  }\n  const total = lineTotal(entry.price, qty, discountPct);",
         new="  if (getStock(sku) < qty) {\n    throw new OutOfStock(`out of stock: ${sku}`);\n  }\n  const total = lineTotal(entry!.price, qty, discountPct);", run="tests",
         message="Ordering an unknown product returns a crash instead of a clean error.",
         describe="the unknown-product guard was removed and `entry!.price` silences the type-check (compiles, crashes at run time)", fix="restore the `if (!entry) throw new OrderError(...)` guard",
         fallback="not ok 2 - an unknown product is an OrderError\n  error: Missing expected exception.\n# fail 1"),
]


def build_ts_cases() -> None:
    for bug in TS_BUGS:
        emit_case(bug["name"], "TypeScript", ts_base, bug, ts_capture)


# ============================================================================================================ STATIC SITE
PAGES = [("index", "Home"), ("products", "Products"), ("about", "About us"), ("contact", "Contact"), ("faq", "FAQ")]


def site_css() -> str:
    parts = [":root {\n  --brand: #1f6f5b;\n  --accent: #e0a526;\n  --ink: #1d2327;\n  --paper: #fbfaf7;\n}\n",
             "* { box-sizing: border-box; }\nbody { margin: 0; font-family: Georgia, serif; color: var(--ink); background: var(--paper); line-height: 1.5; }\n",
             "a { color: var(--brand); }\nimg { max-width: 100%; height: auto; }\n"]
    for comp in ["header", "nav", "hero", "card", "grid", "footer", "form", "button", "badge", "table", "faq", "banner", "gallery", "price", "tag"]:
        parts.append(f".{comp} {{\n  margin: 0 auto;\n  padding: 12px 16px;\n  border-radius: 6px;\n}}\n")
        parts.append(f".{comp}:hover {{\n  outline: 2px solid var(--accent);\n}}\n")
        parts.append(f".{comp} h2 {{\n  margin: 0 0 8px;\n  font-size: 1.25rem;\n  color: var(--brand);\n}}\n")
    parts.append("@media (max-width: 600px) {\n  .grid { display: block; }\n  .nav { text-align: center; }\n  .hero { padding: 24px 8px; }\n}\n")
    parts.append(".grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }\n")
    parts.append(".button { background: var(--brand); color: white; border: 0; cursor: pointer; }\n")
    return "".join(parts)


def static_page(slug: str, title: str) -> str:
    cards = "\n".join(f'      <div class="card">\n        <h2>{title} item {i}</h2>\n        <p>Short description number {i} for {title.lower()}.</p>\n'
                      f'        <img src="img/photo{i % 3 + 1}.png" alt="photo {i}">\n      </div>' for i in range(1, 5))
    nav = "\n".join(f'        <li><a href="{s}.html">{t}</a></li>' for s, t in PAGES)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title} - Tea and Mugs</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="css/styles.css">
  <script src="js/app.js" defer></script>
</head>
<body>
  <header class="header">
    <nav class="nav">
      <ul>
{nav}
      </ul>
    </nav>
  </header>
  <main>
    <section class="hero">
      <h1>{title}</h1>
      <p>Welcome to our little shop.</p>
    </section>
    <section class="grid">
{cards}
    </section>
    <form class="form" action="contact.html">
      <label>Email <input type="email" name="email"></label>
      <button class="button" type="submit">Send</button>
    </form>
  </main>
  <footer class="footer">
    <p>&copy; Tea and Mugs</p>
  </footer>
  <script>
    document.title = document.title + ' ';
  </script>
</body>
</html>
'''


SITE_JS_APP = '''// Small helpers shared by every page.
function $(selector, root = document) {
  return root.querySelector(selector);
}

function $all(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

function highlightNav() {
  const here = location.pathname.split('/').pop() || 'index.html';
  $all('nav a').forEach((link) => {
    if (link.getAttribute('href') === here) {
      link.classList.add('current');
    }
  });
}

function wireForms() {
  $all('form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const email = form.querySelector('input[type=email]');
      if (email && !email.value.includes('@')) {
        event.preventDefault();
        alert('Please enter a valid email address');
      }
    });
  });
}

window.addEventListener('DOMContentLoaded', () => {
  highlightNav();
  wireForms();
});
'''

SITE_JS_CART = '''// A tiny in-memory shopping cart.
const cart = [];

function addToCart(sku, price, qty = 1) {
  const existing = cart.find((line) => line.sku === sku);
  if (existing) {
    existing.qty += qty;
  } else {
    cart.push({ sku, price, qty });
  }
  return cart.length;
}

function cartTotal() {
  let total = 0;
  for (const line of cart) {
    total += line.price * line.qty;
  }
  return Math.round(total * 100) / 100;
}

function clearCart() {
  cart.length = 0;
}
'''


def static_base(repo: Path) -> None:
    for slug, title in PAGES:
        write(repo / f"{slug}.html", static_page(slug, title))
    write(repo / "css/styles.css", site_css())
    write(repo / "js/app.js", SITE_JS_APP)
    write(repo / "js/cart.js", SITE_JS_CART)
    write(repo / "data/products.json", json.dumps({"products": [{"sku": "tea", "price": 120}, {"sku": "coffee", "price": 250}, {"sku": "mug", "price": 399}]}, indent=2) + "\n")
    for i in (1, 2, 3):
        write(repo / f"img/photo{i}.png", "not a real png, but the file exists\n")


def static_capture(repo: Path, bug: dict) -> str:
    return run([sys.executable, str(HERE.parent / "sandbox" / "static_check.py"), "."], repo)


STATIC_BUGS = [
    dict(name="static_easy_unclosed_div", difficulty="easy", file="index.html",
         old='      <div class="card">\n        <h2>Home item 2</h2>', new='      <div class="card">\n        <h2>Home item 2</h2>\n      <div class="card">',
         message="The home page layout is broken: the second card swallows everything below it.",
         describe="an extra <div class=\"card\"> was opened and never closed in index.html", fix="remove the stray opening <div>",
         fallback="index.html:22: unclosed <div> (still open at </section> on line 33)\nstatic_check: 1 errors in 8 files"),
    dict(name="static_easy_wrong_stylesheet_name", difficulty="easy", file="products.html",
         old='href="css/styles.css"', new='href="css/style.css"',
         message="The Products page has no styling at all, the other pages look fine.",
         describe="the stylesheet link points to css/style.css which does not exist", fix='href="css/styles.css"',
         fallback="products.html:7: missing file css/style.css\nstatic_check: 1 errors in 8 files"),
    dict(name="static_medium_css_missing_brace", difficulty="medium", file="css/styles.css",
         old=".card:hover {\n  outline: 2px solid var(--accent);\n}\n", new=".card:hover {\n  outline: 2px solid var(--accent);\n",
         message="After the last style change half of the CSS stopped applying on every page.",
         describe="closing brace missing after .card:hover, which breaks the rules that follow", fix="add the missing }",
         fallback="css/styles.css:30: missing } (block opened here is never closed)\nstatic_check: 1 errors in 8 files"),
    dict(name="static_medium_js_syntax_error", difficulty="medium", file="js/cart.js",
         old="function cartTotal() {\n  let total = 0;", new="function cartTotal( {\n  let total = 0;",
         message="The cart does nothing any more; the browser console shows a syntax error.",
         describe="a missing parenthesis in cartTotal's parameter list", fix="function cartTotal() {",
         fallback="js/cart.js:15: SyntaxError: Unexpected token '{'\nstatic_check: 1 errors in 8 files"),
    dict(name="static_medium_invalid_json", difficulty="medium", file="data/products.json",
         old='    }\n  ]\n}', new='    },\n  ]\n}',
         message="The product list will not load (the browser says the data is invalid).",
         describe="a trailing comma in data/products.json", fix="remove the trailing comma",
         fallback="data/products.json:1: invalid JSON: Expecting value\nstatic_check: 1 errors in 8 files"),
]


def build_static_cases() -> None:
    for bug in STATIC_BUGS:
        emit_case(bug["name"], "Static HTML/CSS/JS", static_base, bug, static_capture)


# ========================================================================================================== PYTHON EXTRAS
def build_python_extras() -> None:
    import make_cases as mc

    pricing_cache = '''"""Remembers unit prices so the catalogue is not searched on every order."""
_BASE = {{"tea": 120.0, "coffee": 250.0, "mug": 399.0}}
_CACHE: dict[str, float] = {{}}


def price_of(sku: str) -> float:
    if sku not in _CACHE:
        _CACHE[sku] = _BASE[sku]
    return _CACHE[sku]


def update_price(sku: str, price: float) -> None:
    _BASE[sku] = price
{invalidate}

def reset() -> None:
    _BASE.update({{"tea": 120.0, "coffee": 250.0, "mug": 399.0}})
    _CACHE.clear()
'''
    admin = '''"""Admin actions: change prices and show them."""
import price_cache


def change_price(sku: str, new_price: float) -> float:
    if new_price <= 0:
        raise ValueError("price must be positive")
    price_cache.update_price(sku, new_price)
    return price_cache.price_of(sku)
'''
    storefront = '''"""Storefront: what a customer pays for a basket."""
import price_cache


def basket_total(items: list[tuple[str, int]]) -> float:
    return round(sum(price_cache.price_of(sku) * qty for sku, qty in items), 2)
'''
    test = '''import admin
import price_cache
import storefront


def setup_function():
    price_cache.reset()


def test_basket_total():
    assert storefront.basket_total([("tea", 2), ("mug", 1)]) == 639.0


def test_new_price_is_used_by_the_storefront():
    assert storefront.basket_total([("tea", 1)]) == 120.0
    admin.change_price("tea", 150.0)
    assert storefront.basket_total([("tea", 1)]) == 150.0
'''

    def base_hard(repo: Path, invalidate: str) -> None:
        mc.base_repo(repo)
        mc.write(repo / "price_cache.py", pricing_cache.format(invalidate=invalidate))
        mc.write(repo / "admin.py", admin)
        mc.write(repo / "storefront.py", storefront)
        mc.write(repo / "tests" / "test_price_cache.py", test)

    name = "py_hard_stale_price_cache"
    repo = ROOT / name / "repo"
    shutil.rmtree(ROOT / name, ignore_errors=True)
    base_hard(repo, "")     # the bug: the cache entry is never dropped
    tb = mc.traceback_for(repo, "pytest:tests/test_price_cache.py")
    mc.write(ROOT / name / "incident.json", json.dumps({"message": "After an admin changes a price, customers still see the OLD price until the server restarts (stale cache).",
                                                        "traceback": tb or "FAILED tests/test_price_cache.py::test_new_price_is_used_by_the_storefront\nassert 120.0 == 150.0\n"}, indent=2))
    KEY.append({"case": name, "language": "Python", "difficulty": "hard", "file": "price_cache.py", "bug": "update_price never drops the cached price",
                "fix": "add _CACHE.pop(sku, None) in update_price", "lines": sum(len(p.read_text().splitlines()) for p in repo.rglob("*.py")), "captured": "yes"})
    print(f"{name}: written (python, hard)")

    name = "py_no_tests_nameerror"
    repo = ROOT / name / "repo"
    shutil.rmtree(ROOT / name, ignore_errors=True)
    for mod, cls in mc.BULK[:4]:
        mc.write(repo / f"{mod}.py", mc.GENERIC.format(title=cls, cls=cls))
    mc.write(repo / "reports.py", mc.REPORTS.format(var="totl"))
    mc.write(repo / "requirements.txt", "")
    tb = mc.traceback_for(repo, "import reports\nreports.sales_total([{'total': 5}])")
    mc.write(ROOT / name / "incident.json", json.dumps({"message": "NameError: name 'totl' is not defined", "traceback": tb}, indent=2))
    KEY.append({"case": name, "language": "Python", "difficulty": "easy", "file": "reports.py", "bug": "`total` misspelled `totl` in a project with NO tests (fix can only be build-checked)",
                "fix": "rename totl -> total", "lines": sum(len(p.read_text().splitlines()) for p in repo.rglob("*.py")), "captured": "yes"})
    print(f"{name}: written (python, easy, no tests)")


# ======================================================================================================================
def write_answer_key() -> None:
    lines = ["# Benchmark answer key", "",
             "Every case is one clean project with exactly ONE planted bug. `fix` says what a correct patch does.", "",
             "| case | language | difficulty | file | the bug | correct fix | lines | incident captured by running it |", "|---|---|---|---|---|---|---|---|"]
    for r in KEY:
        lines.append(f"| {r['case']} | {r['language']} | {r['difficulty']} | `{r['file']}` | {r['bug']} | {r['fix']} | {r['lines']} | {r['captured']} |")
    (HERE / "ANSWER_KEY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    build_java_cases()
    build_js_cases()
    build_ts_cases()
    build_static_cases()
    build_python_extras()
    write_answer_key()


if __name__ == "__main__":
    main()
