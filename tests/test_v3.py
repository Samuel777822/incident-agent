"""v3: direct push with proof (sandbox -> GitHub tests -> push), free models stay free, browser/installer fixes, site probe, journeys."""
import base64
import json
from pathlib import Path

import pytest

import monitoring_installer as mi
import portal_db
from fixengine import adapters, config as fx_config, git_ops, journeys, model_catalog, model_fix, orchestrator, prompts, sandbox, store, triage, validator
from tests import fx_helpers as H


# ============================================================================================================ proof loop
class FakeRunner:
    """Passes when the pricing bug is fixed, fails (with one failing test) when it is not."""
    def run(self, root, profile):
        fixed = "pct / 100" in (Path(root) / "pricing.py").read_text()
        if fixed:
            return sandbox.SandboxResult(passed=True, tests_ran=True, failing=0, output="all tests passed")
        return sandbox.SandboxResult(passed=False, tests_ran=True, failing=1, output="FAILED tests/test_pricing.py::test_ten_percent_off")


class FakeGH:
    def __init__(self, states, ff="ok"):
        self.states, self.ff = list(states), ff
        self.pushed, self.prs, self.deleted, self.ff_calls = [], [], [], 0

    def push_fix_branch(self, project, *, bug_id, new_files, title):
        self.pushed.append(dict(new_files))
        return {"branch": "agent-daemon/fix-x", "head_sha": f"{len(self.pushed):040d}", "base_sha": "b" * 40}

    def checks_state(self, project, sha):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def failed_check_log(self, project, sha, limit=3500):
        return "### GitHub check failed: tests\nAssertionError: expected 180 got 190"

    def fast_forward_base(self, project, head, base):
        self.ff_calls += 1
        return self.ff

    def delete_branch(self, project, branch):
        self.deleted.append(branch)

    def open_pr_for_branch(self, project, *, branch, title, body):
        self.prs.append({"title": title, "body": body})
        return {"url": "https://github.com/acme/shop/pull/8", "number": 8, "branch": branch}


class World:
    def __init__(self, tmp_path, monkeypatch, gh, mode="auto"):
        monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
        monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
        portal_db.init_db()
        self.cfg = fx_config.load()
        self.cfg["warn_every_use"]["opus"] = False
        self.cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
        self.repo = H.make_repo(tmp_path)
        self.user_id, self.project_id = H.make_user_and_project(mode=mode)
        reply = json.dumps({"diagnosis": "pct should be divided by 100", "cannot_determine": False, "edits": [H.GOOD_EDIT]})
        self.adapters = {t: adapters.FakeAdapter(t, self.cfg, [reply]) for t in fx_config.TIERS}
        self.gh = gh
        self.engine = orchestrator.Engine(self.cfg, adapters=self.adapters, runner=FakeRunner(), repo_provider=H.repo_provider(self.repo),
                                          commits_provider=lambda p: "", gh=gh,
                                          pr_opener=lambda *a, **k: pytest.fail("a pull request must not be opened on the direct-push route"))

    def first(self):
        incident_id = H.make_incident(self.project_id)
        claimed = H.claim()
        return incident_id, self.engine.handle_incident(claimed)

    def again(self):
        claimed = H.claim()
        assert claimed, "the red GitHub run must put the incident back in the queue"
        return self.engine.handle_incident(claimed)

    def incident(self, incident_id):
        return portal_db.get_incident_row(incident_id)

    def bug(self, incident_id):
        return store.get_bug_by_incident(incident_id)

    def last_prompt(self):
        return max((a.seen_prompts[-1] for a in self.adapters.values() if a.seen_prompts), key=len)


def test_green_github_run_pushes_straight_to_the_branch_without_a_pr(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["pending", "success"]))
    incident_id, outcome = w.first()
    assert outcome == "github_testing" and w.gh.pushed and w.incident(incident_id)["stage"] == "github_testing"
    w.engine.process_proofs()                       # still pending: nothing happens
    assert w.gh.ff_calls == 0
    w.engine.process_proofs()                       # green: fast-forward the tracked branch
    inc = w.incident(incident_id)
    assert w.gh.ff_calls == 1 and w.gh.deleted == ["agent-daemon/fix-x"] and w.gh.prs == []
    assert inc["status"] == "resolved" and inc["stage"] == "pushed"
    assert w.bug(incident_id)["status"] == "resolved"


