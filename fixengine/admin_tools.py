"""Admin controls and the automatic 'user hit a limit' analysis (plan 9.4 / 10.3)."""
from __future__ import annotations

from datetime import datetime, timezone

import portal_db
from . import config as fx_config
from . import notify, store
from .guard import Guard, days_in_month


def burn_rate(guard: Guard, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    spend = guard.month_spend()
    elapsed_days = max(1.0, (now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 86400)
    projected = spend / elapsed_days * days_in_month(now)
    return {"spend_so_far": round(spend, 2), "days_elapsed": round(elapsed_days, 2), "projected_month_end": round(projected, 2),
            "budget": guard.budget(), "projected_fraction": round(projected / guard.budget(), 3) if guard.budget() else 9.9}


def others_utilization(guard: Guard, user_id: str) -> float:
    """How much of their paid quotas the OTHER active users have used (0..1)."""
    rows = [r for r in store.month_spend_by_user() if r["user_id"] != user_id]
    if not rows:
        return 0.0
    used = total = 0
    for row in rows:
        for tier in fx_config.PAID_TIERS:
            q = guard.quota(row["user_id"], tier)
            used += q["used"]
            total += q["free_pool"] or 1
    return round(used / total, 3) if total else 0.0


def request_more_tries(user_id: str, tier: str, guard: Guard | None = None, now: datetime | None = None) -> dict:
    """The system's automatic analysis. Returns {"decision": "granted"|"held", "analysis": {...}}."""
    guard = guard or Guard()
    existing = store.open_hold(user_id, tier)
    if existing:
        return {"decision": "held", "analysis": {"note": "already waiting for admin review"}, "hold_id": existing["id"]}
    burn = burn_rate(guard, now)
    util = others_utilization(guard, user_id)
    level = guard.level()
    cfgb = guard.cfg["budget"]
    analysis = {**burn, "others_quota_utilization": util, "budget_level": level,
                "user_month_spend": round(store.spend_inr(period=store.current_period(), user_id=user_id), 2)}
    email = portal_db.get_user_email(user_id) or user_id
    low_use = util < 0.5
    cheap = burn["projected_fraction"] < float(cfgb["auto_grant_projection_fraction"])
    first_time = store.bonus_grants_count(user_id, tier) == 0
    analysis["auto_granted_before_this_month"] = not first_time
    if cheap and low_use and level < 2 and first_time and tier in fx_config.PAID_TIERS:
        tries = {"haiku": 10, "sonnet": int(cfgb["auto_grant_high_tries"]), "opus": 1}[tier]
        store.add_grant(user_id, tier, tries, "bonus", "auto-granted by burn-rate analysis")
        store.log_admin_action("auto_grant", user_id, {"tier": tier, "tries": tries, **analysis})
        notify.admin_grant(email, tier, tries, analysis)
        return {"decision": "granted", "tries": tries, "analysis": analysis}
    hold_id = store.create_hold(user_id, tier, 2, analysis)
    store.log_admin_action("hold", user_id, {"tier": tier, "hold_id": hold_id, **analysis})
    notify.admin_hold(email, tier, analysis)
    return {"decision": "held", "analysis": analysis, "hold_id": hold_id}


def approve_hold(hold_id: str, admin_email: str, tries: int | None = None) -> bool:
    hold = store.get_hold(hold_id)
    if not hold or hold["status"] != "held":
        return False
    tries = int(tries or hold["tries_requested"])
    if not store.resolve_hold(hold_id, "granted"):
        return False
    store.add_grant(hold["user_id"], hold["tier"], tries, "admin", f"approved by {admin_email}")
    store.log_admin_action("hold_approved", hold["user_id"], {"hold_id": hold_id, "tries": tries, "by": admin_email})
    return True


def deny_hold(hold_id: str, admin_email: str) -> bool:
    hold = store.get_hold(hold_id)
    if not hold or not store.resolve_hold(hold_id, "denied"):
        return False
    store.log_admin_action("hold_denied", hold["user_id"], {"hold_id": hold_id, "by": admin_email})
    return True


def pause_tier(tier: str, paused: bool, admin_email: str) -> None:
    if tier not in fx_config.TIERS:
        raise ValueError("unknown mode")
    store.set_flag(f"pause_{tier}", "1" if paused else "0")
    if not paused and store.get_flag("spike_paused") == "1" and not store.paused_tiers():
        store.set_flag("spike_paused", "0")
    store.log_admin_action("pause" if paused else "resume", detail={"tier": tier, "by": admin_email})


def sell_pack(user_id: str, kind: str, admin_email: str = "") -> dict:
    """Credit a Rs 100 pack after payment is confirmed: 5 High or 3 Extra tries (plan 5.7)."""
    tier, tries = {"high": ("sonnet", 5), "extra": ("opus", 3)}[kind]
    store.add_grant(user_id, tier, tries, "pack", f"pack confirmed by {admin_email or 'system'}")
    store.log_admin_action("pack_sold", user_id, {"tier": tier, "tries": tries})
    return {"tier": tier, "tries": tries}


def dashboard(guard: Guard | None = None) -> dict:
    guard = guard or Guard()
    period = store.current_period()
    burn = burn_rate(guard)
    return {"period": period, "level": guard.level(), "level_name": guard.level_name(), "burn": burn,
            "by_tier": store.spend_by_tier(period), "by_user": store.month_spend_by_user(period),
            "paused": sorted(store.paused_tiers()), "holds": store.list_holds("held"),
            "actions": store.list_admin_actions(15),
            "credits_left_estimate": round(float(guard.cfg["budget"]["credits_inr"]) - burn["spend_so_far"], 2)}
