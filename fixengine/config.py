"""All prices, quotas, thresholds and probabilities live here, not in the code that uses them.

Every number is an ESTIMATE made before real data exists (plan v2, section 1). Override any
of them without a code change by putting a JSON object in FIXENGINE_CONFIG_JSON (env var) or
in fixengine_config.json next to this package's parent folder. Nested dicts are merged.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

TIERS = ("groq", "haiku", "sonnet", "opus")
PAID_TIERS = ("haiku", "sonnet", "opus")
STRONG_TIERS = ("sonnet", "opus")
USER_MODE_NAMES = {"groq": "Low effort", "haiku": "Engineer", "sonnet": "Lead engineer", "opus": "Lead engineer"}   # v6

DEFAULTS: dict = {
    "usd_inr": 90.0,
    # Model names come from the product list; verify on the provider pages before budgeting.
    "models": {
        "groq": "openai/gpt-oss-120b",
        "haiku": "claude-haiku-5-5",
        "sonnet": "claude-sonnet-5-5",
        "opus": "claude-opus-5-5",
    },
    # The same four tiers through OpenRouter (https://openrouter.ai). Ids follow OpenRouter's "vendor/model" style.
    # The free tier ":free" models are limited to 20 requests/minute and 50/day until you have bought $10 of credit.
    # VERIFY each id on https://openrouter.ai/models (the Opus id is the least certain); override with FIXENGINE_OPENROUTER_MODEL_<TIER>.
    "openrouter_models": {
        "groq": "openai/gpt-oss-120b:free",
        "haiku": "anthropic/claude-haiku-5.5",
        "sonnet": "anthropic/claude-sonnet-5.5",
        "opus": "anthropic/claude-opus-5.5",
    },
    # USD per million tokens. From plan section 5.2. VERIFY ON EACH PROVIDER PRICING PAGE.
    "prices_usd_per_m": {
        "groq": {"in": 0.0, "out": 0.0, "cache_read": 0.0},
        "haiku": {"in": 0.10, "out": 0.50, "in_over_100k": 0.50, "out_over_100k": 2.50, "cache_read": 0.01},
        "sonnet": {"in": 2.0, "out": 10.0, "cache_read": 0.20},
        "opus": {"in": 4.0, "out": 20.0, "cache_read": 0.40},
    },
    # Monthly tries per account (plan 5.4) and the try number at which the user is asked.
    "quotas": {"haiku": 30, "sonnet": 6, "opus": 3},
    "warn_at": {"haiku": 15, "sonnet": 3, "opus": 1},  # opus: warn on every use
    "warn_every_use": {"opus": True},
    "groq_daily_cap": 20,
    "caps": {
        "per_bug_cost_inr": 60.0,
        "per_bug_max_tries": 10,
        "user_month_ceiling_inr": 250.0,
        "tries_per_hour_per_user": 30,
        "new_bugs_per_hour_per_user": 20,
        "cooldown_after_failures": 4,       # consecutive failed bugs
        "cooldown_minutes": 30,
        # v3.1 on-call engineer: how much one try may look around before it must answer (each round is one model call)
        "investigation_rounds": 3,
        "investigation_requests_per_round": 3,
    },
    # Global monthly budget B (INR). For the ₹500 test: credits 500, B 400.
    "budget": {
        "credits_inr": 500.0,
        "b_inr": 400.0,
        "levels": [0.5, 0.8, 0.9, 1.0],      # fractions of B (plan 9.3)
        "reserve_floor_fraction_of_credits": 0.95,
        "spike_hour_multiple": 6.0,          # last hour vs average hourly spend this month
        # These two grow with the budget B (FIXENGINE_BUDGET_INR) unless set explicitly in FIXENGINE_CONFIG_JSON:
        "spike_hour_min_inr": None,          # ignore spikes below this: 10% of B (Rs 40 at B = 400)
        "project_hour_cap_inr": None,        # one project's AI spend per hour before ONLY that project waits: 37.5% of B, at least Rs 150
        "project_pause_minutes": 60,
        "auto_grant_projection_fraction": 0.70,
        "auto_grant_high_tries": 2,
    },
    "router": {
        "lambda": 2.0,
        "give_up_penalty_inr": 30.0,
        "max_depth": 6,
        "free_tries": 3,
        "haiku_floor": 2,
        "haiku_floor_max_with_progress": 3,
        "drop_back_tries": 2,
        "unusable_waives_floor_after": 2,
        "min_samples_for_learned": 10,
        "repeat_decay": 0.7,               # p shrinks by this for each earlier failure of the same tier
    },
    "tokens": {
        "retry_overhead_in": 7500,    # error output + short report (plan 5.1: +5K..+10K)
        "expected_out": 3000,
        "max_prompt_tokens": 60000,   # keeps Haiku under its 100K price band
        "context_tokens": 14000,      # v3.2: code sent up front (the relevant files only); the model asks for more when it needs it
        "groq_prompt_tokens": 3500,   # free tier is rate limited (~8K tokens/min): send only the relevant files
        "groq_request_limit": 7500,   # prompt + answer above this is rejected with HTTP 413: skip the free model instead
        "reasoning_out_multiplier": 1.0,
    },
    # v4: the engineer (Claude with tools). Bounds for ONE run; Sonnet runs first, Opus once if Sonnet does not finish.
    "agent": {
        "max_steps": 45,
        "max_seconds": 1500,
        # Rupees ONE run may spend, per model. Haiku runs cost a few rupees, so it always goes first.
        "max_inr_per_run": {"haiku": 40.0, "sonnet": 120.0, "opus": 160.0},
        # A run that reaches its limit is CONTINUED (same model, its edits kept) up to this many times before a stronger model.
        "continuations": 2,
        # Spending on one case before the owner is asked "Keep going?" (never a silent stop). Each "Keep going" adds this again.
        "max_inr_per_case": 250.0,
        # Whole code base in the first message up to this many characters (Haiku's price rises above 100K prompt tokens).
        "full_code_chars": {"haiku": 120000, "sonnet": 450000, "opus": 450000},     # v6: Haiku starts small (map + tools)
        "max_check_runs": 5,
        "max_page_visits": 5,
        "max_web_searches": 6,
        "effort": {"haiku": "high", "sonnet": "high", "opus": "high"},
    },
    "ask_timeout_minutes": 30,
    "sandbox": {
        "mode": "docker",             # docker | remote | github (v6: GitHub Actions) | local_unsafe (tests only)
        "github_timeout_seconds": 900,
        "github_poll_seconds": 6,
        "timeout_seconds": 120,
        "install_timeout_seconds": 240,
        "memory": "1g",
        "cpus": "1",
        "pids": 256,
        "image_python": "fixengine-sandbox-python:1",
        "image_node": "fixengine-sandbox-node:1",     # also used for static HTML/CSS/JS sites
        "image_java": "fixengine-sandbox-java:1",
        "image_browser": "fixengine-sandbox-browser:1",   # optional: headless-browser journeys for static sites (see sandbox/Dockerfile.browser)
        "journey_timeout_seconds": 150,
        # v3.1 live investigator (a real browser on the client's PUBLIC site; sandbox server only, one job at a time)
        "investigate_memory": "1g",           # fits a 2 GB server when nothing else runs at the same time
        "investigate_cpus": "1",
        "investigate_pids": 512,
        "investigate_timeout_seconds": 90,
        "investigate_network": "fx-investigate",   # docker network with private ranges blocked (DEPLOY.md); "bridge" works too
        "max_repo_mb": 50,
        "max_repo_files": 6000,
    },
}

# Placeholder success probabilities (plan 6.8). GUESSES, replaced by measured values from the ledger.
PLACEHOLDER_P: dict = {
    "easy":   {"groq": 0.35, "haiku": 0.85, "haiku_diag": 0.90, "sonnet": 0.95, "opus": 0.98},
    "medium": {"groq": 0.15, "haiku": 0.55, "haiku_diag": 0.65, "sonnet": 0.80, "opus": 0.90},
    "hard":   {"groq": 0.03, "haiku": 0.20, "haiku_diag": 0.35, "sonnet": 0.50, "opus": 0.70},
}


def _merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(__file__).resolve().parent.parent / "fixengine_config.json"
    for raw in (path.read_text(encoding="utf-8") if path.is_file() else "", os.getenv("FIXENGINE_CONFIG_JSON", "")):
        if raw.strip():
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, dict):
                _merge(cfg, data)
    # Model ids without a code change (a retired model is then a config change, not a deploy).
    for tier in TIERS:
        value = os.getenv(f"FIXENGINE_MODEL_{tier.upper()}", "").strip()
        if value:
            cfg["models"][tier] = value
    # Simple env shortcuts for the numbers the founders change most.
    for env, path_ in (("FIXENGINE_BUDGET_INR", ("budget", "b_inr")),
                       ("FIXENGINE_CREDITS_INR", ("budget", "credits_inr")),
                       ("FIXENGINE_PER_BUG_CAP_INR", ("caps", "per_bug_cost_inr")),
                       ("FIXENGINE_USD_INR", ("usd_inr",))):
        value = os.getenv(env, "").strip()
        if value:
            try:
                number = float(value)
            except ValueError:
                continue
            target = cfg
            for part in path_[:-1]:
                target = target[part]
            target[path_[-1]] = number
    b = cfg["budget"]
    if b.get("spike_hour_min_inr") is None:
        b["spike_hour_min_inr"] = round(0.10 * float(b["b_inr"]), 2)
    if b.get("project_hour_cap_inr") is None:
        b["project_hour_cap_inr"] = round(max(150.0, 0.375 * float(b["b_inr"])), 2)
    return cfg


def estimate_cost_inr(cfg: dict, tier: str, tokens_in: int, tokens_out: int, cache_read: int = 0) -> float:
    price = cfg["prices_usd_per_m"][tier]
    if tokens_in > 100_000 and "in_over_100k" in price:
        rate_in, rate_out = price["in_over_100k"], price.get("out_over_100k", price["out"])
    else:
        rate_in, rate_out = price["in"], price["out"]
    fresh = max(0, tokens_in - cache_read)
    usd = (fresh * rate_in + cache_read * price.get("cache_read", rate_in) + tokens_out * rate_out) / 1_000_000
    return round(usd * float(cfg["usd_inr"]), 4)
