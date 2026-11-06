"""Check the AI providers WITHOUT running any bug:  python -m fixengine.provider_check

What it answers, per tier (Low effort, Normal, High, Extra):
  * which provider the engine would really use (Groq, Anthropic or OpenRouter) and with which model id;
  * is the API key accepted (a free GET request, no tokens);
  * does the provider know the model id (the provider's own model list);
  * for the FREE tier only: does one tiny real request work (this is where provider rules such as OpenRouter's
    "free endpoints that may publish prompts" privacy setting show up as an HTTP 404).

Cost: nothing. Paid tiers are never sent a prompt unless you pass --include-paid, and even then it is one tiny request each
(at most 200 output tokens, a few paise). Keys are read from the environment / .env only and are never printed; every line is redacted.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import adapters as fx_adapters
from . import config as fx_config

PING_SYSTEM = "Reply with the JSON object {\"ok\": true} and nothing else."


def _get(client, url: str, headers: dict):
    """(status, json or None, error text). Never raises."""
    try:
        resp = client.get(url, headers=headers, timeout=20) if client is not None else __import__("httpx").get(url, headers=headers, timeout=20)
    except Exception as exc:                       # network down, DNS, TLS ...
        return None, None, f"{type(exc).__name__}"
    try:
        data = resp.json()
    except Exception:
        data = None
    return resp.status_code, data, ""


def _model_ids(data) -> set[str]:
    rows = data.get("data") if isinstance(data, dict) else None
    return {str(r.get("id")) for r in (rows or []) if isinstance(r, dict) and r.get("id")}


def check_auth_and_model(adapter, client=None) -> tuple[bool, str]:
    """Key accepted? Model id known? Uses list/key endpoints only, so no tokens are spent."""
    provider, model = adapter.provider, adapter.model
    if provider == "openrouter":
        # The model catalogue is public, so a wrong slug is detectable even before the key works.
        s, models, err = _get(client, "https://openrouter.ai/api/v1/models", {})
        known = _model_ids(models) if s == 200 else set()
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        ks, kdata, kerr = _get(client, "https://openrouter.ai/api/v1/auth/key", {"Authorization": "Bearer " + key})
        if ks is None:
            return False, f"could not reach OpenRouter ({kerr})"
        if ks in (401, 403):
            return False, f"OpenRouter rejected the key (HTTP {ks}): revoked, mistyped or from another service"
        if ks != 200:
            return False, f"OpenRouter key check returned HTTP {ks}"
        info = (kdata or {}).get("data") or {}
        credit = ""
        if isinstance(info.get("limit_remaining"), (int, float)):
            credit = f", remaining credit ${info['limit_remaining']:.2f}"
        if known and model not in known:
            return False, f"key OK{credit}, but the model id '{model}' is not in OpenRouter's catalogue"
        return True, f"key OK{credit}; model id found" if known else f"key OK{credit}; model list unavailable"
    if provider == "groq":
        key = os.getenv("GROQ_API_KEY", "").strip()
        s, data, err = _get(client, "https://api.groq.com/openai/v1/models", {"Authorization": "Bearer " + key})
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        s, data, err = _get(client, "https://api.anthropic.com/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        return False, f"unknown provider '{provider}'"
    if s is None:
        return False, f"could not reach {provider} ({err})"
    if s in (401, 403):
        return False, f"{provider} rejected the key (HTTP {s}): revoked, mistyped or from another service"
    if s != 200:
        return False, f"{provider} key check returned HTTP {s}"
    known = _model_ids(data)
    if known and model not in known:
        return False, f"key OK, but the model id '{model}' is not in {provider}'s model list"
    return True, "key OK; model id found" if known else "key OK; model list unavailable"


def ping_model(adapter) -> tuple[bool, str]:
    """One tiny real request through the same adapter code the engine uses (same URL, headers, body shape and error handling)."""
    try:
        res = adapter.call(PING_SYSTEM, [fx_adapters.Block("ping")], 200)
    except fx_adapters.AdapterError as exc:
        return False, exc.summary()
    return True, f"answered ({res.tokens_in} in / {res.tokens_out} out tokens, model {res.model or adapter.model})"


def run(cfg: dict | None = None, *, client=None, include_paid: bool = False, out=print) -> int:
    cfg = cfg or fx_config.load()
    os.environ.pop("FIXENGINE_DRY_RUN", None)          # a check that cannot reach the provider would prove nothing
    adapters = fx_adapters.build_adapters(cfg)
    if client is not None:
        for adapter in adapters.values():
            adapter._client = client
    failures = 0
    out(f"FIXENGINE_PROVIDER={os.getenv('FIXENGINE_PROVIDER', 'auto')}   (keys are never printed)")
    for tier in fx_config.TIERS:
        adapter = adapters[tier]
        name = fx_config.USER_MODE_NAMES[tier]
        if not adapter.configured():
            out(f"[{tier:6s}] {name:10s} NOT CONFIGURED   route: {adapter.describe()}   (no API key for this route)")
            continue
        ok, detail = check_auth_and_model(adapter, client)
        out(f"[{tier:6s}] {name:10s} {'OK  ' if ok else 'FAIL'}  route: {adapter.describe()}   {fx_adapters.redact(detail)}")
        failures += 0 if ok else 1
        if ok and (tier == "groq" or include_paid):
            pok, pdetail = ping_model(adapter)
            out(f"           request test: {'OK  ' if pok else 'FAIL'}  {fx_adapters.redact(pdetail)}")
            failures += 0 if pok else 1
        elif ok:
            out("           request test: skipped (paid tier; pass --include-paid to send one tiny request)")
    out("All checked routes work." if not failures else f"{failures} check(s) FAILED: fix these before any benchmark or paid run.")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-paid", action="store_true", help="also send one tiny request to each configured paid tier (a few paise)")
    return run(include_paid=ap.parse_args(argv).include_paid)


if __name__ == "__main__":
    sys.exit(main())
