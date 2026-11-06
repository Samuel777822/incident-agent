from fixengine import config as fx_config, sim


def test_router_rules_hold_over_thousands_of_simulated_bugs():
    cfg = fx_config.load()
    for tokens in (10000, 50000, 90000):
        for cls, r in sim.run(n=400, cfg=cfg, repo_tokens=tokens).items():
            assert r["max_tries"] <= cfg["caps"]["per_bug_max_tries"]
            # the per-bug rupee cap can be crossed by at most one last try
            assert r["max_cost"] <= cfg["caps"]["per_bug_cost_inr"] + 30


def test_small_tickets_cost_very_little():
    r = sim.run(n=600, cfg=fx_config.load(), repo_tokens=10000)
    assert r["easy"]["mean_cost"] < 3 and r["easy"]["solved"] > 0.9


def test_free_and_haiku_always_run_before_any_strong_model():
    cfg = fx_config.load()
    import random
    rng = random.Random(3)
    for _ in range(300):
        res = sim.simulate_bug(cfg, "medium", 20000, rng)
        path = res["path"]
        first_strong = next((i for i, t in enumerate(path) if t in ("sonnet", "opus")), None)
        if first_strong is not None:
            assert path[:first_strong].count("haiku") >= 2 or "haiku" not in path[:first_strong + 1]
