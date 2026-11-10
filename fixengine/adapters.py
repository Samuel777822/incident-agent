"""Model adapters (plan 4.5): one small adapter per provider, same interface.

Input is a system prompt plus text blocks. Output is text and token usage. Adapters never get tools:
models cannot run commands, touch Git or read other files. Our code applies the patch.
Keys come from environment variables only (ANTHROPIC_API_KEY, GROQ_API_KEY), never from code or prompts.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from . import config as fx_config

log = logging.getLogger("fixengine.adapters")


# ---- secret hygiene: nothing that reaches a log, the ledger, an email or a report may contain a key ---------------------------
_SECRET_ENV_NAMES = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "SESSION_SECRET",
                     "FIXENGINE_SANDBOX_SECRET", "RAZORPAY_KEY_SECRET", "BREVO_API_KEY", "RESEND_API_KEY")
_SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9]{6,}"), re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{6,}"), re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{10,}"), re.compile(r"github_pat_[A-Za-z0-9_]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{6,}"),
    re.compile(r"(?i)\b(x-api-key|authorization|api[_-]?key)\s*[:=]\s*\S+"),
)


def redact(text) -> str:
    """Remove anything that looks like an API key, a bearer token or an authorization header, plus the exact values of our own secrets."""
    out = str(text or "")
    for name in _SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if len(value) >= 8:
            out = out.replace(value, "[redacted]")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


def dry_run_enabled() -> bool:
    """FIXENGINE_DRY_RUN=1 makes every adapter refuse to call any provider, whatever keys are in the environment or in .env."""
    return os.getenv("FIXENGINE_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")


class AdapterError(RuntimeError):
    """kind: auth | rate_limit | outage | timeout | bad_request | config | not_configured | dry_run

    `config` is a persistent setup problem (unknown model id, a provider privacy rule that blocks the model): retrying will not help.
    Every error carries the provider, the model and the HTTP status so a fault is never just "system_fault"; the message is redacted."""

    RETRYABLE = frozenset({"rate_limit", "outage", "timeout"})

    def __init__(self, kind: str, message: str, *, provider: str = "", model: str = "", status: int | None = None):
        super().__init__(redact(message))
        self.kind = kind
        self.provider = provider
        self.model = model
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE

    def summary(self) -> str:
        """One safe line for the ledger and the logs: who failed, with what, why, and whether trying again can help."""
        parts = [f"provider={self.provider or '?'}", f"model={self.model or '?'}"]
        if self.status is not None:
            parts.append(f"http={self.status}")
        parts += [f"kind={self.kind}", f"retryable={'yes' if self.retryable else 'no'}", "origin=provider"]
        return (" ".join(parts) + " | " + str(self))[:420]


_CONFIG_WORDS = ("no endpoints", "data policy", "guardrail", "not a valid model", "model not found", "model_not_found",
                 "does not exist", "decommission", "no longer available", "not found")


def _detail(resp) -> str:
    """The provider's own explanation of a failure (their JSON error message), redacted and shortened. Never the request."""
    msg = ""
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or "")
        elif isinstance(err, str):
            msg = err
        elif isinstance(data, dict):
            msg = str(data.get("message") or "")
    except Exception:
        msg = ""
    if not msg:
        msg = str(getattr(resp, "text", "") or "")
    return " ".join(redact(msg).split())[:240]


def _client_error(provider: str, model: str, code: int, detail: str, hint: str = "") -> "AdapterError":
    """HTTP 400/404/413: a persistent `config` problem when the model or routing is the cause, otherwise a bad_request."""
    low = detail.lower()
    kind = "config" if code == 404 or any(w in low for w in _CONFIG_WORDS) else "bad_request"
    text = f"{provider} rejected the request (HTTP {code})" + (f": {detail}" if detail else "") + (f" {hint}" if hint else "")
    return AdapterError(kind, text, provider=provider, model=model, status=code)


@dataclass
class Block:
    text: str
    cache: bool = False          # mark the big, stable repo block for prompt caching


@dataclass
class ModelResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    model: str = ""
    finish: str = ""


class BaseAdapter:
    tier = ""
    provider = ""
    dry_run = False

    def __init__(self, tier: str, cfg: dict):
        self.tier = tier
        self.cfg = cfg
        self.model = cfg["models"][tier]

    def configured(self) -> bool:
        return True

    def describe(self) -> str:
        return f"{self.provider or 'unknown'} / {self.model}"

    def call(self, system: str, blocks: list[Block], max_tokens: int) -> ModelResult:  # pragma: no cover
        raise NotImplementedError


def _sleep_backoff(attempt: int, sleep: Callable[[float], None]) -> None:
    sleep(min(20.0, 1.5 * (2 ** attempt)))