def test_red_github_run_goes_back_to_the_model_with_what_failed_then_pushes(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["failed"]))
    incident_id, _ = w.first()
    w.engine.process_proofs()                       # red
    inc = w.incident(incident_id)
    assert inc["stage"] == "github_failed" and "round 1 of 3" in inc["stage_detail"]
    w.gh.states = ["success"]
    assert w.again() == "github_testing"            # the model is called again ...
    assert "GitHub tests failed after your patch" in w.last_prompt() and "expected 180 got 190" in w.last_prompt()   # ... with the error
    w.engine.process_proofs()
    assert w.incident(incident_id)["stage"] == "pushed" and w.gh.ff_calls == 1 and w.gh.prs == []


def test_three_red_rounds_open_a_pr_marked_needs_human_review(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["failed"]))
    incident_id, _ = w.first()
    for _ in range(2):
        w.engine.process_proofs()
        assert w.again() == "github_testing"
    w.engine.process_proofs()                       # the third red run: a human takes over
    inc = w.incident(incident_id)
    assert w.gh.ff_calls == 0 and len(w.gh.prs) == 1 and "Last GitHub error" in w.gh.prs[0]["body"]
    assert inc["stage"] == "needs_human" and "Needs human review" in inc["stage_detail"] and inc["pr_url"].endswith("/pull/8")
    assert w.bug(incident_id)["status"] == "needs_human"
    assert inc["no_automerge"] == 1                 # nothing merges this pull request by itself


def test_protected_branch_falls_back_to_a_pr_that_may_merge_itself(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["success"], ff="protected"))
    incident_id, _ = w.first()
    w.engine.process_proofs()
    inc = w.incident(incident_id)
    assert len(w.gh.prs) == 1 and inc["stage"] == "merging" and inc["no_automerge"] == 0


def test_no_github_tests_but_proven_sandbox_still_pushes(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "GITHUB_NO_CHECKS_GRACE", 0)
    w = World(tmp_path, monkeypatch, FakeGH(["no_checks"]))
    incident_id, _ = w.first()
    w.engine.process_proofs()
    assert w.gh.ff_calls == 1 and w.incident(incident_id)["stage"] == "pushed"


def test_branch_that_moved_while_testing_is_retested_then_given_to_a_human(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["success"], ff="moved"))
    incident_id, _ = w.first()
    w.engine.process_proofs()
    assert w.incident(incident_id)["stage"] == "queued" and w.gh.prs == []
    assert w.again() == "github_testing"
    w.engine.process_proofs()                       # moved a second time: stop and ask a human
    assert len(w.gh.prs) == 1 and w.incident(incident_id)["stage"] == "needs_human"


def test_a_ready_made_model_fix_enters_the_same_proof_loop(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, FakeGH(["success"]))
    incident_id = H.make_incident(w.project_id, message="x")
    claimed = H.claim()
    project = store.get_project_row(w.project_id)
    out = w.engine.start_proof_for_files(claimed, project, new_files={"chat.js": "new"}, diff="d", diagnosis="swap model", level="check_fixed",
                                         verified_text="parses", evidence={"kind": "retired_model", "model": "a:free", "replacement": "b:free", "was_free": True})
    assert out == "github_testing"
    state = store.gh_state(w.bug(incident_id)["id"])
    assert state["evidence"]["replacement"] == "b:free" and state["verified_text"] == "parses"
    w.engine.process_proofs()
    assert w.incident(incident_id)["stage"] == "pushed"


# ============================================================================================================ git_ops helpers
def test_condense_log_strips_noise_and_starts_near_the_first_error():
    noisy = "\n".join(f"2026-11-08T10:00:{i:02d}.123Z \x1b[32mok step {i}\x1b[0m" for i in range(40))
    log = noisy + "\n2026-11-08T10:01:00.000Z Error: Cannot find module 'x'\n2026-11-08T10:01:01.000Z exit code 1"
    out = git_ops.condense_log(log, 600)
    assert "\x1b" not in out and "2026-11-08T" not in out and "Cannot find module" in out and len(out) <= 600
    assert git_ops.condense_log("short", 600) == "short"
    assert git_ops.fix_branch_name("abcdef0123456789xyz") == "agent-daemon/fix-abcdef01234567"
    assert git_ops.http_code(RuntimeError("GitHub API rejected the request (HTTP 422)")) == 422


