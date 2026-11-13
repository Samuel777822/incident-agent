"""v6 cheaper runs: automatic prompt caching, trimming old tool output in one go, smaller tool results for Haiku, and a run's spend
cap that follows the owner's bar."""
import json

import httpx

from fixengine import agent, config as fx_config, orchestrator, sandbox
from tests.test_v4_agent import FakeTransport, call, reply


def _transport_body(model):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    t = agent.OpenRouterTransport(model, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return t, seen


def test_claude_requests_ask_openrouter_for_automatic_caching(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-" + "x" * 20)
    t, seen = _transport_body("anthropic/claude-haiku-5.5")
    t.complete([{"role": "user", "content": "hi"}], None)
    assert seen[0]["cache_control"] == {"type": "ephemeral"}
    t2, seen2 = _transport_body("openai/gpt-oss-120b:free")
    t2.complete([{"role": "user", "content": "hi"}], None)
    assert "cache_control" not in seen2[0]                      # only for Claude models


def _engineer(model="anthropic/claude-haiku-5.5", script=None, tmp_path=None):
    ws = agent.Workspace(tmp_path, {"a.py": "x = 1\n"})
    return agent.Engineer(transport=FakeTransport(script or [], model=model), workspace=ws, cfg=fx_config.load()), ws


def test_haiku_tool_results_are_capped_smaller_than_sonnets(tmp_path):
    eng, ws = _engineer(tmp_path=tmp_path)
    big = "y" * 20_000
    out = eng._tool_msg({"id": "c1"}, big)["content"]
    assert len(out) < 6_200 and "cut at 6000 characters" in out
    sonnet, ws2 = _engineer("anthropic/claude-sonnet-5.5", tmp_path=tmp_path)
    assert len(sonnet._tool_msg({"id": "c1"}, big)["content"]) > 13_000
    ws.close(); ws2.close()


def test_old_tool_output_is_trimmed_in_one_go_only_when_the_budget_is_passed(tmp_path):
    eng, ws = _engineer(tmp_path=tmp_path)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": [{"type": "text", "text": "brief"}]}]
    for i in range(10):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"file {i} " + "z" * 5_000})
    before = [dict(m) for m in msgs]
    eng._trim(msgs)
    assert msgs == before and eng.trims == 0                    # under budget: nothing changes (the cache stays valid)
    eng.context_budget = 20_000
    eng._trim(msgs)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert all(m["content"].startswith("[older tool output removed") for m in tools[:-agent.KEEP_RECENT_TOOL_RESULTS])
    assert all("z" * 100 in m["content"] for m in tools[-agent.KEEP_RECENT_TOOL_RESULTS:])
    assert all(m["tool_call_id"] for m in tools) and eng.trims == 1
    assert msgs[1]["content"][0]["text"] == "brief"             # the brief is never trimmed
    ws.close()


def test_haiku_gets_a_smaller_first_message():
    assert fx_config.load()["agent"]["full_code_chars"]["haiku"] <= 120_000


def test_a_run_never_spends_more_than_the_bar_has_left(cfg):
    e = orchestrator.Engine(cfg, adapters={}, runner=None, repo_provider=lambda p: None)

    class Bars:
        def bar_left_inr(self, user_id, tier):
            return 12.0
    e.guard = Bars()
    assert e._run_cap({"user_id": "u"}, "haiku") == 12.0
    e.guard = type("NoBars", (), {})()
    assert e._run_cap({"user_id": "u"}, "haiku") == float(cfg["agent"]["max_inr_per_run"]["haiku"])


from tests.test_fixengine_core import cfg  # noqa: E402,F401  (fixture)
