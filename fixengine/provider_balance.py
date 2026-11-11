"""The real numbers, straight from OpenRouter, for the admin page.

11 Nov 2026: the admin page said Rs 363 spent and Rs 136 of credit left while OpenRouter had charged $4.96 and the account was
empty (HTTP 402). Our own ledger is an estimate (runs that failed half way were once saved at Rs 0, and other keys on the same
OpenRouter account are not ours), so the page now shows what OpenRouter itself says:

* GET /api/v1/key      what THIS key (Agent Daemon's) has spent: in total, today, this week and this month
* GET /api/v1/credits  what the whole account bought and used, so: the balance that is really left

Read with the key from OPENROUTER_API_KEY (never shown or logged). Cached for 2 minutes. Any failure gives None for that part,
and the page falls back to our own estimate and says so.
"""
from __future__ import annotations

import os
import time

import httpx

BASE = "https://openrouter.ai/api/v1"
CACHE_SECONDS = 120
_cache: dict = {"at": 0.0, "value": None}


def _get(client: httpx.Client, path: str, key: str) -> dict | None:
    try:
        resp = client.get(BASE + path, headers={"Authorization": "Bearer " + key})
        if resp.status_code != 200:
            return None
        data = resp.json().get("data")
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def _num(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def openrouter_live(*, client: httpx.Client | None = None, fresh: bool = False) -> dict | None:
    """{key_usage_usd, key_month_usd, key_limit_remaining_usd, credits_usd, account_used_usd, balance_usd} (each may be None),
    or None when there is no key or OpenRouter could not be asked at all."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    if not fresh and _cache["value"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(8, connect=5))
    try:
        mine = _get(client, "/key", key)
        account = _get(client, "/credits", key)
    finally:
        if own:
            client.close()
    if mine is None and account is None:
        return None
    mine, account = mine or {}, account or {}
    credits, used = _num(account.get("total_credits")), _num(account.get("total_usage"))
    value = {"key_usage_usd": _num(mine.get("usage")), "key_month_usd": _num(mine.get("usage_monthly")),
             "key_limit_remaining_usd": _num(mine.get("limit_remaining")),
             "credits_usd": credits, "account_used_usd": used,
             "balance_usd": round(credits - used, 4) if credits is not None and used is not None else None}
    _cache.update(at=time.time(), value=value)
    return value