# ============================================================================================================ free models
OR_LIST = [
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "created": 100, "free": True, "context": 131072, "modality": "text->text", "name": "Llama 3.3"},
    {"id": "meta-llama/llama-4-scout:free", "created": 300, "free": True, "context": 131072, "modality": "text+image->text", "name": "Llama 4 Scout"},
    {"id": "deepseek/deepseek-chat-v3.1:free", "created": 250, "free": True, "context": 65536, "modality": "text->text", "name": "DeepSeek"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "created": 100, "free": False, "context": 131072, "modality": "text->text", "name": "Llama paid"},
    {"id": "openai/gpt-oss-120b", "created": 400, "free": False, "context": 131072, "modality": "text->text", "name": "gpt-oss"},
    {"id": "google/embedding-free:free", "created": 500, "free": True, "context": 8192, "modality": "text->embeddings", "name": "embed"},
]
SOURCE = {"chat.js": "fetch('https://openrouter.ai/api/v1/chat/completions',{body:JSON.stringify({model:'meta-llama/llama-3.2-3b-instruct:free'})})"}


def _catalog(listing, monkeypatch=None):
    model_catalog.clear()
    model_catalog.set_for_tests("openrouter", listing)


def test_provider_for_knows_free_suffix_is_openrouter():
    assert model_fix.provider_for("meta-llama/llama-3.3-70b-instruct:free") == "openrouter"
    assert model_fix.provider_for("deepseek/deepseek-chat-v3-0324:free") == "openrouter"


def test_scan_finds_a_free_model_that_left_openrouters_live_list():
    _catalog(OR_LIST)
    hits = model_fix.scan_files(SOURCE)
    assert [h["model"] for h in hits] == ["meta-llama/llama-3.2-3b-instruct:free"] and hits[0]["confidence"] == "live"
    assert model_fix.scan_files({"a.js": "const path = 'assets/img/logo'; const t = 'text/html'"}) == []
    assert model_fix.scan_files(SOURCE, live=False) == []        # no live list, nothing in the hand-written registry


def test_error_wording_no_endpoints_found_is_recognised():
    got = model_fix.detect_error("POST https://openrouter.ai/api/v1/chat/completions failed with HTTP 404: No endpoints found for "
                                 "meta-llama/llama-3.3-70b-instruct:free.", "", {"host": "openrouter.ai"})
    assert got and got["model"] == "meta-llama/llama-3.3-70b-instruct:free" and got["provider"] == "openrouter"


def test_a_free_model_is_replaced_by_a_free_model_that_answers(monkeypatch):
    _catalog(OR_LIST)
    asked = []
    monkeypatch.setattr(model_fix, "PROBE", lambda m: (asked.append(m), m.startswith("meta-llama/llama-4"))[1] if False else (asked.append(m) or m == "deepseek/deepseek-chat-v3.1:free"))
    choice = model_fix.choose_replacement("meta-llama/llama-3.2-3b-instruct:free", "openrouter")
    assert choice["new"] == "deepseek/deepseek-chat-v3.1:free" and choice["verified"] and choice["was_free"]
    assert asked and asked[0].startswith("meta-llama/")              # same family is tried first
    assert not any("embedding" in m for m in asked)                  # not a chat model
    assert not any(m == "openai/gpt-oss-120b" for m in asked)        # a paid model is never even considered


def test_when_no_free_model_answers_nothing_paid_is_chosen(monkeypatch):
    _catalog(OR_LIST)
    monkeypatch.setattr(model_fix, "PROBE", lambda m: False)
    choice = model_fix.choose_replacement("meta-llama/llama-3.2-3b-instruct:free", "openrouter")
    assert choice["new"] == "" and choice["was_free"] and "paid model was NOT chosen" in choice["note"]


