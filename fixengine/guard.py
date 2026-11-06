"""Quota and budget guard (plan section 9). Every model call passes here first.

Layers: prepaid provider credits, provider-side limit, our own global monthly budget B, per-user quotas
and rupee ceiling, per-bug caps (router.py), per-user rate limits, and a spike breaker.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import config as fx_config
from . import notify, store

log = logging.getLogger("fixengine.guard")
LEVEL_NAMES = ["normal", "50% of budget", "80%: free bonus grants stopped", "90%: Extra paused",
               "100%: High paused", "reserve floor: Low effort only"]
FREE_SOURCES = ("bonus", "admin")


@dataclass
class GuardResult:
    ok: bool
    code: str = "ok"            # ok | exhausted | paused | busy | ceiling | rate | cooldown | budget
    pack_try: bool = False
    message: str = ""


class Guard:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or fx_config.load()

    # ---- global budget / kill switch --------------------------------------------------------------
    def month_spend(self) -> float:
        return store.spend_inr(period=store.current_period())

    def budget(self) -> float:
        return float(self.cfg["budget"]["b_inr"])

    def level(self, spend: float | None = None) -> int:
        spend = self.month_spend() if spend is None else spend
        b = self.budget()
        cfgb = self.cfg["budget"]
        floor = float(cfgb["credits_inr"]) * float(cfgb["reserve_floor_fraction_of_credits"])
        if spend >= floor:
            return 5
        fractions = cfgb["levels"]            # [0.5, 0.8, 0.9, 1.0]
        level = 0
        for i, f in enumerate(fractions):
            if spend >= b * float(f):
                level = i + 1
        return level

    def level_name(self, level: int | None = None) -> str:
        return LEVEL_NAMES[self.level() if level is None else level]

    def check_alerts(self) -> int:
        """Email admins once per level per month; run the spike breaker; return the level."""
        spend = self.month_spend()
        level = self.level(spend)
        period = store.current_period()
        for lvl in range(1, level + 1):
            key = f"alert:{period}:{lvl}"
            if not store.get_flag(key):
                store.set_flag(key, "1")
                notify.admin_level(lvl, LEVEL_NAMES[lvl], spend, self.budget())
                store.log_admin_action("budget_level", detail={"level": lvl, "spend": round(spend, 2)})
        self._spike_breaker(spend)
        return level

    def _spike_breaker(self, spend: float) -> None:
        cfgb = self.cfg["budget"]
        now = datetime.now(timezone.utc)
        hour = store.spend_inr(since=(now - timedelta(hours=1)).isoformat(timespec="microseconds"))
        if hour < float(cfgb["spike_hour_min_inr"]) or store.get_flag("spike_paused") == "1":
            return
        hours_elapsed = max(1.0, (now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600)
        normal = spend / hours_elapsed
        if hour > normal * float(cfgb["spike_hour_multiple"]):
            for tier in fx_config.PAID_TIERS:
                store.set_flag(f"pause_{tier}", "1")
            store.set_flag("spike_paused", "1")
            store.log_admin_action("spike_breaker", detail={"last_hour": round(hour, 2), "normal_per_hour": round(normal, 2)})
            notify.admin_spike(hour, normal)

    def tier_paused_by_budget(self, tier: str, *, pack: bool, level: int | None = None) -> bool:
        """Kill-switch table from plan 9.3. Paid packs survive levels 3 and 4 but not the reserve floor."""
        level = self.level() if level is None else level
        if tier == "groq":
            return False
        if level >= 5:
            return True
        if pack:
            return False
        if tier == "opus" and level >= 3:
            return True
        if tier == "sonnet" and level >= 4:
            return True
        return False

    # ---- quotas ------------------------------------------------------------------------------------
    def quota(self, user_id: str, tier: str, period: str | None = None) -> dict:
        period = period or store.current_period()
        base = int(self.cfg["quotas"].get(tier, 0))
        free_extra = sum(store.grants_total(user_id, tier, s, period) for s in FREE_SOURCES)
        pack_total = store.grants_total(user_id, tier, "pack", period) + store.grants_total(user_id, tier, "plan", period)
        used = store.tier_used(user_id, tier, period)
        pack_used = store.pack_tries_used(user_id, tier, period)
        free_pool = base + free_extra
        free_used = max(0, used - pack_used)
        level = self.level()
        free_left = max(0, free_pool - free_used)
        if self.tier_paused_by_budget(tier, pack=False, level=level):
            free_left_effective = 0
        else:
            free_left_effective = free_left
        pack_left = max(0, pack_total - pack_used)
        if self.tier_paused_by_budget(tier, pack=True, level=level):
            pack_left = 0
        return {"tier": tier, "label": fx_config.USER_MODE_NAMES[tier], "base": base, "free_extra": free_extra,
                "free_pool": free_pool, "used": used, "free_left": free_left, "free_left_effective": free_left_effective,
                "pack_total": pack_total, "pack_used": pack_used, "pack_left": pack_left,
                "left": free_left_effective + pack_left, "total": free_pool + pack_total,
                "warn_at": int(self.cfg["warn_at"].get(tier, 0)), "every_use": bool(self.cfg["warn_every_use"].get(tier))}

    def user_ceiling_reached(self, user_id: str) -> bool:
        return store.spend_inr(period=store.current_period(), user_id=user_id) >= float(self.cfg["caps"]["user_month_ceiling_inr"])

    def quota_left_tuple(self, user_id: str) -> tuple[tuple, tuple]:
        """(left, total) for haiku, sonnet, opus, with the kill switch, admin pauses and user ceiling applied."""
        paused = store.paused_tiers()
        ceiling = self.user_ceiling_reached(user_id)
        left, total = [], []
        for tier in fx_config.PAID_TIERS:
            q = self.quota(user_id, tier)
            n = 0 if (tier in paused or ceiling) else q["left"]
            left.append(n)
            total.append(max(1, q["total"]))
        return tuple(left), tuple(total)

    def groq_available(self, user_id: str) -> bool:
        if "groq" in store.paused_tiers():
            return False
        return store.groq_used_today(user_id) < int(self.cfg["groq_daily_cap"])

    # ---- rate limits -------------------------------------------------------------------------------------
    def rate_check(self, user_id: str) -> GuardResult | None:
        caps = self.cfg["caps"]
        if store.tries_last_hour(user_id) >= int(caps["tries_per_hour_per_user"]):
            return GuardResult(False, "rate", message="Too many tries this hour. The agent will continue later.")
        n = int(caps["cooldown_after_failures"])
        if n and store.recent_failed_bugs(user_id, int(caps["cooldown_minutes"])) >= n:
            return GuardResult(False, "cooldown", message="Cooling down after repeated failures.")
        return None

    def intake_allowed(self, user_id: str) -> bool:
        return store.new_bugs_last_hour(user_id) < int(self.cfg["caps"]["new_bugs_per_hour_per_user"])

    # ---- the gate every model call passes ------------------------------------------------------------------
    def check(self, user_id: str, tier: str) -> GuardResult:
        if tier == "groq":
            if not self.groq_available(user_id):
                return GuardResult(False, "exhausted", message="Daily fair-use cap for Low effort reached.")
            return GuardResult(True)
        if tier in store.paused_tiers():
            return GuardResult(False, "paused", message=f"{fx_config.USER_MODE_NAMES[tier]} mode is paused.")
        rate = self.rate_check(user_id)
        if rate:
            return rate
        if self.user_ceiling_reached(user_id):
            return GuardResult(False, "ceiling", message=notify_text_busy())
        q = self.quota(user_id, tier)
        level = self.level()
        if q["free_left_effective"] > 0:
            return GuardResult(True, pack_try=False)
        if q["pack_left"] > 0:
            return GuardResult(True, pack_try=True)
        if q["free_left"] > 0 and self.tier_paused_by_budget(tier, pack=False, level=level):
            return GuardResult(False, "busy", message=notify_text_busy())
        return GuardResult(False, "exhausted", message=f"All {q['label']} tries for this month are used.")

    def needs_warning(self, user_id: str, tier: str) -> tuple[bool, int, int]:
        """Warn before a try at the plan's warning points (plan 8.2). Returns (warn, used, total)."""
        if tier in ("groq",):
            return False, 0, 0
        q = self.quota(user_id, tier)
        used = q["used"]
        if q["every_use"]:
            return True, used, q["total"]
        if q["warn_at"] and used == q["warn_at"]:
            key = f"warned:{user_id}:{store.current_period()}:{tier}"
            if not store.get_flag(key):
                return True, used, q["total"]
        return False, used, q["total"]

    def mark_warned(self, user_id: str, tier: str) -> None:
        store.set_flag(f"warned:{user_id}:{store.current_period()}:{tier}", "1")

    # ---- snapshot for the usage panel ------------------------------------------------------------------------
    def usage_panel(self, user_id: str) -> list[dict]:
        panel = []
        paused = store.paused_tiers()
        for tier in fx_config.PAID_TIERS:
            q = self.quota(user_id, tier)
            q["paused"] = tier in paused or self.tier_paused_by_budget(tier, pack=True)
            panel.append(q)
        groq_used, cap = store.groq_used_today(user_id), int(self.cfg["groq_daily_cap"])
        panel.insert(0, {"tier": "groq", "label": "Low effort", "used": groq_used, "total": cap, "left": max(0, cap - groq_used),
                         "paused": "groq" in paused, "daily": True, "base": cap, "pack_left": 0})
        return panel


def notify_text_busy() -> str:
    return ("Deep-analysis capacity is busy right now, so extra tries aren't available at the moment. "
            "You can add tries for Rs 100, and those are reserved for you.")


def days_in_month(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return calendar.monthrange(now.year, now.month)[1]
