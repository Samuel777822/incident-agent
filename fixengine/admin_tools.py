"""Admin controls and the automatic 'user hit a limit' analysis (plan 9.4 / 10.3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    store.log_admin_action("pause" if paused else "resume", detail={"tier": tier, "by": admin_email})


def sell_pack(user_id: str, kind: str, admin_email: str = "") -> dict:
    """Credit a Rs 100 pack after payment is confirmed: 5 High or 3 Extra tries (plan 5.7)."""
    tier, tries = {"high": ("sonnet", 5), "extra": ("opus", 3)}[kind]
    store.add_grant(user_id, tier, tries, "pack", f"pack confirmed by {admin_email or 'system'}")
    store.log_admin_action("pack_sold", user_id, {"tier": tier, "tries": tries})
    return {"tier": tier, "tries": tries}


def _recent_periods(n: int = 6) -> list[str]:
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def spending_history(n: int = 6) -> list[dict]:
    """Tracked AI spend per month (newest first). Read-only view of the fx_attempts ledger."""
    rows = []
    for period in _recent_periods(n):
        r = store._all("""SELECT COALESCE(SUM(cost_inr),0) AS spend,
                          COALESCE(SUM(CASE WHEN result<>'system_fault' THEN 1 ELSE 0 END),0) AS tries,
                          COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) AS passes
                          FROM fx_attempts WHERE period=?""", (period,))
        row = r[0] if r else {"spend": 0, "tries": 0, "passes": 0}
        rows.append({"period": period, "spend": round(float(row["spend"] or 0), 2), "tries": int(row["tries"] or 0),
                     "passes": int(row["passes"] or 0)})
    return rows


def users_overview(guard: Guard, period: str) -> list[dict]:
    """Per customer this month: real attempts (faults excluded), successful fixes, tracked spend and quota use per paid mode."""
    rows = store._all("""SELECT user_id, COALESCE(SUM(cost_inr),0) AS spend,
                         COALESCE(SUM(CASE WHEN result<>'system_fault' THEN 1 ELSE 0 END),0) AS tries,
                         COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) AS passes
                         FROM fx_attempts WHERE period=? GROUP BY user_id ORDER BY spend DESC""", (period,))
    ceiling = float(guard.cfg["caps"]["user_month_ceiling_inr"])
    out = []
    for r in rows:
        quotas = {}
        for tier in fx_config.PAID_TIERS:
            q = guard.quota(r["user_id"], tier, period)
            quotas[tier] = {"used": q["used"], "total": q["total"]}
        out.append({"user_id": r["user_id"], "spend": round(float(r["spend"] or 0), 2), "tries": int(r["tries"] or 0),
                    "passes": int(r["passes"] or 0), "quotas": quotas, "ceiling": ceiling})
    return out


def protection_status(guard: Guard) -> dict:
    """Everything the 'Spending protection' panel needs: rupee thresholds, current level, spike-breaker numbers."""
    cfgb = guard.cfg["budget"]
    b = guard.budget()
    credits = float(cfgb["credits_inr"])
    now = datetime.now(timezone.utc)
    spend = guard.month_spend()
    last_hour = store.spend_inr(since=(now - timedelta(hours=1)).isoformat(timespec="microseconds"))
    hours = max(1.0, (now - now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600)
    return {"levels": [round(b * float(f), 2) for f in cfgb["levels"]], "fractions": [float(f) for f in cfgb["levels"]],
            "reserve_floor": round(credits * float(cfgb["reserve_floor_fraction_of_credits"]), 2),
            "reserve_fraction": float(cfgb["reserve_floor_fraction_of_credits"]), "credits": credits, "budget": b,
            "spike_multiple": float(cfgb["spike_hour_multiple"]), "spike_min": float(cfgb["spike_hour_min_inr"]),
            "last_hour": round(last_hour, 2), "normal_per_hour": round(spend / hours, 2),
            "spike_paused": store.get_flag("spike_paused") == "1",
            "auto_grant_fraction": float(cfgb["auto_grant_projection_fraction"]), "auto_grant_high": int(cfgb["auto_grant_high_tries"])}


def _enrich_holds(guard: Guard, holds: list[dict]) -> list[dict]:
    """Add what the admin needs to decide: the customer's use of that mode and what one more try typically costs."""
    import json
    from .router import RouterInput, _est_cost
    for h in holds:
        try:
            h["analysis"] = json.loads(h.get("analysis_json") or "{}")
        except ValueError:
            h["analysis"] = {}
        try:
            q = guard.quota(h["user_id"], h["tier"])
            h["quota"] = {"used": q["used"], "total": q["total"], "left": q["left"]}
        except Exception:
            h["quota"] = {}
        try:
            h["try_cost"] = round(_est_cost(guard.cfg, h["tier"], RouterInput(repo_tokens=10000, total_tries=1)), 2)
        except Exception:
            h["try_cost"] = 0.0
    return holds


def dashboard(guard: Guard | None = None) -> dict:
    guard = guard or Guard()
    period = store.current_period()
    burn = burn_rate(guard)
    import os
    return {"period": period, "level": guard.level(), "level_name": guard.level_name(), "burn": burn,
            "by_tier": store.spend_by_tier(period), "by_user": store.month_spend_by_user(period),
            "users": users_overview(guard, period), "history": spending_history(6), "protection": protection_status(guard),
            "paused": sorted(store.paused_tiers()), "holds": _enrich_holds(guard, store.list_holds("held")),
            "actions": store.list_admin_actions(15), "cfg": guard.cfg,
            "provider": (os.getenv("FIXENGINE_PROVIDER", "auto") or "auto"),
            "credits_left_estimate": round(float(guard.cfg["budget"]["credits_inr"]) - burn["spend_so_far"], 2)}
