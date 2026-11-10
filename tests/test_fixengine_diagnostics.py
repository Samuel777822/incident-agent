"""Provider faults are diagnosable and safe, a dry run can never call a model, the ledger tells the truth, the sandbox gets no host secrets.

No network, no money, no Docker needed: fake HTTP clients, a fake sandbox runner, and the real database code on a temporary SQLite file.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import portal_db
from fixengine import adapters, config as fx_config, orchestrator, provider_check, sandbox, store
from tests import fx_helpers as H

ROOT = Path(__file__).resolve().parent.parent
CFG = fx_config.load()


# ---- tiny fake HTTP layer ---------------------------------------------------------------------------------------------------------
class Resp:
    def __init__(self, status, payload=None, text=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}
        self.text = text if text is not None else json.dumps(payload if payload is not None else {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class Client:
    """Answers the next queued response and remembers every request. Raises if used more often than expected."""

    def __init__(self, *responses):
        self.queue, self.requests = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.requests.append(("POST", url, headers or {}, json))
        return self.queue.pop(0)

    def get(self, url, headers=None, timeout=None):
        self.requests.append(("GET", url, headers or {}, None))
        return self.queue.pop(0)


class RoutedClient:
    """Answers by URL (and method) so a multi-request check can be scripted; remembers every request."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def _answer(self, method, url, headers, body):
        self.requests.append((method, url, headers or {}, body))
        for (m, fragment), resp in self.routes.items():
            if m == method and fragment in url:
                return resp
        raise AssertionError(f"unexpected request {method} {url}")

    def post(self, url, headers=None, json=None, timeout=None):
        return self._answer("POST", url, headers, json)

    def get(self, url, headers=None, timeout=None):
        return self._answer("GET", url, headers, None)


class NoNetwork:
    def post(self, *a, **k):
        raise AssertionError("a network call was attempted")

    get = post


def _call(adapter, n=1):
    return adapter.call("system", [adapters.Block("user text")], 100)


# ---- redaction ------------------------------------------------------------------------------------------------------------------------
def test_redact_removes_keys_tokens_and_authorization_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abcdef0123456789")
    for text in ("Incorrect API key provided: sk-ant-api03-SECRETSECRET1234", "Authorization: Bearer abc.def-ghi123456",
                 "key sk-or-v1-abcdef0123456789 was rejected", "token ghp_abcdefghijklmnopqrstu", "gsk_ABCDEFGH1234 nope", "x-api-key: topsecretvalue1"):
        out = adapters.redact(text)
        assert "[redacted]" in out and not any(s in out for s in ("SECRETSECRET", "abc.def", "abcdef0123456789", "ghp_abc", "ABCDEFGH1234", "topsecretvalue"))
    assert adapters.redact("ANTHROPIC_API_KEY is not set") == "ANTHROPIC_API_KEY is not set"


