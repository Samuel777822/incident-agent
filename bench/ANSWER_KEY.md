# Benchmark answer key

Every case is one clean project with exactly ONE planted bug. `fix` says what a correct patch does.

| case | language | difficulty | file | the bug | correct fix | lines | incident captured by running it |
|---|---|---|---|---|---|---|---|
| java_easy_typo_variable | Java | easy | `src/main/java/com/shop/Reports.java` | variable `total` misspelled as `totl` in salesTotal (compile error) | rename totl -> total | 1995 | yes |
| java_medium_logic_discount | Java | medium | `src/main/java/com/shop/Pricing.java` | discount divided by 10 instead of 100 in applyDiscount | price * pct / 100 | 1995 | yes |
| java_medium_npe_unknown_sku | Java | medium | `src/main/java/com/shop/Inventory.java` | getStock unboxes a null Integer for unknown SKUs instead of throwing InventoryException | restore the null check and InventoryException | 1991 | yes |
| java_medium_cross_file_rename | Java | medium | `src/main/java/com/shop/Inventory.java` | Inventory.getStock renamed to stockFor, but Orders and Cart still call getStock (compile error in OTHER files) | revert the rename in Inventory.java | 1995 | yes |
| java_hard_concurrent_modification | Java | hard | `src/main/java/com/shop/Cart.java` | removing from a list inside a for-each loop (ConcurrentModificationException) | use removeIf or an iterator | 1999 | yes |
| java_hard_stale_price_cache | Java | hard | `src/main/java/com/shop/PriceCache.java` | setPrice forgets to invalidate the cached price | CACHE.remove(sku) after updating BASE | 1994 | yes |
| js_easy_reference_error | JavaScript | easy | `src/reports.js` | variable `total` misspelled `totl` in salesTotal | rename totl -> total | 1239 | yes |
| js_medium_logic_discount | JavaScript | medium | `src/pricing.js` | discount divided by 10 instead of 100 | (price * pct) / 100 | 1239 | yes |
| js_medium_export_rename | JavaScript | medium | `src/inventory.js` | getStock renamed to stockFor in inventory.js while orders.js still imports getStock (error shows in ANOTHER file) | revert the rename in inventory.js | 1239 | yes |
| js_hard_missing_await | JavaScript | hard | `src/inventory.js` | getStock became async (returns a Promise) but callers compare it as a number, so the stock check silently never fires | make getStock synchronous again (or await it everywhere) | 1239 | yes |
| js_medium_typeerror_unknown | JavaScript | medium | `src/orders.js` | the guard for an unknown product was deleted | restore the `if (!entry) throw new OrderError(...)` guard | 1236 | yes |
| ts_easy_wrong_argument_type | TypeScript | easy | `src/orders.ts` | qty converted to a string before being passed to lineTotal (TS2345) | pass qty as a number | 1068 | yes |
| ts_medium_property_rename | TypeScript | medium | `src/catalog.ts` | Product.price renamed to cost in catalog.ts; orders.ts still reads entry.price and the catalog still uses price (errors show in OTHER places) | revert the rename in catalog.ts | 1068 | yes |
| ts_medium_logic_discount | TypeScript | medium | `src/pricing.ts` | discount divided by 10 instead of 100 (compiles fine, only the tests catch it) | (price * pct) / 100 | 1068 | yes |
| ts_hard_promise_in_comparison | TypeScript | hard | `src/inventory.ts` | getStock made async; its callers compare the Promise to a number (errors in inventory.ts AND orders.ts) | make getStock synchronous again | 1068 | yes |
| ts_medium_removed_guard | TypeScript | medium | `src/orders.ts` | the unknown-product guard was removed and `entry!.price` silences the type-check (compiles, crashes at run time) | restore the `if (!entry) throw new OrderError(...)` guard | 1065 | yes |
| static_easy_unclosed_div | Static HTML/CSS/JS | easy | `index.html` | an extra <div class="card"> was opened and never closed in index.html | remove the stray opening <div> | 592 | yes |
| static_easy_wrong_stylesheet_name | Static HTML/CSS/JS | easy | `products.html` | the stylesheet link points to css/style.css which does not exist | href="css/styles.css" | 591 | yes |
| static_medium_css_missing_brace | Static HTML/CSS/JS | medium | `css/styles.css` | closing brace missing after .card:hover, which breaks the rules that follow | add the missing } | 590 | yes |
| static_medium_js_syntax_error | Static HTML/CSS/JS | medium | `js/cart.js` | a missing parenthesis in cartTotal's parameter list | function cartTotal() { | 591 | yes |
| static_medium_invalid_json | Static HTML/CSS/JS | medium | `data/products.json` | a trailing comma in data/products.json | remove the trailing comma | 591 | yes |
| py_hard_stale_price_cache | Python | hard | `price_cache.py` | update_price never drops the cached price | add _CACHE.pop(sku, None) in update_price | 1300 | yes |
| py_no_tests_nameerror | Python | easy | `reports.py` | `total` misspelled `totl` in a project with NO tests (fix can only be build-checked) | rename totl -> total | 304 | yes |