def test_untestable_probe_still_picks_a_free_listed_model(monkeypatch):
    _catalog(OR_LIST)
    monkeypatch.setattr(model_fix, "PROBE", lambda m: None)          # no key / rate limited
    choice = model_fix.choose_replacement("meta-llama/llama-3.2-3b-instruct:free", "openrouter")
    assert choice["new"].endswith(":free") and choice["verified"]


def test_non_free_models_keep_the_documented_replacement_logic():
    _catalog(OR_LIST)
    choice = model_fix.choose_replacement("openai/gpt-3.5-turbo", "openrouter")
    assert choice["was_free"] is False and choice["new"]


def test_rank_free_candidates_prefers_same_family_then_newest():
    ranked = model_fix.rank_free_candidates("meta-llama/llama-3.2-3b-instruct:free", OR_LIST)
    assert ranked[0].startswith("meta-llama/") and "embedding" not in " ".join(ranked) and all(r.endswith(":free") for r in ranked)


# ============================================================================================================ installer
HTML = "<!doctype html><html><head><title>Bot</title></head><body><script src='app.js'></script></body></html>"
JS = "async function send(){ await fetch('https://openrouter.ai/api/v1/chat/completions'); }"


def _plan(files):
    read = files.get
    targets = mi.detect_targets(list(files), read)
    out, results = mi.plan_install(targets, read, ingest_url="https://x.test/ingest", ingest_key="adi_test", project_id="p1")
    return targets, out, results


def test_browser_script_never_gets_a_node_require_line():
    for extra in ({}, {"package.json": json.dumps({"name": "bot"})}, {"package.json": json.dumps({"name": "bot", "scripts": {"start": "npx serve ."}})}):
        targets, out, _ = _plan({"index.html": HTML, "app.js": JS, **extra})
        assert [t["kind"] for t in targets] == ["browser"]
        assert "require(" not in out.get("app.js", "") and "app.js" not in out


def test_serverless_functions_are_monitored_and_a_real_express_server_still_works():
    targets, out, results = _plan({"index.html": HTML, "app.js": JS, "api/chat.js": "export default async function h(){}", "package.json": "{}"})
    assert ("node", "serverless") in [(t["kind"], t["framework"]) for t in targets]
    assert out["api/chat.js"].startswith("import '../incident-agent-monitor.cjs'")
    targets, out, _ = _plan({"server.js": "const express=require('express');", "package.json": json.dumps({"dependencies": {"express": "4"}, "scripts": {"start": "node server.js"}})})
    assert targets[0]["framework"] == "express" and "node -r ./incident-agent-monitor.cjs" in out["package.json"]


class FakeGitHub:
    """Just enough of the GitHub API for open_monitoring_pr."""
    def __init__(self, protected=False, tree_ok=True):
        self.files = {"index.html": HTML, "app.js": JS}
        self.protected, self.tree_ok = protected, tree_ok
        self.calls, self.refs = [], {"heads/main": "c0"}

    def __call__(self, url, token, method="GET", payload=None):
        self.calls.append((method, url.split("api.github.com")[-1], payload))
        path = url.split("api.github.com/repos/o/r")[-1]
        if path == "":
            return {"private": True, "default_branch": "main"}
        if path.startswith("/branches/"):
            return {}
        if path.startswith("/git/ref/heads/") and method == "GET":
            name = "heads/" + path.split("/git/ref/heads/")[1]
            if name not in self.refs:
                raise mi.GitHubInstallError("not found")
            return {"object": {"sha": self.refs[name]}}
        if path.startswith("/git/commits/") and method == "GET":
            return {"tree": {"sha": "t0"}}
        if path.startswith("/git/trees/t0") or path.startswith("/git/trees/c0"):
            if not self.tree_ok:
                raise mi.GitHubInstallError("boom")
            return {"tree": [{"path": p, "type": "blob", "size": len(t)} for p, t in self.files.items()]}
        if path.startswith("/contents/"):
            name = path.split("/contents/")[1].split("?")[0]
            if name in self.files:
                return {"content": base64.b64encode(self.files[name].encode()).decode()}
            raise mi.GitHubInstallError("404")
        if path == "/contents/.github/workflows?ref=main":
            return []
        if path == "/git/blobs":
            return {"sha": "b" + str(len(self.calls))}
        if path == "/git/trees":
            return {"sha": "t1"}
        if path == "/git/commits":
            return {"sha": "c1"}
        if path == "/git/refs" and method == "POST":
            self.refs[payload["ref"].replace("refs/", "")] = payload["sha"]
            return {}
        if path == "/git/refs/heads/main" and method == "PATCH":
            if self.protected:
                raise mi.GitHubInstallError("protected")
            self.refs["heads/main"] = payload["sha"]
            return {}
        if path == "/pulls" and method == "POST":
            return {"html_url": "https://github.com/o/r/pull/1", "number": 1}
        if path.startswith("/pulls/") and path.endswith("/merge"):
            return {}
        return {}


