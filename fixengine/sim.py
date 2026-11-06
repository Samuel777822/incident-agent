"""Router simulation (plan 6.10): run thousands of fake bugs through the REAL router with made-up success odds.

    python -m fixengine.sim            # prints cost per bug class, how often each mode is used, worst cases

It costs nothing. It checks that the rules hold (floor, drop-back, caps, quotas) and shows what a month might cost.
Numbers are only as good as the placeholder probabilities in config.PLACEHOLDER_P.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import replace

from . import config as fx_config
from . import router

PAID = fx_config.PAID_TIERS


def simulate_bug(cfg: dict, bug_class: str, repo_tokens: int, rng: random.Random, probs: dict | None = None,
                 quota_left=(30, 6, 3), mode="auto") -> dict:
    probs = probs or fx_config.PLACEHOLDER_P
    table = router.ProbTable(cfg)
    s = router.RouterInput(bug_class=bug_class, mode=mode, quota_left=tuple(quota_left), quota_total=(30, 6, 3),
                           repo_tokens=repo_tokens, cur_info="s0")
    cost, path = 0.0, []
    for step in range(cfg["caps"]["per_bug_max_tries"] + 3):
        d = router.decide(s, cfg, table)
        if d.action == "stop":
            return {"solved": False, "cost": cost, "path": path, "tries": s.total_tries, "stop": d.reason}
        tier = d.action
        tok = cfg["tokens"]
        tin = min(repo_tokens, tok["groq_prompt_tokens"] if tier == "groq" else tok["max_prompt_tokens"]) + (tok["retry_overhead_in"] if s.total_tries else 0)
        spent = fx_config.estimate_cost_inr(cfg, tier, tin, tok["expected_out"])
        cost += spent
        path.append(tier)
        cell = "haiku_diag" if tier == "haiku" and s.strong_diag else tier
        p = probs[bug_class][cell] * (cfg["router"]["repeat_decay"] ** {"groq": s.free_tries, "haiku": s.haiku_tries,
                                                                         "sonnet": s.sonnet_tries, "opus": s.opus_tries}[tier])
        won = rng.random() < p
        if won:
            return {"solved": True, "cost": cost, "path": path, "tries": s.total_tries + 1, "stop": ""}
        progress = rng.random() < 0.4
        q = list(s.quota_left)
        if tier in PAID:
            q[PAID.index(tier)] -= 1
        info = f"{s.cur_info}>{step}"
        base = dict(spent_inr=cost, total_tries=s.total_tries + 1, last_tier=tier, last_progress=progress, quota_left=tuple(q), cur_info=info)
        if tier == "groq":
            s = replace(s, free_tries=s.free_tries + 1, **base)
        elif tier == "haiku":
            s = replace(s, haiku_tries=s.haiku_tries + 1, haiku_since_strong=s.haiku_since_strong + 1 if s.strong_diag else 0, **base)
        elif tier == "sonnet":
            s = replace(s, sonnet_tries=s.sonnet_tries + 1, strong_diag=True, haiku_since_strong=0, **base)
        else:
            s = replace(s, opus_tries=s.opus_tries + 1, strong_diag=True, haiku_since_strong=0, **base)
    return {"solved": False, "cost": cost, "path": path, "tries": s.total_tries, "stop": "loop limit"}


def run(n=2000, seed=7, cfg: dict | None = None, mix=(("easy", 0.45), ("medium", 0.35), ("hard", 0.20)), repo_tokens=30000) -> dict:
    cfg = cfg or fx_config.load()
    rng = random.Random(seed)
    out: dict = {}
    for bug_class, _share in mix:
        runs = [simulate_bug(cfg, bug_class, repo_tokens, rng) for _ in range(n)]
        costs = sorted(r["cost"] for r in runs)
        usage = {t: sum(r["path"].count(t) for r in runs) / n for t in fx_config.TIERS}
        out[bug_class] = {"solved": sum(r["solved"] for r in runs) / n, "mean_cost": statistics.mean(costs),
                          "p95_cost": costs[int(0.95 * n)], "max_cost": costs[-1], "tries_per_bug": usage,
                          "max_tries": max(r["tries"] for r in runs)}
    return out


if __name__ == "__main__":
    cfg = fx_config.load()
    for tokens in (10000, 50000):
        print(f"\n=== repo size about {tokens} tokens ===")
        for cls, r in run(cfg=cfg, repo_tokens=tokens).items():
            used = ", ".join(f"{t} {v:.1f}" for t, v in r["tries_per_bug"].items())
            print(f"{cls:7s} solved {r['solved']:.0%}  mean Rs {r['mean_cost']:.1f}  p95 Rs {r['p95_cost']:.1f}  max Rs {r['max_cost']:.1f}  tries/bug: {used}")