# ---- provider errors keep their cause -----------------------------------------------------------------------------------------------------
def test_openrouter_privacy_404_becomes_a_clear_config_error_with_provider_model_and_status(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-real-0000")
    body = {"error": {"message": "No endpoints found matching your data policy (Free model publication).", "code": 404}}
    adapter = adapters.OpenRouterAdapter("groq", CFG, client=Client(Resp(404, body)))
    with pytest.raises(adapters.AdapterError) as info:
        _call(adapter)
    exc = info.value
    assert (exc.kind, exc.provider, exc.status, exc.model) == ("config", "openrouter", 404, "openai/gpt-oss-120b:free")
    assert exc.retryable is False
    line = exc.summary()
    assert "provider=openrouter" in line and "http=404" in line and "kind=config" in line and "retryable=no" in line
    assert "data policy" in line and "settings/privacy" in line and "customer code" in line


def test_groq_400_keeps_the_providers_explanation_and_404_is_a_config_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_not_real_0000")
    bad = adapters.GroqAdapter("groq", CFG, client=Client(Resp(400, {"error": {"message": "response_format is not supported with this model"}})))
    with pytest.raises(adapters.AdapterError) as info:
        _call(bad)
    assert info.value.kind == "bad_request" and info.value.status == 400 and "response_format is not supported" in str(info.value)
    gone = adapters.GroqAdapter("groq", CFG, client=Client(Resp(404, {"error": {"message": "The model `x` does not exist or you do not have access"}})))
    with pytest.raises(adapters.AdapterError) as info:
        _call(gone)
    assert info.value.kind == "config" and "provider=groq" in info.value.summary() and "http=404" in info.value.summary()


def test_a_provider_that_echoes_the_key_in_its_error_never_leaks_it(monkeypatch):
    secret = "sk-ant-api03-ThisIsMyRealLookingSecretKey9999"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    echo = {"error": {"message": f"invalid x-api-key: {secret}"}}
    adapter = adapters.AnthropicAdapter("haiku", CFG, client=Client(Resp(400, echo)))
    with pytest.raises(adapters.AdapterError) as info:
        _call(adapter)
    assert secret not in info.value.summary() and secret not in str(info.value)


def test_auth_errors_name_the_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real-0000")
    adapter = adapters.AnthropicAdapter("haiku", CFG, client=Client(Resp(401, {"error": {"message": "invalid x-api-key"}})))
    with pytest.raises(adapters.AdapterError) as info:
        _call(adapter)
    assert (info.value.kind, info.value.provider, info.value.status) == ("auth", "anthropic", 401)


# ---- dry run: no model can be called, whatever keys exist -----------------------------------------------------------------------------------
def test_dry_run_forces_dry_adapters_even_when_every_key_is_set(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "sk-test-not-real-key-0000")
    monkeypatch.setenv("FIXENGINE_DRY_RUN", "1")
    built = adapters.build_adapters(CFG)
    assert set(built) == set(fx_config.TIERS) and all(isinstance(a, adapters.DryRunAdapter) and a.dry_run and a.configured() for a in built.values())
    for a in built.values():
        a._client = NoNetwork()
        with pytest.raises(adapters.AdapterError) as info:
            _call(a)
        assert info.value.kind == "dry_run"
    monkeypatch.delenv("FIXENGINE_DRY_RUN")
    assert not any(isinstance(a, adapters.DryRunAdapter) for a in adapters.build_adapters(CFG).values())


class FakeRunner:
    """A sandbox that returns scripted results, so these tests need neither Docker nor pytest."""

    def __init__(self, *results):
        self.results, self.calls = list(results), 0

    def run(self, repo_dir, profile):
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


FAILING = sandbox.SandboxResult(passed=False, tests_ran=True, failing=1, output="[test] exit 1\nFAILED tests/test_pricing.py::test_ten_percent_off")
PASSING = sandbox.SandboxResult(passed=True, tests_ran=True, failing=0, output="[test] exit 0\n1 passed")


class World:
    def __init__(self, tmp_path, monkeypatch, scripts=None, runner=None, dry=False):
        monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
        portal_db.init_db()
        self.cfg = fx_config.load()
        self.cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
        self.cfg["warn_every_use"]["opus"] = False
        self.repo = H.make_repo(tmp_path)
        self.user_id, self.project_id = H.make_user_and_project()
        self.incident_id = H.make_incident(self.project_id)
        scripts = scripts or {}
        if dry:
            self.adapters = {t: adapters.DryRunAdapter(t, self.cfg) for t in fx_config.TIERS}
        else:
            self.adapters = {t: adapters.FakeAdapter(t, self.cfg, scripts.get(t)) for t in fx_config.TIERS}
        self.runner = runner or FakeRunner(FAILING, PASSING)
        self.prs = []
        self.engine = orchestrator.Engine(self.cfg, adapters=self.adapters, runner=self.runner, repo_provider=H.repo_provider(self.repo),
                                          commits_provider=lambda p: "", pr_opener=self._pr)

    def _pr(self, project, **kw):
        self.prs.append(kw)
        return {"url": "https://example.invalid/pr/1", "number": 1, "branch": "b", "path": ", ".join(kw["new_files"]), "diff": kw["diff"], "ci_status": "pending"}

    def run(self):
        outcome = self.engine.handle_incident(H.claim())
        bug = store.get_bug_by_incident(self.incident_id)
        return outcome, bug, store.list_attempts(bug["id"]) if bug else []


def test_a_dry_run_stops_at_the_model_call_with_no_ledger_row_no_quota_and_no_cost(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch, dry=True)
    outcome, bug, attempts = world.run()
    assert outcome == "dry_run"
    assert attempts == [] and world.runner.calls == 1                      # the sandbox baseline ran; nothing else did
    assert store.spend_by_tier() == [] and world.prs == []
    assert bug["baseline_failing"] == 1 and float(bug["spent_inr"] or 0) == 0.0


# ---- the ledger tells the truth ---------------------------------------------------------------------------------------------------------------
def test_a_provider_fault_is_recorded_with_its_cause_and_is_not_a_try(tmp_path, monkeypatch):
    err = adapters.AdapterError("config", "OpenRouter rejected the request (HTTP 404): No endpoints found matching your data policy",
                                provider="openrouter", model="openai/gpt-oss-120b:free", status=404)
    world = World(tmp_path, monkeypatch, scripts={"groq": [err]})
    outcome, bug, attempts = world.run()
    # v3.1: a model that cannot answer hands the problem to the next model at once (no waiting on the free model).
    assert attempts[0]["tier"] == "groq" and all(x["tier"] != "groq" for x in attempts[1:])
    a = attempts[0]
    assert a["result"] == "system_fault" and a["model"] == "openai/gpt-oss-120b:free"
    assert a["tokens_in"] == 0 and a["tokens_out"] == 0 and float(a["cost_inr"]) == 0.0
    for part in ("provider=openrouter", "model=openai/gpt-oss-120b:free", "http=404", "kind=config", "retryable=no", "origin=provider"):
        assert part in a["error_summary"], part
    assert store.tier_used(world.user_id, "groq") == 0                      # a fault never consumes a quota
    row = next(r for r in store.spend_by_tier() if r["tier"] == "groq")
    assert (row["tries"], row["faults"], row["passes"]) == (0, 1, 0)        # not shown as a failed bug fix
    assert store.get_flag("pause_groq") == "1"                              # a persistent config problem pauses the tier instead of retrying forever
    assert sum(1 for x in attempts if x["tier"] == "groq" and x["result"] != "system_fault") == 0


def test_the_model_that_really_answered_is_recorded_and_tokens_and_cost_are_exact(tmp_path, monkeypatch):
    answer = json.dumps({"diagnosis": "pct should be divided by 100", "cannot_determine": False, "edits": [H.GOOD_EDIT]})
    result = adapters.ModelResult(answer, tokens_in=10000, tokens_out=2000, cache_read=4000, model="claude-haiku-5-5-test", finish="stop")
    world = World(tmp_path, monkeypatch, scripts={"haiku": [result]})
    world.adapters["groq"].configured = lambda: False                       # skip the free tier so Normal mode is the try
    outcome, bug, attempts = world.run()
    assert outcome == "pr_opened"
    a = attempts[-1]
    assert a["result"] == "pass" and a["model"] == "claude-haiku-5-5-test"
    assert (a["tokens_in"], a["tokens_out"], a["cache_read"]) == (10000, 2000, 4000)
    expected = fx_config.estimate_cost_inr(world.cfg, "haiku", 10000, 2000, 4000)
    assert float(a["cost_inr"]) == pytest.approx(expected, abs=1e-6) and expected == pytest.approx(0.1476, abs=1e-4)   # (6000*0.10 + 4000*0.01 + 2000*0.50)/1e6 * 90
    assert float(bug["spent_inr"]) == pytest.approx(expected, abs=1e-6)


def test_a_sandbox_fault_is_labelled_as_a_sandbox_fault_not_a_provider_fault(tmp_path, monkeypatch):
    answer = json.dumps({"diagnosis": "d", "cannot_determine": False, "edits": [H.GOOD_EDIT]})
    broken = sandbox.SandboxResult(system_fault=True, error="Docker is not available on this machine")
    world = World(tmp_path, monkeypatch, scripts={"groq": [answer]}, runner=FakeRunner(FAILING, broken))
    outcome, bug, attempts = world.run()
    fault = [a for a in attempts if a["result"] == "system_fault"][0]
    assert "origin=sandbox" in fault["error_summary"] and "Docker is not available" in fault["error_summary"]
    assert store.tier_used(world.user_id, "groq") == 0


# ---- the sandbox gets no host secrets ----------------------------------------------------------------------------------------------------------
def _abuse_module():
    spec = importlib.util.spec_from_file_location("sandbox_abuse_check", ROOT / "bench" / "sandbox_abuse_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_commands_never_carry_host_secrets(tmp_path, monkeypatch):
    abuse = _abuse_module()
    for name, value in abuse.CANARIES.items():
        monkeypatch.setenv(name, value)
    (tmp_path / "tests").mkdir()
    (tmp_path / "requirements.txt").write_text("")
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n")
    seen = []

    def fake_exec(argv, timeout, cwd=None, env=None):
        seen.append(argv)
        return 0, "1 passed", False

    cfg = fx_config.load()
    res = sandbox.DockerRunner(cfg, fake_exec).run(tmp_path, sandbox.detect_profile(tmp_path))
    assert res.passed and len(seen) >= 2                                    # install + test phases both went through docker
    for argv in seen:
        flat = " ".join(argv)
        assert abuse.CANARY_MARK not in flat, "a host secret reached a docker command line"
        assert "--env-file" not in argv and "--privileged" not in argv
        forwarded = [argv[i + 1].split("=", 1)[0] for i, tok in enumerate(argv) if tok == "-e"]
        assert set(forwarded) <= {"PYTHONPATH", "CI", "PORT"}, forwarded      # an explicit allow-list: nothing else is ever forwarded
        assert all("=" in argv[i + 1] for i, tok in enumerate(argv) if tok == "-e")    # always NAME=value, never a bare NAME that copies the host value


def _run_probe(extra_env):
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    env.update(extra_env)
    proc = subprocess.run([sys.executable, "-c", _abuse_module().secrets_script()], env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def test_secrets_canary_detects_leaks_by_name_and_by_value_and_ignores_the_public_gpg_key():
    abuse = _abuse_module()
    # negative control: the official python image's PUBLIC GPG_KEY must NOT fail the check (this was the false alarm)
    assert _run_probe({"GPG_KEY": "A035C8C19219BA821ECEA86B64E628F8D684696D", "PYTHON_VERSION": "3.12.1"}) == (0, "CONTAINED")
    # positive controls: the probe MUST fail when a planted secret is present, otherwise the check proves nothing
    code, out = _run_probe(dict(abuse.CANARIES))
    assert code == 1 and out.startswith("ESCAPED") and "ANTHROPIC_API_KEY" in out
    code, out = _run_probe({"TOTALLY_INNOCENT_NAME": abuse.CANARIES["GROQ_API_KEY"]})       # smuggled under another name
    assert code == 1 and "TOTALLY_INNOCENT_NAME" in out


# ---- the benchmark runner cannot spend money by accident --------------------------------------------------------------------------------------------
def test_the_benchmark_refuses_to_run_without_an_explicit_mode():
    for flags in ([], ["--dry-run", "--paid"]):
        proc = subprocess.run([sys.executable, str(ROOT / "fixengine_bench.py"), *flags], capture_output=True, text=True, cwd=ROOT)
        assert proc.returncode == 2 and "Choose exactly one mode" in proc.stdout


# ---- provider_check works offline against fakes ----------------------------------------------------------------------------------------------------
def test_provider_check_reports_each_route_and_never_prints_a_key(monkeypatch):
    secret = "sk-or-v1-NEVERPRINTTHISSECRET123"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.setenv("FIXENGINE_PROVIDER", "openrouter")
    for key in ("GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    privacy_404 = {"error": {"message": "No endpoints found matching your data policy (Free model publication).", "code": 404}}
    catalogue = {"data": [{"id": m} for m in CFG["openrouter_models"].values()]}
    client = RoutedClient({("GET", "openrouter.ai/api/v1/models"): Resp(200, catalogue),
                           ("GET", "openrouter.ai/api/v1/auth/key"): Resp(200, {"data": {"limit_remaining": 4.5}}),
                           ("POST", "openrouter.ai/api/v1/chat/completions"): Resp(404, privacy_404)})
    lines = []
    code = provider_check.run(CFG, client=client, out=lines.append)
    text = "\n".join(lines)
    assert code == 1 and secret not in text
    assert "http=404" in text and "kind=config" in text and "settings/privacy" in text
    assert "remaining credit $4.50" in text
    assert "request test: skipped" in text                                  # paid tiers are not sent a prompt without --include-paid
    assert len([r for r in client.requests if r[0] == "POST"]) == 1         # exactly one tiny request, to the free tier only


@pytest.mark.parametrize("make,key_env,kind,status", [
    (lambda c: adapters.AnthropicAdapter("haiku", CFG, client=c, sleep=lambda s: None), "ANTHROPIC_API_KEY", "outage", 503),
    (lambda c: adapters.GroqAdapter("groq", CFG, client=c, sleep=lambda s: None), "GROQ_API_KEY", "outage", 503),
    (lambda c: adapters.OpenRouterAdapter("haiku", CFG, client=c, sleep=lambda s: None), "OPENROUTER_API_KEY", "outage", 503),
    (lambda c: adapters.AnthropicAdapter("haiku", CFG, client=c, sleep=lambda s: None), "ANTHROPIC_API_KEY", "rate_limit", 429),
    (lambda c: adapters.OpenRouterAdapter("haiku", CFG, client=c, sleep=lambda s: None), "OPENROUTER_API_KEY", "rate_limit", 429),
])
def test_exhausted_retries_report_provider_status_and_are_retryable(make, key_env, kind, status, monkeypatch):
    monkeypatch.setenv(key_env, "test-key-not-real-0000")

    class Always:
        def post(self, url, headers=None, json=None, timeout=None):
            return Resp(status, {"error": {"message": "overloaded"}}, headers={})

    with pytest.raises(adapters.AdapterError) as info:
        _call(make(Always()))
    exc = info.value
    assert exc.kind == kind and exc.status == status and exc.retryable is True and exc.provider
    assert f"http={status}" in exc.summary() and "retryable=yes" in exc.summary()