def _install(monkeypatch, gh, **kw):
    monkeypatch.setattr(mi, "_request", gh)
    monkeypatch.setattr(mi.time, "sleep", lambda s: None)
    return mi.open_monitoring_pr(owner="o", repo="r", base_branch="main", project_id="p" * 36, token="t", ingest_url="https://x/ingest",
                                 ingest_key="k" * 40, **kw)


def test_install_commits_straight_to_the_branch_when_direct_push_is_on(monkeypatch):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    gh = FakeGitHub()
    result = _install(monkeypatch, gh)
    assert result["direct"] and result["merged"] and result["number"] == 0 and gh.refs["heads/main"] == "c1"
    assert not any(m == "POST" and u == "/pulls" for m, u, _ in gh.calls)


def test_install_falls_back_to_a_pr_on_a_protected_branch(monkeypatch):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    result = _install(monkeypatch, FakeGitHub(protected=True))
    assert not result.get("direct") and result["number"] == 1 and result["merged"]


def test_install_never_falls_back_to_a_python_only_guess_when_the_file_list_is_unreadable(monkeypatch):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    with pytest.raises(mi.GitHubInstallError, match="file list"):
        _install(monkeypatch, FakeGitHub(tree_ok=False))


# ============================================================================================================ prompts / triage
def test_prompt_allows_outside_api_fixes_and_keeps_free_models_free():
    assert "MUST also be free" in prompts.SYSTEM_PROMPT and "OUTSIDE API" in prompts.SYSTEM_PROMPT and "at most 5 files" in prompts.SYSTEM_PROMPT


def test_blocks_carry_evidence_and_the_failed_patch_as_untrusted_data():
    blocks = prompts.build_blocks(message="m", traceback="", files={"a.js": "x"}, sandbox_output="GitHub tests failed after your patch",
                                  previous_patch='[{"file_path":"a.js"}]', evidence={"kind": "failed_request", "request": "GET https://bible.example/isaiah/1",
                                                                                       "status": 404, "ignored": "x"})
    text = "\n".join(b.text for b in blocks)
    assert "UNTRUSTED: EVIDENCE FROM THE LIVE SITE" in text and "Failed request: GET https://bible.example/isaiah/1" in text
    assert "THE PATCH THAT FAILED" in text and "ignored" not in text


def test_triage_does_not_call_a_browser_failed_request_config():
    t = triage.classify(error_type="HTTPError", message="request failed: connection refused", traceback="", frame_count=0, files_in_trace=0,
                        repo_tokens=1000, has_tests=False, kind="failed_request")
    assert t["category"] == "external_api"
    assert triage.classify(error_type="", message="[user report] x", traceback="", frame_count=0, files_in_trace=0, repo_tokens=100,
                           has_tests=True, kind="user_report")["category"] == "user_report"


def test_evidence_line_is_parsed_from_the_event():
    claimed = {"first_event": {"message": "x", "traceback": '[evidence] {"kind": "dead_click", "dom": "button#go"}\nstack...'}}
    assert orchestrator._evidence_of(claimed) == {"kind": "dead_click", "dom": "button#go"}
    assert orchestrator._evidence_of({"first_event": {"message": "GET https://a/b failed with HTTP 404: x", "traceback": ""}})["kind"] == "failed_request"
    assert orchestrator._evidence_of({"first_event": {"message": "[user report] chapter is blank", "traceback": ""}})["kind"] == "user_report"


