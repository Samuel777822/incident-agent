# Web cases (v3.1)

Five website problems the on-call engineer must handle. Each `case.json` has the events the monitors (or the owner) send, a tiny
repository, optionally what the live site shows, and what a correct outcome looks like (`expect`).

| Case | What it checks |
| --- | --- |
| broken_api | one broken outside call = ONE case (the failed request and the error text are merged) and the fix is in app.js |
| dead_button | a renamed id: proven by a browser journey (click Send, a message appears) |
| retired_free_model | fixed without any AI try, and the replacement is free |
| vague_report | a plain-words report: starts with High mode, opens the live page first, finds app.js |
| duplicate_flood | 10 dead clicks + 3 identical reports = 1 case, 1 paid diagnosis, 1 fix |

Here they run with fakes inside `tests/test_v31.py` (grouping, the loop, the policy, the live check). With real models and keys on
your laptop, run them through `fixengine_bench.py` with a cost limit, exactly like `bench/cases` (see RUN_TESTS.md, layer 4).
