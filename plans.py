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


PLAN_PRICES = {"monthly": _price("PLAN_PRICE_MONTHLY_INR", 200),     # Basic: Rs 200 a month
               "yearly": _price("PLAN_PRICE_YEARLY_INR", 1500),      # Basic for a year
               "pro": _price("PLAN_PRICE_PRO_INR", 500)}             # v6: Pro, Rs 500 a month
PLAN_DAYS = {"monthly": 30, "yearly": 365, "pro": 30}
PLAN_LABELS = {"monthly": "Basic", "yearly": "Basic (yearly)", "pro": "Pro"}
PLAN_OF_PRODUCT = {"monthly": "basic", "yearly": "basic", "pro": "pro"}

# ---- v6 (13 Nov 2026): usage bars instead of tries -------------------------------------------------------------------------
# A bar is rupees of AI per calendar month, shown to the customer as a percentage. The Engineer is Claude Haiku, the Lead engineer
# Claude Sonnet. Bars are 59% of the price, so even a customer who empties every bar leaves about 40% after OpenRouter's fee and the
# payment fee (see JOURNEY-AND-PLANS.md section 4). Nothing is ever paused automatically: an empty bar only stops new AI work for
# that customer until a top-up or the next month.
BARS = {"none": {"haiku": 0, "sonnet": 0},
        "trial": {"haiku": 15, "sonnet": 0},
        "basic": {"haiku": 118, "sonnet": 0},
        "pro": {"haiku": 230, "sonnet": 64}}
BAR_NAMES = {"haiku": "Engineer", "sonnet": "Lead engineer"}
SMALL_FIX_INR = {"haiku": 8, "sonnet": 9}          # what one typical small fix (Engineer) or one review (Lead) costs
TOPUP_PRICE = _price("TOPUP_PRICE_INR", 99)
TOPUP_INR = 58                                     # rupees of AI a Rs 99 top-up adds to one bar
TOPUP_TIERS = {"topup_engineer": "haiku", "topup_lead": "sonnet"}
# Value of tries granted before v6 (packs, admin grants), counted as bar rupees so nobody loses what they paid for.
LEGACY_TRY_INR = {"haiku": 0.9, "sonnet": 11.6, "opus": 19.3}


def user_plan(user_id: str) -> str:
    """'trial' | 'basic' | 'pro' | 'none' (no active access)."""
    try:
        import portal_db
        row = portal_db.get_subscription(user_id)
    except Exception:
        return "none"
    if not row:
        return "none"
    from datetime import datetime, timezone
    try:
        until = datetime.fromisoformat(str(row["active_until"]))
        until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        if until <= datetime.now(timezone.utc):
            return "none"
    except (TypeError, ValueError):
        return "none"
    if row.get("grant_type") == "trial":
        return "trial"
    return "pro" if row.get("plan") == "pro" else "basic"


def bar_sizes(plan: str) -> dict:
    return dict(BARS.get(plan, BARS["none"]))
PACK_PRICE = 100                                    # plan 5.7: Rs 100 = 5 High tries or 3 Extra tries
PACK_HIGH_TRIES, PACK_EXTRA_TRIES = 5, 3
PACK_NORMAL_PRICE = _price("PACK_NORMAL_PRICE_INR", 30)  # Rs 30 = 20 more Normal tries this month
PACK_NORMAL_TRIES = 20
PACK_TIERS = {"pack_normal": ("normal", "haiku", PACK_NORMAL_TRIES), "pack_high": ("high", "sonnet", PACK_HIGH_TRIES),
              "pack_extra": ("extra", "opus", PACK_EXTRA_TRIES)}      # product -> (kind, engine tier, tries)

# Projects: every plan includes one connected project. Each extra project costs a one-time PROJECT_SLOT_PRICE, and the
# slot stays on the account (delete a project and the slot is free for the next one). Fix-attempt quotas are per ACCOUNT,
# so more projects never multiply the AI cost (plan sections 11 and 15).
INCLUDED_PROJECTS = 1
PROJECT_SLOT_PRICE = _price("PROJECT_SLOT_PRICE_INR", 30)

# Everything a customer can pay for with the manual UPI flow. "days" > 0 means it grants plan access.
PRODUCTS = {
    "monthly": {"label": "Basic plan", "rupees": PLAN_PRICES["monthly"], "days": 30},
    "yearly": {"label": "Basic plan (yearly)", "rupees": PLAN_PRICES["yearly"], "days": 365},
    "pro": {"label": "Pro plan", "rupees": PLAN_PRICES["pro"], "days": 30},
    "project_slot": {"label": "Extra project", "rupees": PROJECT_SLOT_PRICE, "days": 0},
    "topup_engineer": {"label": "Engineer top-up", "rupees": TOPUP_PRICE, "days": 0},
    "topup_lead": {"label": "Lead engineer top-up", "rupees": TOPUP_PRICE, "days": 0},
}
ADDON_PRODUCTS = ("project_slot", "topup_engineer", "topup_lead")
# Packs sold before v6. Not for sale any more; a payment submitted for one before the change can still be approved.
LEGACY_PRODUCTS = {
    "pack_normal": {"label": f"{PACK_NORMAL_TRIES} Normal tries (old pack)", "rupees": PACK_NORMAL_PRICE, "days": 0},
    "pack_high": {"label": f"{PACK_HIGH_TRIES} High tries (old pack)", "rupees": PACK_PRICE, "days": 0},
    "pack_extra": {"label": f"{PACK_EXTRA_TRIES} Extra tries (old pack)", "rupees": PACK_PRICE, "days": 0},
}