class AnthropicAdapter(BaseAdapter):
    URL = "https://api.anthropic.com/v1/messages"
    provider = "anthropic"

    def __init__(self, tier, cfg, *, client: httpx.Client | None = None, sleep=time.sleep):
        super().__init__(tier, cfg)
        self._client = client
        self._sleep = sleep

    def _key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "").strip()

    def configured(self) -> bool:
        return bool(self._key())

    def call(self, system, blocks, max_tokens):
        key = self._key()
        if not key:
            raise AdapterError("not_configured", "ANTHROPIC_API_KEY is not set", provider="anthropic", model=self.model)
        content = []
        for b in blocks:
            item = {"type": "text", "text": b.text}
            if b.cache:
                item["cache_control"] = {"type": "ephemeral"}
            content.append(item)
        body = {"model": self.model, "max_tokens": int(max_tokens),
                "system": [{"type": "text", "text": system}],
                "messages": [{"role": "user", "content": content}]}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        last, last_status = "unknown error", None
        for attempt in range(4):
            try:
                if self._client is not None:
                    resp = self._client.post(self.URL, headers=headers, json=body, timeout=90)
                else:
                    resp = httpx.post(self.URL, headers=headers, json=body, timeout=90)
            except httpx.TimeoutException:
                last = "request timed out"
                _sleep_backoff(attempt, self._sleep)
                continue
            except httpx.HTTPError as exc:
                last = f"network error ({type(exc).__name__})"
                _sleep_backoff(attempt, self._sleep)
                continue
            code = resp.status_code
            if code == 200:
                data = resp.json()
                text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
                u = data.get("usage") or {}
                read = int(u.get("cache_read_input_tokens") or 0)
                created = int(u.get("cache_creation_input_tokens") or 0)
                fresh = int(u.get("input_tokens") or 0)
                return ModelResult(text, tokens_in=fresh + int(created * 1.25) + read, tokens_out=int(u.get("output_tokens") or 0),
                                   cache_read=read, model=self.model, finish=str(data.get("stop_reason") or ""))
            if code in (401, 403):
                raise AdapterError("auth", f"Anthropic rejected the API key (HTTP {code})", provider="anthropic", model=self.model, status=code)
            if code in (400, 404, 413):
                raise _client_error("anthropic", self.model, code, _detail(resp))
            if code == 429 or code >= 500:
                last = f"HTTP {code}"
                last_status = code
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    self._sleep(min(30, int(retry_after)))
                else:
                    _sleep_backoff(attempt, self._sleep)
                continue
            raise AdapterError("bad_request", f"Unexpected HTTP {code}: {_detail(resp)}", provider="anthropic", model=self.model, status=code)
        raise AdapterError("rate_limit" if "429" in last else "outage", f"Anthropic unavailable after retries ({last})",
                           provider="anthropic", model=self.model, status=last_status)


class GroqAdapter(BaseAdapter):
    URL = "https://api.groq.com/openai/v1/chat/completions"
    FALLBACK = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
    provider = "groq"

    def __init__(self, tier, cfg, *, client=None, sleep=time.sleep):
        super().__init__(tier, cfg)
        self._client = client
        self._sleep = sleep

    def _key(self) -> str:
        return os.getenv("GROQ_API_KEY", "").strip()

    def configured(self) -> bool:
        return bool(self._key())

    def _post(self, body):
        headers = {"Authorization": "Bearer " + self._key(), "Content-Type": "application/json"}
        if self._client is not None:
            return self._client.post(self.URL, headers=headers, json=body, timeout=60)
        return httpx.post(self.URL, headers=headers, json=body, timeout=60)

    def call(self, system, blocks, max_tokens):
        if not self._key():
            raise AdapterError("not_configured", "GROQ_API_KEY is not set", provider="groq", model=self.model)
        user = "\n\n".join(b.text for b in blocks)
        body = {"model": self.model, "temperature": 0.1, "max_tokens": int(max_tokens),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}, "reasoning_effort": "low"}
        last, last_status = "unknown", None
        for attempt in range(3):
            try:
                resp = self._post(body)
            except httpx.TimeoutException:
                last = "timeout"; _sleep_backoff(attempt, self._sleep); continue
            except httpx.HTTPError as exc:
                last = type(exc).__name__; _sleep_backoff(attempt, self._sleep); continue
            code = resp.status_code
            if code == 200:
                data = resp.json()
                u = data.get("usage") or {}
                choice = (data.get("choices") or [{}])[0]
                return ModelResult((choice.get("message") or {}).get("content") or "", int(u.get("prompt_tokens") or 0),
                                   int(u.get("completion_tokens") or 0), 0, body["model"], str(choice.get("finish_reason") or ""))
            if code in (401, 403):
                raise AdapterError("auth", f"Groq rejected the API key (HTTP {code})", provider="groq", model=body["model"], status=code)
            if code == 400 and "reasoning" in resp.text.lower() and "reasoning_effort" in body:
                body.pop("reasoning_effort"); continue
            if code == 413:
                # "Request too large" for the free tier's per-minute token limit. Waiting or retrying the same request can never
                # help: say so, so the engine moves on to the next model straight away.
                raise AdapterError("too_large", f"Groq: the request is too large for the free tier (HTTP 413){': ' + _detail(resp) if _detail(resp) else ''}",
                                   provider="groq", model=body["model"], status=413)
            if code == 429:
                if body["model"] != self.FALLBACK and attempt == 0:
                    body["model"] = self.FALLBACK; continue
                last, last_status = f"HTTP {code}", code; _sleep_backoff(attempt, self._sleep); continue
            if code >= 500:
                last, last_status = f"HTTP {code}", code; _sleep_backoff(attempt, self._sleep); continue
            raise _client_error("groq", body["model"], code, _detail(resp))
        raise AdapterError("rate_limit" if "429" in last else "outage", f"Groq unavailable after retries ({last})",
                           provider="groq", model=body["model"], status=last_status)


