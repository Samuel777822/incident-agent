# Autonomous Repair Pipeline Proof (Proof F)

- **Incident ID:** `5e4e8002-9890-4a98-82d3-cf9bce70b985`
- **Sandbox Runner & Image:** `DockerRunner` (`fixengine-sandbox-python:1`)
- **Baseline Failing Tests in Docker:** `3`
- **Final Outcome:** `pr_opened` (Verification level: `strong`, Auto-merged: `False`)
- **Pull Request URL:** `https://github.com/acme/buggy-shop/pull/42` (branch `agent-daemon/fix-6f430b806f394d`)

## Baseline Output (Before Fix)
```text
[test] exit 1
...............FFF......................                                 [100%]
=================================== FAILURES ===================================
_______________________________ test_order_total _______________________________

    def test_order_total():
        o = orders.create_order([('tea', 2)], 10)
>       assert o['total'] == 216.0
E       assert 0.0 == 216.0

tests/test_orders.py:6: AssertionError
________________________________ test_discount _________________________________

    def test_discount():
>       assert apply_discount(200, 10) == 180
E       assert 0.0 == 180
E        +  where 0.0 = apply_discount(200, 10)

tests/test_pricing.py:5: AssertionError
__________________________________ test_line ___________________________________

    def test_line():
>       assert line_total(100, 3, 10) == 270
E       assert 0.0 == 270
E        +  where 0.0 = line_total(100, 3, 10)

tests/test_pricing.py:9: AssertionError
=========================== short test summary info ============================
FAILED tests/test_orders.py::test_order_total - assert 0.0 == 216.0
FAILED tests/test_pricing.py::test_discount - assert 0.0 == 180
 +  where 0.0 = apply_discount(200, 10)
FAILED tests/test_pricing.py::test_line - assert 0.0 == 270
 +  where 0.0 = line_total(100, 3, 10)
3 failed, 37 passed in 0.89s
```

## Attempt Ledger

| # | Tier | Model | Result | Failing Before | Failing After | Diagnosis |
|---|---|---|---|---|---|---|
| 1 | `groq` | `openai/gpt-oss-120b` | `unusable` | `None` | `None` | - |
| 2 | `groq` | `openai/gpt-oss-120b` | `unusable` | `None` | `None` | - |
| 3 | `groq` | `openai/gpt-oss-120b` | `unusable` | `None` | `None` | - |
| 4 | `haiku` | `claude-haiku-5-5` | `pass` | `3` | `0` | apply_discount in pricing.py divides pct by 10 instead of 100, causing a 10% discount to wipe out 100% of the price. |

## Validated Unified Diff
```diff
--- a/pricing.py
+++ b/pricing.py
@@ -5,7 +5,7 @@
 def apply_discount(price: float, pct: float) -> float:
     if pct < 0 or pct > 100:
         raise ValueError("discount must be between 0 and 100")
-    return round(price - price * pct / 10, 2)
+    return round(price - price * pct / 100, 2)
 
 
 def add_tax(price: float) -> float:
```