# ============================================================================================================ journeys
def test_journeys_are_generated_from_the_html_and_aimed_at_a_reported_dead_button():
    files = {"public/index.html": "<html><body><button id='go'>Read chapter</button><button type='submit'>x</button></body></html>"}
    spec = journeys.generate(files, evidence={"kind": "dead_click", "page": "https://s.example/index.html", "dom": 'button#go "Read chapter"'})
    assert spec["root"] == "public" and spec["journeys"][0]["steps"][1] == {"click": "#go", "expect_change": True}
    assert any(j["name"].endswith("opens without errors") for j in spec["journeys"])
    assert all(set(s) <= journeys.STEP_KEYS for j in spec["journeys"] for s in j["steps"])
    assert journeys.generate({"a.py": "x"}) is None
    assert journeys.validate({"name": "x", "steps": [{"rm": "-rf"}]}) is None


def test_a_passing_journey_after_a_failing_baseline_counts_as_proof():
    res = sandbox.SandboxResult(passed=True, journeys_ran=True)
    assert validator.verification_level(baseline_failing=-1, baseline_had_tests=False, result=res) == "journey_fixed"
    assert "journey_fixed" in validator.PROVEN_LEVELS


# ============================================================================================================ site probe
def test_site_probe_refuses_private_addresses_and_judges_answers(monkeypatch):
    import site_probe
    assert site_probe.safe_url("http://169.254.169.254/latest/meta-data") == ""
    assert site_probe.safe_url("http://localhost:8080/") == "" and site_probe.safe_url("ftp://example.com/") == ""
    assert site_probe.safe_url("https://user:pw@example.com/") == ""
    assert site_probe.judge({"ok": True, "status": 200, "size": 5000}) == "up"
    assert site_probe.judge({"ok": True, "status": 500, "size": 5000}) == "bad"
    assert site_probe.judge({"ok": True, "status": 200, "size": 10}) == "bad"           # blank page
    assert site_probe.judge({"ok": True, "status": 503, "size": 5000}) == "unreachable"   # host busy: not a code bug
    assert site_probe.judge({"ok": False, "status": 0, "size": 0}) == "unreachable"


def test_site_probe_opens_an_incident_only_after_two_bad_answers_and_never_for_outages(tmp_path, monkeypatch):
    import site_probe
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "p.sqlite3"))
    portal_db.init_db()
    _user, project_id = H.make_user_and_project()
    project = {"id": project_id, "app_url": "https://site.example/", "gate_state": "active"}
    monkeypatch.setattr(site_probe, "safe_url", lambda u: u)
    answers = iter([{"ok": True, "status": 500, "size": 900, "ms": 5}, {"ok": True, "status": 500, "size": 900, "ms": 5},
                    {"ok": False, "status": 0, "size": 0, "ms": 9}, {"ok": True, "status": 200, "size": 9000, "ms": 7}])
    monkeypatch.setattr(site_probe, "fetch", lambda url, client=None: next(answers))
    site_probe._STREAK.clear()
    assert site_probe.check_one(project) == "bad" and portal_db.list_incidents(project_id) == []
    assert site_probe.check_one(project) == "bad" and len(portal_db.list_incidents(project_id)) == 1
    assert site_probe.check_one(project) == "unreachable" and len(portal_db.list_incidents(project_id)) == 1
    assert site_probe.check_one(project) == "up"
    beats = portal_db.list_monitor_heartbeats(project_id)
    assert [b["monitor"] for b in beats] == ["probe"]
    assert portal_db.get_project_any(project_id).get("last_heartbeat_at") in ("", None)      # the probe never hides a missing monitor
    assert portal_db.site_check_state({"app_url": "https://site.example/", "id": project_id}, beats)["state"] == "answering"


# ============================================================================================================ UI
def test_ui_pieces_render_and_escape():
    import ui_flow
    assert ui_flow.flow_diagram_html().count("flow-node") == 8 and "3 failed GitHub rounds" in ui_flow.flow_diagram_html()
    card = ui_flow.report_card_html("abc", "tok<en>")
    assert "action='/projects/abc/report'" in card and "tok&lt;en&gt;" in card and "New" in card
    assert "Tell the agent" in ui_flow.new_feature_banner_html() and ui_flow.flash_html("nope") == ""
    import incident_board
    assert "5000" in incident_board.LIVE_JS and "3000" not in incident_board.LIVE_JS       # the board refreshes every 5 seconds