class OpenRouterAdapter(BaseAdapter):
    """One key, many models: Claude (Haiku/Sonnet/Opus) and free open models through OpenRouter's OpenAI-compatible API.

    Used when the direct provider key is missing, or for every tier when FIXENGINE_PROVIDER=openrouter. The key is read from the
    OPENROUTER_API_KEY environment variable only; it is never stored, logged or put in an error message.
    Model ids can be overridden with FIXENGINE_OPENROUTER_MODEL_<TIER> (for example FIXENGINE_OPENROUTER_MODEL_OPUS).
    """
    URL = "https://openrouter.ai/api/v1/chat/completions"
    provider = "openrouter"
    PRIVACY_HINT = ("Fix: openrouter.ai/settings/privacy ('free endpoints that may publish prompts'), or pick a paid model. "
                    "Do not enable that setting for real customer code.")

    def __init__(self, tier, cfg, *, client=None, sleep=time.sleep):
        super().__init__(tier, cfg)
        self.model = (os.getenv(f"FIXENGINE_OPENROUTER_MODEL_{tier.upper()}", "").strip()
                      or (cfg.get("openrouter_models") or {}).get(tier) or self.model)
        self._client = client
        self._sleep = sleep

    def _key(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "").strip()

    def configured(self) -> bool:
        return bool(self._key())

    def _post(self, body):
        headers = {"Authorization": "Bearer " + self._key(), "Content-Type": "application/json",
                   "HTTP-Referer": os.getenv("FIXENGINE_SITE_URL", "https://agent-daemon.invalid"), "X-Title": "Agent Daemon fix engine"}
        if self._client is not None:
            return self._client.post(self.URL, headers=headers, json=body, timeout=90)
        return httpx.post(self.URL, headers=headers, json=body, timeout=90)

    def call(self, system, blocks, max_tokens):
        if not self._key():
            raise AdapterError("not_configured", "OPENROUTER_API_KEY is not set", provider="openrouter", model=self.model)
        parts = []
        for b in blocks:
            part = {"type": "text", "text": b.text}
            if b.cache and self.model.startswith("anthropic/"):        # prompt caching, supported for Claude models
                part["cache_control"] = {"type": "ephemeral"}
            parts.append(part)
        body = {"model": self.model, "temperature": 0.1, "max_tokens": int(max_tokens),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": parts}],
                "usage": {"include": True}}
        if self.tier == "groq":                                          # the free tier uses an open reasoning model
            body["reasoning"] = {"effort": "low"}
        last, last_status = "unknown", None
        for attempt in range(4):
            try:
                resp = self._post(body)
            except httpx.TimeoutException:
                last = "timeout"; _sleep_backoff(attempt, self._sleep); continue
            except httpx.HTTPError as exc:
                last = type(exc).__name__; _sleep_backoff(attempt, self._sleep); continue
            code = resp.status_code
            if code == 200:
                data = resp.json()
                if data.get("error") and not data.get("choices"):          # OpenRouter can answer 200 with an error body
                    inner = data["error"].get("code") if isinstance(data["error"], dict) else None
                    if inner in (401, 403):
                        raise AdapterError("auth", "OpenRouter rejected the API key", provider="openrouter", model=self.model, status=inner)
                    if inner == 402:
                        raise AdapterError("auth", "OpenRouter says the account has no credit left (HTTP 402)",
                                           provider="openrouter", model=self.model, status=402)
                    last, last_status = f"HTTP {inner or 'error'}", (inner if isinstance(inner, int) else None)
                    _sleep_backoff(attempt, self._sleep); continue
                u = data.get("usage") or {}
                choice = (data.get("choices") or [{}])[0]
                cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
                return ModelResult(str((choice.get("message") or {}).get("content") or ""), int(u.get("prompt_tokens") or 0),
                                   int(u.get("completion_tokens") or 0), cached, self.model, str(choice.get("finish_reason") or ""))
            if code in (401, 403):
                raise AdapterError("auth", f"OpenRouter rejected the API key (HTTP {code})", provider="openrouter", model=self.model, status=code)
            if code == 402:
                raise AdapterError("auth", "OpenRouter says the account has no credit left (HTTP 402)",
                                   provider="openrouter", model=self.model, status=402)
            if code == 400 and "reasoning" in resp.text.lower() and "reasoning" in body:
                body.pop("reasoning"); continue
            if code in (400, 404, 413):
                detail = _detail(resp)
                privacy = code == 404 and any(w in detail.lower() for w in ("data policy", "guardrail", "publish"))
                raise _client_error("openrouter", self.model, code, detail, self.PRIVACY_HINT if privacy else "")
            if code == 429 or code >= 500:
                last, last_status = f"HTTP {code}", code
                retry_after = resp.headers.get("retry-after")
                if retry_after and str(retry_after).isdigit():
                    self._sleep(min(30, int(retry_after)))
                else:
                    _sleep_backoff(attempt, self._sleep)
                continue
            raise AdapterError("bad_request", f"Unexpected HTTP {code} from OpenRouter: {_detail(resp)}",
                               provider="openrouter", model=self.model, status=code)
        raise AdapterError("rate_limit" if "429" in last else "outage", f"OpenRouter unavailable after retries ({last})",
                           provider="openrouter", model=self.model, status=last_status)


