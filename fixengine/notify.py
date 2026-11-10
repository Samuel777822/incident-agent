"""User warnings and admin alerts (plan 4.10 / 8 / 10.2). Email first, in-app second (the usage page)."""
from __future__ import annotations

import logging
import os

import notifications
import portal_db
from . import config as fx_config

log = logging.getLogger("fixengine.notify")


def _base() -> str:
    return os.getenv("PORTAL_BASE_URL", "").rstrip("/")


def _to_user(user_id: str, subject: str, body: str, kind: str) -> None:
    try:
        address = portal_db.get_user_email(user_id)
        if address:
            notifications.notify_customer(address, subject, body, kind)
    except Exception:
        log.exception("Could not queue a user notification")


def _to_admins(subject: str, body: str, kind: str = "fix_admin") -> None:
    try:
        notifications.notify_admins(subject, body, kind)
    except Exception:
        log.exception("Could not queue an admin notification")


def mode_name(tier: str) -> str:
    return fx_config.USER_MODE_NAMES.get(tier, tier)


def user_warning(user_id: str, tier: str, used: int, total: int) -> str:
    name = mode_name(tier)
    if tier == "opus":
        text = (f"This would be Extra try {used + 1} of {total} for this month. Want us to keep going, "
                "choose differently, or send this bug to human review?")
    else:
        text = (f"You've used {used} of your {total} {name}-mode tries this month. How would you like to continue? "
                "Let us pick the best option, choose a mode yourself, or send this bug to human review.")
    _to_user(user_id, f"Your agent needs a decision ({name} mode)",
             text + f"\n\nAnswer here: {_base()}/usage\nIf you do not answer in a while, Auto mode will continue with the cheapest sensible option.",
             "fix_warning")
    return text


def user_exhausted(user_id: str, tier: str) -> str:
    text = ("You've used all your High and Extra tries for this month, as listed in your plan. You can add more for "
            "Rs 100: 5 High tries or 3 Extra tries. This buys attempts, not a guaranteed fix.")
    _to_user(user_id, "Monthly tries used up", text + f"\n\n{_base()}/usage", "fix_exhausted")
    return text


def user_busy(user_id: str) -> str:
    text = ("Deep-analysis capacity is busy right now, so extra tries aren't available at the moment. "
            "You can add tries for Rs 100, and those are reserved for you.")
    _to_user(user_id, "Extra tries are busy", text + f"\n\n{_base()}/usage", "fix_busy")
    return text


def user_review_ready(user_id: str, project_name: str, incident_id: str, why: str) -> None:
    _to_user(user_id, f"A bug in {project_name} needs a human",
             f"The agent stopped on this bug: {why}\n\nA review report is ready with everything it tried and why each "
             f"attempt failed. Open it: {_base()}/usage\n\nIncident: {incident_id}", "fix_review")


def user_pr_opened(user_id: str, project_name: str, pr_url: str, verified: str) -> None:
    _to_user(user_id, f"Fix proposed for {project_name}",
             f"The agent opened a pull request: {pr_url}\n\nVerification: {verified}\nNothing was pushed to your main branch.",
             "fix_pr")


def user_fix_pushed(user_id: str, project_name: str, branch: str, verified: str) -> None:
    _to_user(user_id, f"Fixed and pushed: {project_name}",
             f"The agent fixed a bug and pushed the fix to your {branch} branch after it passed the sandbox and your GitHub tests.\n\n"
             f"Verification: {verified}\nOpen {_base()}/dashboard to see what changed.", "fix_pushed")


def user_question(user_id: str, project_name: str, project_id: str, incident_id: str, question: str) -> None:
    _to_user(user_id, f"One question about {project_name}",
             f"The agent is working on your report and needs one thing only you know:\n\n{question}\n\n"
             f"Answer it here (one line is enough): {_base()}/projects/{project_id}/incidents/{incident_id}\n"
             "The agent continues by itself as soon as you reply.", "fix_question")


def user_live_verified(user_id: str, project_name: str, text: str) -> None:
    _to_user(user_id, f"Verified on your live site: {project_name}", text + f"\n\nOpen {_base()}/dashboard for the details.", "fix_verified")


def user_live_still_failing(user_id: str, project_name: str, text: str) -> None:
    _to_user(user_id, f"Still failing on your live site: {project_name}", text + f"\n\nOpen {_base()}/dashboard for the details.", "fix_still_failing")


def user_fix_reverted(user_id: str, project_name: str, text: str) -> None:
    _to_user(user_id, f"Fix undone on {project_name}", text + f"\n\nOpen {_base()}/dashboard for the details.", "fix_reverted")


def user_needs_review(user_id: str, project_name: str, pr_url: str, why: str) -> None:
    _to_user(user_id, f"Needs your review: {project_name}",
             f"The agent could not get a fix through your GitHub tests, so it opened a pull request for you: {pr_url}\n\n{why}\n"
             "Nothing was pushed to your main branch.", "fix_review")


def admin_level(level: int, name: str, spend: float, budget: float) -> None:
    _to_admins(f"Auto-fix budget alert: {name}",
               f"Month spend is Rs {spend:.2f} of the global budget B = Rs {budget:.2f} (level {level}: {name}).\n"
               f"Open {_base()}/admin to review.", "fix_budget")


def admin_hold(user_email: str, tier: str, analysis: dict) -> None:
    _to_admins(f"{user_email} asked for more {mode_name(tier)} tries",
               "Held for your review.\n" + "\n".join(f"- {k}: {v}" for k, v in analysis.items())
               + f"\n\nApprove or deny on {_base()}/admin", "fix_hold")


def admin_grant(user_email: str, tier: str, tries: int, analysis: dict) -> None:
    _to_admins(f"Auto-granted +{tries} {mode_name(tier)} tries to {user_email}",
               "Granted automatically because projected spend was low.\n"
               + "\n".join(f"- {k}: {v}" for k, v in analysis.items()), "fix_grant")


def admin_spike(last_hour: float, normal: float) -> None:
    _to_admins("Auto-fix spend spike: paid models paused",
               f"Spend in the last hour is Rs {last_hour:.2f} against about Rs {normal:.2f} per hour normally. "
               f"Paid models were paused. Resume them on {_base()}/admin after checking the ledger.", "fix_spike")


def admin_low_credit(balance: float, threshold: float) -> None:
    _to_admins("Auto-fix credit balance is low",
               f"Estimated remaining credits: Rs {balance:.2f} (alert threshold Rs {threshold:.2f}). Top up in the provider console.",
               "fix_credit")
