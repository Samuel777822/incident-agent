"""OpenRouter route: one key for Claude and free models. Fake HTTP only; no network, no money, no real key."""
import json

import httpx
import pytest

from fixengine import adapters, config as fx_config

CFG = fx_config.load()
FAKE_KEY = "test-key-not-real"


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(text="{}", prompt=1000, completion=100, cached=0):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                                               "prompt_tokens_details": {"cached_tokens": cached}}})


def make(tier, handler, monkeypatch, sleeps=None):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    return adapters.OpenRouterAdapter(tier, CFG, client=client(handler), sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def test_request_shape_for_a_claude_tier_with_caching(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), (request.headers.get("authorization") or request.headers.get("Authorization")), json.loads(request.content)
        return ok('{"diagnosis": "x"}', prompt=9000, completion=400, cached=8000)
    a = make("haiku", handler, monkeypatch)
    res = a.call("system text", [adapters.Block("repo", cache=True), adapters.Block("error")], 2000)
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == "Bearer " + FAKE_KEY
    body = seen["body"]
    assert body["model"] == "anthropic/claude-haiku-5.5" and body["max_tokens"] == 2000 and body["usage"] == {"include": True}
    assert body["messages"][0] == {"role": "system", "content": "system text"}
    assert body["messages"][1]["content"][0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in body["messages"][1]["content"][1]
    assert "reasoning" not in body
    assert (res.tokens_in, res.tokens_out, res.cache_read, res.text) == (9000, 400, 8000, '{"diagnosis": "x"}')


def test_free_tier_uses_a_free_model_and_asks_for_low_reasoning(monkeypatch):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok()
    make("groq", handler, monkeypatch).call("s", [adapters.Block("x", cache=True)], 500)
    assert seen["body"]["model"].endswith(":free") and seen["body"]["reasoning"] == {"effort": "low"}
    assert "cache_control" not in json.dumps(seen["body"])           # caching is only requested for Claude models


def test_model_id_can_be_overridden_from_the_environment(monkeypatch):
    monkeypatch.setenv("FIXENGINE_OPENROUTER_MODEL_OPUS", "anthropic/claude-opus-5.5-custom")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    assert adapters.OpenRouterAdapter("opus", CFG).model == "anthropic/claude-opus-5.5-custom"


def test_not_configured_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    a = adapters.OpenRouterAdapter("haiku", CFG)
    assert not a.configured()
    with pytest.raises(adapters.AdapterError) as err:
        a.call("s", [adapters.Block("x")], 10)
    assert err.value.kind == "not_configured"


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (402, "auth"), (400, "bad_request"), (404, "config")])   # 404 = unknown model or a provider rule blocks it: persistent, so it pauses the tier
def test_error_statuses_map_to_kinds_and_never_leak_the_key(status, kind, monkeypatch):
    a = make("sonnet", lambda r: httpx.Response(status, text="nope"), monkeypatch)
    with pytest.raises(adapters.AdapterError) as err:
        a.call("s", [adapters.Block("x")], 10)
    assert err.value.kind == kind and FAKE_KEY not in str(err.value)


def test_rate_limit_is_retried_then_reported(monkeypatch):
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="slow down")
    a = make("groq", handler, monkeypatch, sleeps)
    with pytest.raises(adapters.AdapterError) as err:
        a.call("s", [adapters.Block("x")], 10)
    assert err.value.kind == "rate_limit" and len(calls) == 4 and len(sleeps) == 4


def test_a_429_followed_by_success_recovers(monkeypatch):
    answers = [httpx.Response(429, text="x"), ok("fine")]
    a = make("haiku", lambda r: answers.pop(0), monkeypatch)
    assert a.call("s", [adapters.Block("x")], 10).text == "fine"


def test_200_with_an_error_body_is_understood(monkeypatch):
    a = make("haiku", lambda r: httpx.Response(200, json={"error": {"code": 402, "message": "insufficient credits"}}), monkeypatch)
    with pytest.raises(adapters.AdapterError) as err:
        a.call("s", [adapters.Block("x")], 10)
    assert err.value.kind == "auth" and "credit" in str(err.value)