class DryRunAdapter(BaseAdapter):
    """Used when FIXENGINE_DRY_RUN=1. It never opens a network connection and never reads an API key, so a dry run cannot spend money
    or leak code, whatever is in the environment or in .env. It reports itself as configured so the router still picks a tier and the
    sandbox baseline still runs: the run stops exactly where the model call would have happened."""
    provider = "dry-run"
    dry_run = True

    def configured(self) -> bool:
        return True

    def call(self, system, blocks, max_tokens):
        raise AdapterError("dry_run", "dry run: model calls are disabled", provider="dry-run", model=self.model)


class FakeAdapter(BaseAdapter):
    """Deterministic stand-in for tests and the router simulation. `script` maps (call number) -> text or raises."""

    def __init__(self, tier, cfg, script: Callable[[int, str, list], str | ModelResult] | list | None = None, *,
                 tokens=(8000, 1200)):
        super().__init__(tier, cfg)
        self.script, self.tokens, self.calls = script, tokens, 0
        self.seen_prompts: list[str] = []

    def call(self, system, blocks, max_tokens):
        self.calls += 1
        self.seen_prompts.append("\n".join(b.text for b in blocks))
        script = self.script
        if callable(script):
            out = script(self.calls, system, blocks)
        elif isinstance(script, list):
            out = script[min(self.calls - 1, len(script) - 1)]
        else:
            out = '{"cannot_determine": true, "diagnosis": "fake adapter has no script", "edits": []}'
        if isinstance(out, Exception):
            raise out
        if isinstance(out, ModelResult):
            return out
        return ModelResult(str(out), self.tokens[0], self.tokens[1], 0, self.model, "stop")


def build_adapters(cfg: dict | None = None) -> dict[str, BaseAdapter]:
    """Pick, per tier, the direct provider (Groq for the free tier, Anthropic for the Claude tiers) when its key is set, otherwise
    OpenRouter when OPENROUTER_API_KEY is set. FIXENGINE_PROVIDER=openrouter forces OpenRouter for every tier, and
    FIXENGINE_PROVIDER=direct never uses it."""
    cfg = cfg or fx_config.load()
    if dry_run_enabled():
        return {tier: DryRunAdapter(tier, cfg) for tier in fx_config.TIERS}
    mode = os.getenv("FIXENGINE_PROVIDER", "auto").strip().lower()
    have_router = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    out: dict[str, BaseAdapter] = {}
    for tier in fx_config.TIERS:
        direct = GroqAdapter(tier, cfg) if tier == "groq" else AnthropicAdapter(tier, cfg)
        if mode == "openrouter" or (mode != "direct" and have_router and not direct.configured()):
            out[tier] = OpenRouterAdapter(tier, cfg)
        else:
            out[tier] = direct
    return out
