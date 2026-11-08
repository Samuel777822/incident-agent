"""Live lists of the AI models each provider serves today, used to double-check a model swap before it is pushed.

  openrouter  https://openrouter.ai/api/v1/models            public, no key (also covers OpenAI, Anthropic and Google ids)
  anthropic   https://api.anthropic.com/v1/models            ANTHROPIC_API_KEY (ours)
  groq        https://api.groq.com/openai/v1/models          GROQ_API_KEY (ours)
  openai      https://api.openai.com/v1/models               OPENAI_API_KEY if set, otherwise derived from OpenRouter
  google      generativelanguage.googleapis.com/v1beta/models GEMINI_API_KEY if set, otherwise derived from OpenRouter

Each list is cached for six hours. When a list cannot be read the answer is None ("unknown"), never an empty list, so a
missing network never makes a working model look retired.
"""
from __future__ import annotations

import os
import time

import httpx

CACHE_SECONDS = 6 * 3600
_CACHE: dict[str, tuple[float, list[dict] | None]] = {}


def _get(url: str, headers: dict | None = None) -> dict | None:
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=6)) as client:
            resp = client.get(url, headers=headers or {})
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _is_zero(value) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def _or_entry(m: dict) -> dict:
    """One OpenRouter model: id, age, whether it costs nothing, context size and what it accepts/produces."""
    pricing = m.get("pricing") or {}
    arch = m.get("architecture") or {}
    mid = str(m.get("id"))
    free = mid.endswith(":free") or (_is_zero(pricing.get("prompt")) and _is_zero(pricing.get("completion")) and "prompt" in pricing)
    return {"id": mid, "created": int(m.get("created") or 0), "free": bool(free), "context": int(m.get("context_length") or 0),
            "modality": str(arch.get("modality") or ""), "name": str(m.get("name") or "")[:80]}


def _fetch(provider: str) -> list[dict] | None:
    if provider == "openrouter":
        data = _get("https://openrouter.ai/api/v1/models")
        return [_or_entry(m) for m in (data or {}).get("data", [])] if data else None
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        data = _get("https://api.anthropic.com/v1/models?limit=1000",
                    {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        if data:
            return [{"id": str(m.get("id")), "created": _ts(m.get("created_at"))} for m in data.get("data", [])]
    if provider == "groq" and os.getenv("GROQ_API_KEY"):
        data = _get("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]})
        if data:
            return [{"id": str(m.get("id")), "created": int(m.get("created") or 0)} for m in data.get("data", []) if m.get("active", True)]
        return None
    if provider == "openai" and os.getenv("OPENAI_API_KEY"):
        data = _get("https://api.openai.com/v1/models", {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
        if data:
            return [{"id": str(m.get("id")), "created": int(m.get("created") or 0)} for m in data.get("data", [])]
    if provider == "google" and os.getenv("GEMINI_API_KEY"):
        data = _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&key=" + os.environ["GEMINI_API_KEY"])
        if data:
            return [{"id": str(m.get("name", "")).removeprefix("models/"), "created": 0} for m in data.get("models", [])]
    vendor = {"openai": "openai/", "anthropic": "anthropic/", "google": "google/"}.get(provider)
    if vendor:                                # fall back to OpenRouter's public list, which mirrors these vendors' current models
        listing = models("openrouter")
        if listing is None:
            return None
        out = [{"id": m["id"][len(vendor):].split(":")[0], "created": m["created"]} for m in listing if m["id"].startswith(vendor)]
        if provider == "anthropic":           # OpenRouter writes claude-sonnet-5.5 where the API writes claude-sonnet-5-5
            out += [{"id": m["id"].replace(".", "-"), "created": m["created"]} for m in out]
        return out or None
    return None


def _ts(value) -> int:
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


def models(provider: str) -> list[dict] | None:
    """[{id, created}] the provider serves now, or None when that cannot be known right now."""
    now = time.time()
    hit = _CACHE.get(provider)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    if os.getenv("MODEL_CATALOG_OFFLINE") == "1":
        return None
    listing = _fetch(provider)
    _CACHE[provider] = (now, listing)
    return listing


def ids(provider: str) -> set[str] | None:
    listing = models(provider)
    return None if listing is None else {m["id"] for m in listing}


def set_for_tests(provider: str, listing: list[dict] | None) -> None:
    _CACHE[provider] = (time.time(), listing)


def clear() -> None:
    _CACHE.clear()
