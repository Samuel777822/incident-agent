"""The router: an expected-cost optimizer with hard rules on top (plan section 6).

V(state) = min over allowed actions a of  effective_cost(a) + (1 - p(a)) * V(state after a fails)
V(success) = 0,  V(human review) = G.   Search depth is about 6 and cached; it runs instantly.

Only this module chooses models. It has no side effects: callers pass in a RouterInput and get a
Decision back, and the caller logs it (plan 6.9) before doing anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache

from . import config as fx_config

PAID = ("haiku", "sonnet", "opus")
STRONG = ("sonnet", "opus")


@dataclass(frozen=True)
class RouterInput:
    bug_class: str = "medium"
    mode: str = "auto"                 # auto | ask | economy
    free_tries: int = 0
    haiku_tries: int = 0
    sonnet_tries: int = 0
    opus_tries: int = 0
    last_tier: str = ""
    strong_diag: bool = False          # a diagnosis from sonnet/opus exists
    last_progress: bool = False
    haiku_since_strong: int = 0
    unusable_streak_haiku: int = 0
    spent_inr: float = 0.0
    total_tries: int = 0
    quota_left: tuple = (0, 0, 0)      # haiku, sonnet, opus tries left this month (after guard/pauses)
    quota_total: tuple = (30, 6, 3)
    groq_available: bool = True
    seen: frozenset = field(default_factory=frozenset)   # {(tier, info_hash)} already tried
    cur_info: str = ""
    pinned: str = ""                   # tier the user chose at a warning ('' = none)
    repo_tokens: int = 10000


@dataclass
class Decision:
    action: str                        # groq | haiku | sonnet | opus | stop
    reason: str
    forced: bool = False
    options: list = field(default_factory=list)   # [{"action","expected_cost","p"}] considered


class ProbTable:
    """p(one try succeeds). Placeholders until a cell has enough ledger data (plan 6.8)."""

    def __init__(self, cfg: dict, stats: dict | None = None):
        self.cfg = cfg
        self.stats = stats or {}

    def get(self, bug_class: str, cell: str) -> float:
        ok, n = self.stats.get((bug_class, cell), (0, 0))
        if n >= int(self.cfg["router"]["min_samples_for_learned"]):
            return (ok + 1) / (n + 2)
        return fx_config.PLACEHOLDER_P.get(bug_class, fx_config.PLACEHOLDER_P["medium"])[cell]


def _idx(tier: str) -> int:
    return PAID.index(tier)


def _tries(s: RouterInput, tier: str) -> int:
    return {"haiku": s.haiku_tries, "sonnet": s.sonnet_tries, "opus": s.opus_tries}[tier]


def _est_cost(cfg: dict, tier: str, s: RouterInput) -> float:
    tok = cfg["tokens"]
    tokens_in = min(s.repo_tokens, tok["max_prompt_tokens"], int(tok.get("context_tokens", tok["max_prompt_tokens"])) + 6000) + (tok["retry_overhead_in"] if s.total_tries else 0)
    tokens_out = int(tok["expected_out"] * tok.get("reasoning_out_multiplier", 1.0))
    return fx_config.estimate_cost_inr(cfg, tier, tokens_in, tokens_out)


def _effective_cost(cfg: dict, tier: str, s: RouterInput) -> float:
    i = _idx(tier)
    total = max(1, s.quota_total[i])
    used_fraction = min(1.0, max(0.0, 1.0 - s.quota_left[i] / total))
    return _est_cost(cfg, tier, s) * (1.0 + float(cfg["router"]["lambda"]) * used_fraction)


def _haiku_allowed(s: RouterInput, cfg: dict) -> tuple[bool, bool, str]:
    """Return (allowed, forced, why) for Haiku from the floor / drop-back / progress rules."""
    r = cfg["router"]
    if s.quota_left[0] <= 0:
        return False, False, "haiku quota exhausted"
    if s.strong_diag:  # drop-back phase (rule 4)
        if s.last_tier in STRONG:
            return True, True, "drop back to Haiku with the stronger model's diagnosis"
        if s.haiku_since_strong < int(r["drop_back_tries"]) and s.last_tier == "haiku" and s.last_progress:
            return True, False, "Haiku made progress after the drop-back"
        return False, False, "drop-back Haiku had no progress"
    waived = s.unusable_streak_haiku >= int(r["unusable_waives_floor_after"])
    if waived:
        return False, False, "Haiku returned unusable results twice: floor waived"
    if s.haiku_tries < int(r["haiku_floor"]):
        return True, True, f"Haiku floor: {s.haiku_tries} of {r['haiku_floor']} tries done"
    if s.haiku_tries < int(r["haiku_floor_max_with_progress"]) and s.last_tier == "haiku" and s.last_progress:
        return True, False, "third Haiku try allowed because the last try made progress"
    return False, False, "Haiku floor met and no progress"


def allowed_actions(s: RouterInput, cfg: dict) -> tuple[list[str], str | None, str]:
    """Hard rules that override the optimizer. Returns (allowed, forced_action_or_None, forced_reason)."""
    est_ok = {}
    cap = float(cfg["caps"]["per_bug_cost_inr"])
    for tier in PAID:
        est_ok[tier] = s.quota_left[_idx(tier)] > 0 and s.spent_inr + _est_cost(cfg, tier, s) <= cap
        if (tier, s.cur_info) in s.seen:      # rule 6: never repeat a model with the same information
            est_ok[tier] = False
    allowed: list[str] = []
    forced, forced_reason = None, ""
    h_ok, h_forced, h_why = _haiku_allowed(s, cfg)
    if h_ok and est_ok["haiku"]:
        allowed.append("haiku")
        if h_forced:
            forced, forced_reason = "haiku", h_why
    if s.mode != "economy":
        pre_floor = (not s.strong_diag and s.haiku_tries < int(cfg["router"]["haiku_floor"])
                     and s.quota_left[0] > 0 and s.unusable_streak_haiku < int(cfg["router"]["unusable_waives_floor_after"]))
        if not (pre_floor and "haiku" in allowed):       # Sonnet/Opus stay locked until the floor is met
            for tier in STRONG:
                if est_ok[tier]:
                    allowed.append(tier)
    if forced and forced not in allowed:
        forced, forced_reason = None, ""
    return allowed, forced, forced_reason


def _next_state(s: RouterInput, action: str, cfg: dict, cost: float) -> RouterInput:
    q = list(s.quota_left)
    q[_idx(action)] -= 1
    common = dict(spent_inr=s.spent_inr + cost, total_tries=s.total_tries + 1, last_tier=action,
                  last_progress=False, seen=frozenset(), cur_info=f"{s.cur_info}>{action}", quota_left=tuple(q), pinned="")
    if action == "haiku":
        return replace(s, haiku_tries=s.haiku_tries + 1,
                       haiku_since_strong=s.haiku_since_strong + 1 if s.strong_diag else 0, **common)
    if action == "sonnet":
        return replace(s, sonnet_tries=s.sonnet_tries + 1, strong_diag=True, haiku_since_strong=0, **common)
    return replace(s, opus_tries=s.opus_tries + 1, strong_diag=True, haiku_since_strong=0, **common)


def _p(action: str, s: RouterInput, cfg: dict, probs: ProbTable) -> float:
    cell = "haiku_diag" if action == "haiku" and s.strong_diag else action
    base = probs.get(s.bug_class, cell)
    prior_fails = _tries(s, action)
    return base * (float(cfg["router"]["repeat_decay"]) ** prior_fails)


def solve(s: RouterInput, cfg: dict, probs: ProbTable) -> tuple[float, str, list]:
    """Return (expected cost, best action, option table) for the current state."""
    G = float(cfg["router"]["give_up_penalty_inr"])
    max_depth = int(cfg["router"]["max_depth"])
    cache: dict = {}

    def key(st, depth):
        return (st.haiku_tries, st.sonnet_tries, st.opus_tries, st.last_tier, st.strong_diag, st.haiku_since_strong,
                st.quota_left, round(st.spent_inr, 2), st.last_progress, st.unusable_streak_haiku, st.mode, depth)

    def value(st: RouterInput, depth: int) -> float:
        if depth <= 0:
            return G
        k = key(st, depth)
        if k in cache:
            return cache[k]
        allowed, forced, _ = allowed_actions(st, cfg)
        best = G
        for a in ([forced] if forced else allowed):
            cost = _effective_cost(cfg, a, st)
            p = _p(a, st, cfg, probs)
            v = cost + (1.0 - p) * value(_next_state(st, a, cfg, _est_cost(cfg, a, st)), depth - 1)
            best = min(best, v)
        cache[k] = best
        return best

    allowed, forced, _ = allowed_actions(s, cfg)
    options = []
    for a in allowed:
        cost = _effective_cost(cfg, a, s)
        p = _p(a, s, cfg, probs)
        v = cost + (1.0 - p) * value(_next_state(s, a, cfg, _est_cost(cfg, a, s)), max_depth - 1)
        options.append({"action": a, "expected_cost": round(v, 2), "try_cost": round(_est_cost(cfg, a, s), 2), "p": round(p, 3)})
    options.append({"action": "stop", "expected_cost": round(G, 2), "try_cost": 0.0, "p": 0.0})
    best = min(options, key=lambda o: o["expected_cost"])
    return best["expected_cost"], best["action"], options


def decide(s: RouterInput, cfg: dict, probs: ProbTable | None = None) -> Decision:
    probs = probs or ProbTable(cfg)
    r = cfg["router"]
    caps = cfg["caps"]
    # Hard stops first.
    if s.total_tries >= int(caps["per_bug_max_tries"]):
        return Decision("stop", f"per-bug cap of {caps['per_bug_max_tries']} tries reached", True)
    if s.spent_inr >= float(caps["per_bug_cost_inr"]):
        return Decision("stop", f"per-bug cost cap of Rs {caps['per_bug_cost_inr']} reached", True)
    # Rule 5: the user's own pick wins, inside their quota.
    if s.pinned in PAID and s.quota_left[_idx(s.pinned)] > 0 and (s.pinned, s.cur_info) not in s.seen:
        return Decision(s.pinned, "you chose this mode", True,
                        [{"action": s.pinned, "expected_cost": round(_est_cost(cfg, s.pinned, s), 2), "p": None}])
    # Rule 1: free first, up to 3 tries, each passing its failure report forward.
    if s.free_tries < int(r["free_tries"]) and s.groq_available and s.total_tries == s.free_tries:
        return Decision("groq", f"free first: try {s.free_tries + 1} of {r['free_tries']}", True)
    allowed, forced, forced_reason = allowed_actions(s, cfg)
    if not allowed:
        # Plain words: this text is shown to the customer as the reason the agent stopped, so it says what to do next.
        if s.mode == "economy":
            why = ("Economy mode only uses the free AI, and its tries for this problem are used up. Next step: switch to Auto mode "
                   "on the Usage page, or read the report below.")
        elif not any(int(x or 0) > 0 for x in (s.quota_left or ())):
            why = "This month's AI tries are used up. Next step: add a pack on the Usage page, or wait for the new month."
        else:
            why = ("The agent used every try it may spend on one problem and no fix passed the tests. Nothing was pushed. "
                   "Next step: read the report below; this one needs a human look.")
        return Decision("stop", why, True)
    if forced:
        cost = round(_est_cost(cfg, forced, s), 2)
        return Decision(forced, forced_reason, True, [{"action": forced, "expected_cost": cost, "p": None}])
    expected, best, options = solve(s, cfg, probs)
    if best == "stop":
        return Decision("stop", f"giving up is cheaper than trying more (about Rs {expected})", False, options)
    return Decision(best, f"lowest expected cost: about Rs {expected}", False, options)
