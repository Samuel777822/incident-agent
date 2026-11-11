"""Quota and budget guard (plan section 9). Every model call passes here first.

Layers: prepaid provider credits, provider-side limit, our own global monthly budget B, per-user quotas
and rupee ceiling, per-bug caps (router.py). The guard NEVER pauses a mode or a project by itself: budget levels, spikes,
busy customers and fast-spending projects only email the admins, who decide.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import config as fx_config
from . import notify, store

log = logging.getLogger("fixengine.guard")
LEVEL_NAMES = ["normal", "50% of budget", "80% of budget", "90% of budget", "100% of budget", "reserve floor of the credits"]
FREE_SOURCES = ("bonus", "admin")


@dataclass
class GuardResult:
    ok: bool
    code: str = "ok"            # ok | exhausted | paused | busy | ceiling | rate | cooldown | budget
    pack_try: bool = False
    message: str = ""
    wait_seconds: int = 0


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
        """Email admins once per level per month, and when spending spikes. NOTHING is paused here: only an admin pauses a mode
        (Admin, AI spending, Mode switches) or a project (its owner, or an admin)."""
        spend = self.month_spend()
        level = self.level(spend)
        period = store.current_period()
        for lvl in range(1, level + 1):
            key = f"alert:{period}:{lvl}"
            if not store.get_flag(key):
                store.set_flag(key, "1")
                notify.admin_level(lvl, LEVEL_NAMES[lvl], spend, self.budget())
                store.log_admin_action("budget_level", detail={"level": lvl, "spend": round(spend, 2)})
        self._release_old_automatic_pause()
        self._spike_alert(spend)
        return level

    @staticmethod
    def _release_old_automatic_pause() -> None:
        """Older versions paused every paid mode by themselves on a spike. Undo that once, so only pauses made by an admin remain."""
        if store.get_flag("spike_paused") != "1":
            return
        for tier in fx_config.PAID_TIERS:
            store.set_flag(f"pause_{tier}", "0")
        store.set_flag("spike_paused", "0")
        store.log_admin_action("spike_pause_released", detail={"why": "automatic pausing was removed"})
        notify._to_admins("Automatic pause removed: all modes are running again",
                          "An older version had paused Normal, High and Extra by itself after a spending spike. The agent no longer "
                          "pauses anything on its own, so they are running again. To pause a mode yourself: Admin, AI spending, "
                          "Mode switches.", "fix_pause")

    @staticmethod
    def _hour_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d%H")

    def project_paused(self, project_id: str) -> str:
        """Always '': the agent never pauses a project by itself. Above `project_hour_cap_inr` of AI spend in the last hour the
        admins get ONE email per project per hour with the numbers and how to pause it if they decide to."""
        if not project_id:
            return ""
        cap = float(self.cfg["budget"].get("project_hour_cap_inr", 150.0) or 0)
        if cap <= 0:
            return ""
        now = datetime.now(timezone.utc)
        hour = store.spend_inr(project_id=project_id, since=(now - timedelta(hours=1)).isoformat(timespec="microseconds"))
        if hour >= cap:
            key = f"project_spend_mail:{project_id}:{self._hour_key()}"
            if not store.get_flag(key):
                store.set_flag(key, "1")
                store.log_admin_action("project_spend_alert", detail={"project_id": project_id, "last_hour": round(hour, 2)})
                notify._to_admins("A project is spending fast (nothing was paused)",
                                  f"Project {project_id} spent Rs {hour:.2f} on AI in the last hour (alert level Rs {cap:.0f}). "
                                  "The agent keeps working: it never pauses anything by itself.\n"
                                  "If you want it to stop: pause a mode for everyone in Admin, AI spending, Mode switches, or ask the "
                                  "owner to press Pause agent on the project.", "fix_spend_alert")
        return ""

    def _spike_alert(self, spend: float) -> None:
        """A sudden jump in spending: email the admins (once an hour). Never pauses anything."""
        cfgb = self.cfg["budget"]
        now = datetime.now(timezone.utc)
        since = (now - timedelta(hours=1)).isoformat(timespec="microseconds")
        hour = store.spend_inr(since=since)
        if hour < float(cfgb["spike_hour_min_inr"]):
            return
        hours_elapsed = max(1.0, (now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600)
        normal = spend / hours_elapsed
        if hour <= normal * float(cfgb["spike_hour_multiple"]):
            return
        key = f"spike_mail:{self._hour_key()}"
        if store.get_flag(key):
            return
        store.set_flag(key, "1")
        top = [(r["project_id"], round(float(r["spend"] or 0), 2)) for r in store.spend_by_project(since)[:5]]
        store.log_admin_action("spike_alert", detail={"last_hour": round(hour, 2), "normal_per_hour": round(normal, 2), "top": top})
        notify.admin_spike(hour, normal, top)

    def tier_paused_by_budget(self, tier: str, *, pack: bool, level: int | None = None) -> bool:
        """Always False: budget levels only email the admins (check_alerts). A mode stops only when an admin pauses it."""
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
        """Always False: a customer above the monthly level keeps being served. The admins get one email per customer per month."""
        spent = store.spend_inr(period=store.current_period(), user_id=user_id)
        ceiling = float(self.cfg["caps"]["user_month_ceiling_inr"])
        if spent >= ceiling:
            key = f"ceiling_mail:{user_id}:{store.current_period()}"
            if not store.get_flag(key):
                store.set_flag(key, "1")
                store.log_admin_action("user_ceiling_alert", user_id, {"spent": round(spent, 2), "ceiling": ceiling})
                notify._to_admins("A customer passed the monthly AI spending level (nothing was paused)",
                                  f"Customer {user_id} has used Rs {spent:.2f} of AI this month (alert level Rs {ceiling:.0f}). The agent "
                                  "keeps working for them. If you want to stop it, pause a mode in Admin, AI spending.", "fix_spend_alert")
        return False

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
        """Never blocks. Many tries in an hour, or several failed cases in a row, email the admins once an hour so a person decides."""
        caps = self.cfg["caps"]
        hour = store.tries_last_hour(user_id)
        n = int(caps["cooldown_after_failures"])
        failed = store.recent_failed_bugs(user_id, int(caps["cooldown_minutes"])) if n else 0
        if hour >= int(caps["tries_per_hour_per_user"]) or (n and failed >= n):
            key = f"rate_mail:{user_id}:{self._hour_key()}"
            if not store.get_flag(key):
                store.set_flag(key, "1")
                notify._to_admins("A customer's agent is very busy (nothing was paused)",
                                  f"Customer {user_id}: {hour} AI tries in the last hour and {failed} failed cases recently. The agent keeps "
                                  "working. If this looks like a loop, pause a mode in Admin, AI spending.", "fix_spend_alert")
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