def product_grant_text(product: str) -> str:
    """What the admin's 'I received' button grants, in words."""
    return {"monthly": "grant Basic for 30 days", "yearly": "grant Basic for 365 days", "pro": "grant Pro for 30 days",
            "project_slot": "add 1 project slot", "topup_engineer": f"add Rs {TOPUP_INR} to the Engineer bar",
            "topup_lead": f"add Rs {TOPUP_INR} to the Lead engineer bar",
            "pack_normal": "old pack: add its value to the Engineer bar", "pack_high": "old pack: add its value to the Lead bar",
            "pack_extra": "old pack: add its value to the Lead bar"}.get(product, "grant")

# Prices before the plan-v2 change. Accepted ONLY when an admin approves a payment that the customer
# submitted at the old price, so nobody who already paid is stranded. New payments never use these.
LEGACY_PRICES = {"monthly": 100, "yearly": 1000}

YEARLY_PER_MONTH = round(PLAN_PRICES["yearly"] / 12)                      # Rs 125 at the default price
YEARLY_SAVING = PLAN_PRICES["monthly"] * 12 - PLAN_PRICES["yearly"]       # Rs 900 against 12 monthly payments


def valid_amount(plan: str, amount) -> bool:
    """True when `amount` (whole rupees) is the current price of `plan` (a plan or an add-on product)."""
    try:
        return (PRODUCTS.get(plan) or LEGACY_PRODUCTS.get(plan) or {}).get("rupees") == int(amount)
    except (TypeError, ValueError):
        return False


def valid_amount_or_legacy(plan: str, amount) -> bool:
    try:
        return valid_amount(plan, amount) or LEGACY_PRICES.get(plan) == int(amount)
    except (TypeError, ValueError):
        return False


def quotas() -> dict:
    """Kept for older pages: the plan's bars in 'typical small fixes' (v6)."""
    return {"normal": BARS["basic"]["haiku"] // SMALL_FIX_INR["haiku"], "high": BARS["pro"]["sonnet"] // SMALL_FIX_INR["sonnet"],
            "extra": 0}


def plan_bar_lines(plan: str) -> list[tuple[str, str, str]]:
    """[(bar, amount, what it is)] for a plan card."""
    bars = BARS[plan]
    lines = [("Engineer", f"≈ {bars['haiku'] // SMALL_FIX_INR['haiku']} small fixes a month",
              "diagnoses every problem, then fixes it once you say yes")]
    if bars["sonnet"]:
        lines.append(("Lead engineer", f"≈ {bars['sonnet'] // SMALL_FIX_INR['sonnet']} reviews or rescues a month",
                      "checks medium fixes and guides the Engineer when it gets stuck, after asking you"))
    return lines


def quota_sentence() -> str:
    return (f"Basic: an Engineer bar of about {BARS['basic']['haiku'] // SMALL_FIX_INR['haiku']} small fixes a month. "
            f"Pro: about {BARS['pro']['haiku'] // SMALL_FIX_INR['haiku']} small fixes plus a Lead engineer bar")


def quota_lines() -> list[tuple[str, str, str]]:
    return plan_bar_lines("pro")


def projects_sentence() -> str:
    return (f"{INCLUDED_PROJECTS} project included. Each extra project is a one-time ₹{PROJECT_SLOT_PRICE}; "
            "your bars are shared by all your projects")


def topup_sentence() -> str:
    return (f"A ₹{TOPUP_PRICE} top-up adds about {TOPUP_INR // SMALL_FIX_INR['haiku']} small fixes to your Engineer bar "
            f"(or about {TOPUP_INR // SMALL_FIX_INR['sonnet']} reviews to the Lead engineer bar on Pro) for this month.")


def quota_fine_print() -> str:
    return ("Bars refill on the 1st of every month and do not roll over. You are paying for the engineer's time on your problems, "
            "not a guaranteed fix. " + topup_sentence())


# ---- One wording for every page (architecture page, usage, FAQ, help, chatbot, emails). Change it here, not per page. ----
BAR_DEFINITION = ("Your plan comes with usage bars, like a phone's data pack. The Engineer bar is used when the agent diagnoses and "
                  "fixes your problems; on Pro, the Lead engineer bar is used when it reviews a fix or guides the Engineer. A small fix "
                  "uses about 7% of the Basic Engineer bar. Checking your pushes is free and never uses a bar, and a technical fault "
                  "on our side is never charged.")
TRY_DEFINITION = BAR_DEFINITION
WHY_STRONGER = ("Every problem starts with the Engineer, which is fast and low-cost. On Pro, the Lead engineer (a stronger AI) checks "
                "medium fixes and, when the Engineer gets stuck, writes it exact instructions. It always asks you first and shows how "
                "much of your Lead bar it will use.")
FAILED_FIX = ("If a fix does not pass the checks, nothing is pushed to your repository. The Engineer tries again with the new error; "
              "on Pro the Lead engineer can step in. Very big jobs (a new feature, a whole page) are offered to the founders instead.")
HUMAN_NEEDED = ("When the cause is outside your code (a missing key on your host, a database or sign-in setting, a service that is "
                "down) the agent says so right away and gives you simple step-by-step instructions. It stops and asks for a person when "
                "it reaches the limit for one case or when more work is unlikely to help, and you get a report of everything it "
                "tried. You can also send any case to human review yourself.")
MODE_SUMMARY = ("First the Engineer diagnoses the problem and tells you what broke and why. Nothing is changed until you press "
                "Yes, fix it. Then it fixes, tests and proves the change before it reaches your branch.")
TRY_SHORT = "Your bars refill every month. Push checks are free."
