"""Single source of truth for the paid plans (architecture plan v2, sections 1, 5.4, 5.6 and 5.7).

Every price, every piece of plan text and every amount check reads from here, so the pricing page,
the billing page, the terms, the chatbot and the payment validation cannot drift apart.
Rupee figures are whole rupees. Gateway amounts are paise (rupees * 100).
"""
from __future__ import annotations

import os


def _price(env_name: str, default: int) -> int:
    """Plan 10.3: prices can change without a code change. Set PLAN_PRICE_MONTHLY_INR / PLAN_PRICE_YEARLY_INR (whole rupees)."""
    raw = os.getenv(env_name, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


PLAN_PRICES = {"monthly": _price("PLAN_PRICE_MONTHLY_INR", 200),     # plan 1 and 5.6: Rs 200 a month,
               "yearly": _price("PLAN_PRICE_YEARLY_INR", 1500)}      # about Rs 1,500 a year
PLAN_DAYS = {"monthly": 30, "yearly": 365}
PLAN_LABELS = {"monthly": "Monthly", "yearly": "Yearly"}
PACK_PRICE = 100                                    # plan 5.7: Rs 100 = 5 High tries or 3 Extra tries
PACK_HIGH_TRIES, PACK_EXTRA_TRIES = 5, 3

# Projects: every plan includes one connected project. Each extra project costs a one-time PROJECT_SLOT_PRICE, and the
# slot stays on the account (delete a project and the slot is free for the next one). Fix-attempt quotas are per ACCOUNT,
# so more projects never multiply the AI cost (plan sections 11 and 15).
INCLUDED_PROJECTS = 1
PROJECT_SLOT_PRICE = _price("PROJECT_SLOT_PRICE_INR", 30)

# Everything a customer can pay for with the manual UPI flow. "days" > 0 means it grants plan access.
PRODUCTS = {
    "monthly": {"label": "Monthly plan", "rupees": PLAN_PRICES["monthly"], "days": 30},
    "yearly": {"label": "Yearly plan", "rupees": PLAN_PRICES["yearly"], "days": 365},
    "project_slot": {"label": "Extra project", "rupees": PROJECT_SLOT_PRICE, "days": 0},
    "pack_high": {"label": f"{PACK_HIGH_TRIES} High tries", "rupees": PACK_PRICE, "days": 0},
    "pack_extra": {"label": f"{PACK_EXTRA_TRIES} Extra tries", "rupees": PACK_PRICE, "days": 0},
}
ADDON_PRODUCTS = ("project_slot", "pack_high", "pack_extra")


def product_grant_text(product: str) -> str:
    """What the admin's 'I received' button grants, in words."""
    return {"monthly": "grant 30 days", "yearly": "grant 365 days", "project_slot": "add 1 project slot",
            "pack_high": f"add {PACK_HIGH_TRIES} High tries", "pack_extra": f"add {PACK_EXTRA_TRIES} Extra tries"}.get(product, "grant")

# Prices before the plan-v2 change. Accepted ONLY when an admin approves a payment that the customer
# submitted at the old price, so nobody who already paid is stranded. New payments never use these.
LEGACY_PRICES = {"monthly": 100, "yearly": 1000}

YEARLY_PER_MONTH = round(PLAN_PRICES["yearly"] / 12)                      # Rs 125 at the default price
YEARLY_SAVING = PLAN_PRICES["monthly"] * 12 - PLAN_PRICES["yearly"]       # Rs 900 against 12 monthly payments


def valid_amount(plan: str, amount) -> bool:
    """True when `amount` (whole rupees) is the current price of `plan` (a plan or an add-on product)."""
    try:
        return (PRODUCTS.get(plan) or {}).get("rupees") == int(amount)
    except (TypeError, ValueError):
        return False


def valid_amount_or_legacy(plan: str, amount) -> bool:
    try:
        return valid_amount(plan, amount) or LEGACY_PRICES.get(plan) == int(amount)
    except (TypeError, ValueError):
        return False


def quotas() -> dict:
    """Monthly tries per mode, read from the engine configuration (plan 5.4) so the text follows the config."""
    try:
        from fixengine import config as fx_config
        q = fx_config.load().get("quotas", {})
        return {"normal": int(q.get("haiku", 30)), "high": int(q.get("sonnet", 6)), "extra": int(q.get("opus", 3))}
    except Exception:
        return {"normal": 30, "high": 6, "extra": 3}


def quota_sentence() -> str:
    q = quotas()
    return (f"{q['normal']} Normal, {q['high']} High and {q['extra']} Extra fix attempts every month, "
            "plus Low effort attempts on a fair-use basis")


def quota_lines() -> list[tuple[str, str, str]]:
    """[(mode, amount, what it is)] for plan cards: one line per mode, so the pack reads '30 Normal / 6 High / 3 Extra'."""
    q = quotas()
    return [("Normal", f"{q['normal']} tries / month", "everyday fixes, where most bugs get solved"),
            ("High", f"{q['high']} tries / month", "deeper analysis when Normal is not enough"),
            ("Extra", f"{q['extra']} tries / month", "maximum effort for the hardest bugs"),
            ("Low effort", "fair use, daily cap", "a free first look at every bug")]


def projects_sentence() -> str:
    return (f"{INCLUDED_PROJECTS} project included. Each extra project is a one-time ₹{PROJECT_SLOT_PRICE}; "
            "the monthly tries are shared by all your projects")


def quota_fine_print() -> str:
    return ("Quotas reset every month and do not roll over. You are buying attempts to fix a bug, not a guaranteed fix. "
            f"Need more High or Extra attempts? A ₹{PACK_PRICE} pack adds {PACK_HIGH_TRIES} High or {PACK_EXTRA_TRIES} Extra attempts.")