def test_reasoning_rejection_is_retried_without_it(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, text="reasoning not supported") if len(bodies) == 1 else ok("done")
    assert make("groq", handler, monkeypatch).call("s", [adapters.Block("x")], 10).text == "done"
    assert "reasoning" in bodies[0] and "reasoning" not in bodies[1]


# ---- which adapter serves which tier
def kinds(adapter_map):
    return {t: type(a).__name__ for t, a in adapter_map.items()}


def test_direct_keys_win_and_openrouter_fills_the_gaps(monkeypatch):
    monkeypatch.delenv("FIXENGINE_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "direct-anthropic-test")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    got = kinds(adapters.build_adapters(CFG))
    assert got == {"groq": "OpenRouterAdapter", "haiku": "AnthropicAdapter", "sonnet": "AnthropicAdapter", "opus": "AnthropicAdapter"}


def test_only_an_openrouter_key_routes_every_tier_through_it(monkeypatch):
    monkeypatch.delenv("FIXENGINE_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert set(kinds(adapters.build_adapters(CFG)).values()) == {"OpenRouterAdapter"}


def test_forcing_openrouter_ignores_direct_keys_and_direct_mode_ignores_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "direct-anthropic-test")
    monkeypatch.setenv("GROQ_API_KEY", "direct-groq-test")
    monkeypatch.setenv("FIXENGINE_PROVIDER", "openrouter")
    assert set(kinds(adapters.build_adapters(CFG)).values()) == {"OpenRouterAdapter"}
    monkeypatch.setenv("FIXENGINE_PROVIDER", "direct")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    got = kinds(adapters.build_adapters(CFG))
    assert got["haiku"] == "AnthropicAdapter" and not adapters.build_adapters(CFG)["haiku"].configured()


def test_no_keys_means_nothing_is_configured(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "FIXENGINE_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    assert not any(a.configured() for a in adapters.build_adapters(CFG).values())


def test_unavailable_model_is_replaced_from_live_catalogue_and_retried(monkeypatch):
    from fixengine import model_catalog
    model_catalog.clear()
    try:
        # 1. OpenRouter: :free variant removed from catalogue -> falls back to verified openai/gpt-oss-120b and retries
        model_catalog.set_for_tests("openrouter", [{"id": "openai/gpt-oss-120b", "created": 10},
                                                   {"id": "anthropic/claude-sonnet-5.5", "created": 10}])
        seen_or = []

        def or_handler(request):
            body = json.loads(request.content)
            seen_or.append(body["model"])
            if len(seen_or) == 1:
                return httpx.Response(404, json={"error": {"message": "No endpoints found for openai/gpt-oss-120b:free.", "code": 404}})
            return ok('{"diagnosis": "fixed via verified replacement"}')

        a_or = make("groq", or_handler, monkeypatch)
        res_or = a_or.call("sys", [adapters.Block("err")], 200)
        assert seen_or == ["openai/gpt-oss-120b:free", "openai/gpt-oss-120b"]
        assert res_or.model == "openai/gpt-oss-120b" and "fixed via verified replacement" in res_or.text

        # 2. Anthropic: retired model -> verified claude-haiku-5-5 in catalogue -> retries on same provider
        model_catalog.set_for_tests("anthropic", [{"id": "claude-haiku-5-5", "created": 20}])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000")
        monkeypatch.setenv("FIXENGINE_MODEL_HAIKU", "claude-3-haiku-20240307")
        cfg_ant = fx_config.load()
        seen_ant = []

        def ant_handler(request):
            body = json.loads(request.content)
            seen_ant.append(body["model"])
            if len(seen_ant) == 1:
                return httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "model: claude-3-haiku-20240307"}})
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"ok": true}'}],
                                             "usage": {"input_tokens": 50, "output_tokens": 10}, "stop_reason": "end_turn"})

        a_ant = adapters.AnthropicAdapter("haiku", cfg_ant, client=client(ant_handler), sleep=lambda s: None)
        res_ant = a_ant.call("sys", [adapters.Block("err")], 200)
        assert seen_ant == ["claude-3-haiku-20240307", "claude-haiku-5-5"]
        assert res_ant.model == "claude-haiku-5-5" and res_ant.text == '{"ok": true}'
    finally:
        model_catalog.clear()
