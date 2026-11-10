"""v4: the engineer (Claude with tools on the real repository), its harm rules, pause / resume, the beginner guide on the case card,
'I merged it, check my site', 'Undo this fix', and the noise filter. A scripted fake model; no network, no money."""
import json
from pathlib import Path

import httpx
import pytest

import cases
import portal_db
from fixengine import agent, config as fx_config, orchestrator, sandbox, store, validator
from tests import fx_helpers as H
from tests.test_fixengine_core import cfg, fx_db  # noqa: F401  (fixtures)
from test_web_app import web_env  # noqa: F401  (fixture)


def call(name, **args):
    return {"id": f"c_{name}_{len(json.dumps(args))}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def reply(*calls, text="", cost=0.01):
    return {"message": {"content": text, "tool_calls": list(calls)}, "finish": "tool_calls" if calls else "stop",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "cost": cost}}


class FakeTransport:
    def __init__(self, script, model="anthropic/claude-sonnet-5.5"):
        self.script, self.model, self.calls = list(script), model, []

    def complete(self, messages, tools, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, **kw})
        if kw.get("extra", {}).get("plugins"):
            return {"message": {"content": "Use the anon key in front-end code; it is public by design.",
                                "annotations": [{"type": "url_citation", "url_citation": {"url": "https://supabase.com/docs/guides/api/api-keys"}}]},
                    "finish": "stop", "usage": {"prompt_tokens": 50, "completion_tokens": 50, "cost": 0.01}}
        step = self.script.pop(0) if self.script else reply(call("give_up", reason="script ended", findings=""))
        return step(messages) if callable(step) else step


class OkRunner:
    def __init__(self, passed=True):
        self.passed, self.runs = passed, 0

    def run(self, root, profile):
        self.runs += 1
        return sandbox.SandboxResult(passed=self.passed, phases=[sandbox.PhaseResult("build", self.passed, 0 if self.passed else 1, 1.0, "out")],
                                     output="all good" if self.passed else "[build] exit 1\nboom")


def _ws(tmp_path, files):
    root = tmp_path / "repo"
    for p, t in files.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text(t, encoding="utf-8")
    return agent.Workspace(root, files)


KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhvZWFt.ZhMOL3zDYB_phB7dUainGAYAVxvEinZsR1yW"
APP = {"src/supabase.js": f"const supabaseKey = '{KEY}'\nexport const supabase = createClient(url, supabaseKey)\n",
       "src/App.jsx": 'const versions = ["NIV", "ESV", "NLT", "NKJV"]\nconst url = "/api/verse/" + book + " " + chapter\n'}


# ============================================================================================ the harm rules (the Bible-Well replay)
@pytest.mark.parametrize("name,change,expect", [
    ("placeholder key (0113612)", {"src/supabase.js": "const supabaseKey = 'public-anon-key'\nexport const supabase = createClient(url, supabaseKey)\n"}, "placeholder"),
    ("key to a missing env var (fcd300a)", {"src/supabase.js": "const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY\nexport const supabase = createClient(url, supabaseKey)\n"}, "environment variable"),
    ("fake client (89866aa)", {"src/supabase.js": APP["src/supabase.js"] + "// stub client so it does not crash\nconst stub = {}\n"}, "stub"),
    ("removes NIV (bfe1a7f)", {"src/App.jsx": APP["src/App.jsx"].replace('"NIV", ', "")}, "'NIV'"),
])
def test_judgement_calls_are_allowed_but_flagged_for_the_owner(name, change, expect):
    """The engineer decides (it may delete things when that is right), but the owner sees each judgement call before it goes live."""
    assert validator.agent_change_problems(APP, change) == [], name
    warnings = validator.agent_change_warnings(APP, change)
    assert warnings and expect in " ".join(warnings), (name, warnings)


def test_hard_limits_stay_refused():
    assert "monitor" in " ".join(validator.agent_change_problems(APP, {"incident-agent-monitor.cjs": "x"}))
    assert "existing test" in " ".join(validator.agent_change_problems({"tests/test_a.py": "x"}, {"tests/test_a.py": "y"}))
    assert validator.agent_change_problems(APP, {"src/App.jsx": "const k = 'sk-ant-" + "a" * 30 + "'\n"})
    html_old = {"web_app.py": 'x = ("<section class=a>", "<a class=b>", "</section>")\n'}
    html_new = {"web_app.py": 'x = ("<div class=c>", "<a class=b>", "</div>")\n'}
    assert validator.agent_change_problems(html_old, html_new) == [] and validator.agent_change_warnings(html_old, html_new) == []


def test_an_honest_fix_and_a_new_reproduction_test_pass():
    change = {"src/App.jsx": APP["src/App.jsx"].replace('" " + chapter', '"/" + chapter'), "tests/test_verse_url.py": "def test_x():\n    assert 1\n"}
    assert validator.agent_change_problems(APP, change) == []
    assert "existing test" in validator.agent_path_problem("tests/test_a.py", existed=True)
    assert validator.agent_path_problem("tests/test_new.py", existed=False) == ""


# ============================================================================================ the engineer loop
def test_the_engineer_reads_edits_runs_checks_and_finishes(tmp_path):
    ws = _ws(tmp_path, APP)
    t = FakeTransport([
        reply(call("read_file", path="src/App.jsx"), call("search_code", query="api/verse")),
        reply(call("edit_file", path="src/App.jsx", old_text='" " + chapter', new_text='"/" + chapter')),
        reply(call("finish_fixed", understanding="u", root_cause="space instead of slash", changes_summary="slash", client_message="Fixed.",
                   verification=[], owner_steps=[], risk="low", project_notes="Vite + Supabase")),      # refused: no checks yet
        reply(call("run_checks")),
        reply(call("finish_fixed", understanding="u", root_cause="space instead of slash", changes_summary="slash", client_message="Fixed.",
                   verification=[{"goto": "/isaiah/1"}], owner_steps=[], risk="low", project_notes="Vite + Supabase")),
    ])
    runner = OkRunner()
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=runner, profile=sandbox.Profile(language="static", build="x")).run(
        agent.build_brief(request_text="Isaiah 1 does not load", incident_text="", evidence_text="", live_text="", case_reports=[], replies=[],
                          baseline="", notes="", history="", commits="", project_map="map", code=agent.code_dump(APP)))
    ws.close()
    assert res.outcome == "fixed" and runner.runs == 1 and res.checks_passed is True
    assert res.new_files == {"src/App.jsx": APP["src/App.jsx"].replace('" " + chapter', '"/" + chapter')}
    assert "run run_checks" in json.dumps(t.calls[3]["messages"][-1])           # finishing before checking was refused
    first = t.calls[0]["messages"][1]["content"]
    assert "THE OWNER'S REQUEST" in first[0]["text"] and "THE WHOLE CODE BASE" in first[2]["text"] and first[2]["cache_control"]
    assert [s["tool"] for s in res.steps][:2] == ["read_file", "search_code"] and res.cost_usd == pytest.approx(0.05)


def test_the_engineer_may_make_a_judgement_call_and_can_still_hand_it_to_the_owner(tmp_path):
    ws = _ws(tmp_path, APP)
    t = FakeTransport([
        reply(call("web_search", query="is the supabase anon key secret")),
        reply(call("needs_owner", what_is_wrong="Your Supabase project blocks the Google sign-in return address.",
                   why="Google sends people back to an address Supabase does not allow.",
                   steps=["Open supabase.com and sign in", "Authentication > URL Configuration > add https://bible.example to Redirect URLs"],
                   how_to_check="Press Continue with Google: you should see your name.", project_notes="")),
    ])
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=OkRunner(), profile=sandbox.Profile(language="static")).run(
        [{"type": "text", "text": "x"}])
    ws.close()
    assert res.outcome == "needs_owner" and len(res.data["steps"]) == 2
    everything = json.dumps(t.calls[-1]["messages"])
    assert "supabase.com/docs" in everything                                        # the web search answer came back with its source
    assert any(c.get("extra", {}).get("plugins") for c in t.calls)                 # through OpenRouter's web plugin
    ws2 = _ws(tmp_path / "b", APP)
    t2 = FakeTransport([
        reply(call("edit_file", path="src/App.jsx", old_text='"NIV", ', new_text="")),
        reply(call("run_checks")),
        reply(call("finish_fixed", understanding="u", root_cause="the NIV source is gone for good", changes_summary="removed NIV on purpose",
                   client_message="NIV is no longer offered by the API, so it was removed.", verification=[], owner_steps=[], risk="low",
                   project_notes="")),
    ])
    res2 = agent.Engineer(transport=t2, workspace=ws2, cfg=fx_config.load(), runner=OkRunner(), profile=sandbox.Profile(language="static")).run(
        [{"type": "text", "text": "x"}])
    ws2.close()
    assert res2.outcome == "fixed"                                                    # its decision stands


def test_a_judgement_call_goes_to_a_pull_request_with_the_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    fix = [reply(call("edit_file", path="pricing.py", old_text="price * pct / 10\n", new_text="price * pct / 100\n")),
           reply(call("write_file", path="helpers.py", content="# stub payment client used while the real one is down\nclass Stub:\n    pass\n")),
           reply(call("run_checks")),
           reply(call("finish_fixed", understanding="u", root_cause="r", changes_summary="c", client_message="m", verification=[],
                      owner_steps=[], risk="low", project_notes=""))]
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": fix}, mode="auto")
    sent = []
    monkeypatch.setattr(engine, "_start_github_proof", lambda claimed, project, bug, win: sent.append(win) or "github_testing")
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "github_testing"
    assert "stub" in sent[0]["hold_reason"] and sent[0]["hold_reason"].startswith("the agent is not sure")


def test_paused_budget_and_secret_files(tmp_path):
    ws = _ws(tmp_path, {**APP, ".env": "SECRET=1"})
    stop = {"now": False}
    t = FakeTransport([reply(call("read_file", path=".env")), lambda m: stop.update(now=True) or reply(call("list_files"))])
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), should_stop=lambda: stop["now"]).run([{"type": "text", "text": "x"}])
    assert res.outcome == "paused" and "secret files are never read" in json.dumps(t.calls[1]["messages"][-1])
    c = fx_config.load()
    c["agent"]["max_inr_per_run"] = 1.0
    t2 = FakeTransport([reply(call("list_files"), cost=1.0), reply(call("list_files"), cost=1.0)])
    res2 = agent.Engineer(transport=t2, workspace=ws, cfg=c).run([{"type": "text", "text": "x"}])
    ws.close()
    assert res2.outcome == "budget" and "budget is used up" in json.dumps(t2.calls[1]["messages"])


def test_openrouter_transport_sends_tools_and_reports_no_credit_plainly():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [call("list_files")]}, "finish_reason": "tool_calls"}],
                                             "usage": {"prompt_tokens": 9, "completion_tokens": 3, "cost": 0.002}})
        return httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits"}})
    import os
    os.environ["OPENROUTER_API_KEY"] = "sk-or-test-" + "x" * 20
    try:
        t = agent.OpenRouterTransport("anthropic/claude-sonnet-5.5", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
        out = t.complete([{"role": "user", "content": "hi"}], agent.tool_specs())
        assert out["message"]["tool_calls"][0]["function"]["name"] == "list_files"
        assert seen[0]["model"] == "anthropic/claude-sonnet-5.5" and seen[0]["tool_choice"] == "auto" and seen[0]["reasoning"] == {"effort": "high"}
        with pytest.raises(agent.AgentFault) as err:
            t.complete([{"role": "user", "content": "hi"}], None)
        assert err.value.kind == "credit" and "openrouter.ai/credits" in str(err.value)
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


# ============================================================================================ the whole case, through the orchestrator
def _engine(tmp_path, monkeypatch, scripts, *, mode="pr"):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
    portal_db.init_db()
    c = fx_config.load()
    c["sandbox"]["mode"] = "local_unsafe"
    c["warn_every_use"]["opus"] = False
    c["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
    repo = H.make_repo(tmp_path)
    uid, pid = H.make_user_and_project(mode=mode)
    transports = {t: FakeTransport(s, model=f"anthropic/claude-{t}-5.5") for t, s in scripts.items()}
    prs = []
    engine = orchestrator.Engine(c, runner=sandbox.LocalUnsafeRunner(c), repo_provider=H.repo_provider(repo), commits_provider=lambda p: "",
                                 pr_opener=lambda project, **kw: prs.append(kw) or {"url": "https://github.com/acme/shop/pull/7", "number": 7,
                                                                                     "branch": "agent-daemon/fix-x", "path": "pricing.py", "diff": kw["diff"]},
                                 agent_transport=lambda tier: transports.setdefault(tier, FakeTransport([], model=tier)))
    return engine, transports, prs, pid


FIX = [reply(call("read_file", path="pricing.py")),
       reply(call("edit_file", path="pricing.py", old_text="price * pct / 10\n", new_text="price * pct / 100\n")),
       reply(call("run_checks")),
       reply(call("finish_fixed", understanding="Discounts are 10x too big", root_cause="pricing.py divides the percent by 10",
                  changes_summary="divide by 100", client_message="Discounts were 10 times too big. Fixed.", verification=[], owner_steps=[],
                  risk="low", project_notes="Python shop, prices in pricing.py"))]


def test_haiku_fixes_it_and_no_stronger_model_is_paid(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": list(FIX)})
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "pr_opened"
    assert "pct / 100" in prs[0]["new_files"]["pricing.py"]
    assert "sonnet" not in transports and "opus" not in transports                             # Haiku fixed it: nothing else ran
    bug = store.get_bug_by_incident(inc)
    tiers = [(a["tier"], a["result"]) for a in store.list_attempts(bug["id"])]
    assert tiers == [("haiku", "pass")] and "groq" not in json.dumps(tiers)                      # no free model in fixing
    assert transports["haiku"].calls[0]["messages"][1]["content"][2]["text"].count("===== FILE:") >= 2   # Haiku got the whole code
    assert store.get_flag(f"notes:{pid}") == "Python shop, prices in pricing.py"                # remembered for the next case
    assert [s["tool"] for s in store.gh_state(bug["id"])["agent_log"]][:3] == ["read_file", "edit_file", "run_checks"]


def test_when_haiku_cannot_finish_sonnet_takes_over_with_what_haiku_found(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {
        "haiku": [reply(call("give_up", reason="could not find it", findings="the discount maths in pricing.py looks wrong"))],
        "sonnet": list(FIX)})
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "pr_opened" and "opus" not in transports
    sonnet_brief = json.dumps(transports["sonnet"].calls[0]["messages"][1]["content"])
    assert "AN EARLIER RUN ON THIS CASE" in sonnet_brief and "discount maths" in sonnet_brief


def test_not_a_code_problem_ends_with_beginner_steps_and_no_more_models(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call(
        "needs_owner", what_is_wrong="The site cannot reach its database because a key is missing on Vercel.",
        why="The code asks Vercel for VITE_SUPABASE_ANON_KEY and Vercel has none.",
        steps=["Open vercel.com > your project > Settings > Environment Variables", "Name: VITE_SUPABASE_ANON_KEY. Value: copy the anon public "
               "key from supabase.com > Project Settings > API", "Click Save, then Deployments > Redeploy"],
        how_to_check="Open your site and press Continue with Google.", project_notes=""))]})
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_owner"
    row = portal_db.get_incident_row(inc)
    assert row["live_result"].startswith("NEEDS YOU") and "1. Open vercel.com" in row["live_result"] and "How to check it worked" in row["live_result"]
    assert "sonnet" not in transports and "opus" not in transports and not prs
    import incident_board
    card = incident_board.guide_html({**row, "fx_can_escalate": True}, pid, "tok", "")
    assert "What you need to do" in card and "I did it, check again" in card and "Let a stronger AI look" in card
    # the owner disagrees: the next run starts at Sonnet (no Haiku again), with the owner's words
    bug = store.get_bug_by_incident(inc)
    store.set_flag(f"agent_start:{bug['id']}", "sonnet")
    store.add_client_reply(inc, "The owner thinks this IS a problem in the code. Look again, deeper.")
    portal_db.reopen_incident_with_reply(inc, pid, "Not right")
    transports["sonnet"] = FakeTransport(list(FIX))
    assert engine.handle_incident(H.claim()) == "pr_opened"
    assert len(transports["haiku"].calls) == 1 and "Look again, deeper" in json.dumps(transports["sonnet"].calls[0]["messages"][1]["content"])


def test_an_unsafe_fix_is_never_sent_even_if_the_model_insists(tmp_path, monkeypatch):
    bad = [reply(call("write_file", path="pricing.py", content="def apply_discount(price, pct):\n    return price  # stub\n")),
           reply(call("run_checks")),
           reply(call("finish_fixed", understanding="", root_cause="", changes_summary="", client_message="", verification=[], owner_steps=[],
                      risk="low", project_notes="")),
           reply(call("give_up", reason="my only idea was a stub", findings=""))]
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": bad, "sonnet": list(bad), "opus": [reply(call("give_up", reason="no", findings=""))]})
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_human" and not prs


# ============================================================================================ pause / resume / auto-start / noise
def test_pause_resume_and_auto_start(fx_db):
    uid, pid = H.make_user_and_project(mode="auto")
    a = H.make_incident(pid, ts="2020-01-01T10:00:00Z")
    assert portal_db.pause_incident(a, pid) and H.claim() is None                       # a paused case is never picked up
    assert portal_db.resume_incident(a, pid) and H.claim()["incident_id"] == a
    portal_db.set_auto_start(pid, uid, False)
    found, _ = portal_db.ingest_event(pid, timestamp="2020-01-01T10:00:00Z", level="ERROR", message="TypeError in cart.js",
                                      traceback='[evidence] {"kind": "js_error", "page": "/cart"}', signature="js:cart")
    assert portal_db.get_incident_row(found)["status"] == "paused"
    mine, _ = portal_db.ingest_event(pid, timestamp="2020-01-01T10:00:00Z", level="ERROR", message="[user report] the cart is empty",
                                     traceback='[evidence] {"kind": "user_report", "owner_report": "the cart is empty"}', signature="user_report:9")
    assert portal_db.get_incident_row(mine)["status"] == "diagnosing"                    # your own reports always start


def test_rate_limits_trackers_and_extensions_are_noise_not_cases():
    assert "rate limited" in cases.noise_reason("GET https://openrouter.ai/api failed with HTTP 429", '[evidence] {"status": 429}')
    assert "analytics" in cases.noise_reason("GET https://www.google-analytics.com/g/collect failed with HTTP 400", "")
    assert cases.noise_reason("TypeError: verses is undefined", "at App.jsx:12") == ""


def test_case_buttons_on_the_project_page(web_env, monkeypatch):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the Send button does nothing"})
    inc = portal_db.list_incidents(project_id)[0]
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Pause this case" in page and "Pause all open cases" in page and "Turn auto-start off" in page
    _, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/pause", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "case=paused" in str(headers) and portal_db.get_incident_row(inc["id"])["status"] == "paused"
    _, _, page = _request(f"/projects/{project_id}?case=paused", cookie=cookie)
    assert "Resume (continues where it stopped)" in page and "spends nothing" in page
    _request(f"/projects/{project_id}/incidents/{inc['id']}/resume", method="POST", cookie=cookie, form={"csrf": csrf})
    assert portal_db.get_incident_row(inc["id"])["status"] == "diagnosing"
    # a fix waiting as a pull request: the beginner steps and the "I merged it" button
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE incidents SET status='pr_opened',stage='pr_open',pr_url='https://github.com/acme/shop/pull/7',pr_number=7 WHERE id=?", (inc["id"],))
        conn.commit()
    finally:
        conn.close()
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Merge pull request" in page and "Confirm merge" in page and "I merged it, check my site" in page
    _, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/merged", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "case=merged_nosite" in str(headers)                                             # no live address: it says so


def test_undo_this_fix_puts_the_files_back(web_env, monkeypatch):
    from test_v3_web import _setup
    from test_web_app import _request
    from fixengine import git_ops
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "prices are wrong on the cart"})
    inc = portal_db.list_incidents(project_id)[0]
    row = portal_db.get_project_any(project_id)
    bug = store.create_bug(project_id=project_id, user_id=row["user_id"], incident_id=inc["id"], fingerprint_json={"hash": "h"},
                           bug_class="medium", category="")
    store.save_gh_state(bug["id"], {"base_sha": "b" * 40, "files": ["pricing.py"]})
    portal_db.resolve_incident(inc["id"], project_id, "pushed")
    portal_db.set_incident_stage(inc["id"], "verified", "Verified on your live site")
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Undo this fix" in page and "data-confirm" in page
    calls = []
    monkeypatch.setattr(git_ops, "revert_files", lambda project, **kw: calls.append(kw) or "ok")
    _, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/undo", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "case=undone" in str(headers) and calls[0]["paths"] == ["pricing.py"] and calls[0]["base_sha"] == "b" * 40


# ============================================================================================ Auto mode: sure pushes, not sure asks
def _auto(tmp_path, monkeypatch, risk):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    fix = list(FIX[:-1]) + [reply(call("finish_fixed", understanding="u", root_cause="r", changes_summary="c", client_message="m",
                                       verification=[], owner_steps=[], risk=risk, project_notes=""))]
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": fix}, mode="auto")
    sent = []
    monkeypatch.setattr(engine, "_start_github_proof", lambda claimed, project, bug, win: sent.append(win) or "github_testing")
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "github_testing"
    return sent[0]


def test_auto_mode_pushes_a_sure_fix(tmp_path, monkeypatch):
    win = _auto(tmp_path, monkeypatch, "low")
    assert not win.get("hold_reason")                 # checks green, low risk, nothing for the owner: straight to the branch


def test_auto_mode_sends_an_unsure_fix_to_a_pull_request_with_the_reason(tmp_path, monkeypatch):
    win = _auto(tmp_path, monkeypatch, "medium")
    assert win["hold_reason"].startswith("the agent is not sure") and "risk of this change as medium" in win["hold_reason"]


def test_budgets_haiku_runs_are_cheap_by_design(cfg):
    caps = cfg["agent"]["max_inr_per_run"]
    assert caps["haiku"] < caps["sonnet"] < caps["opus"] and caps["haiku"] <= 40 and cfg["agent"]["effort"]["haiku"] == "high"
    eng = agent.Engineer(transport=FakeTransport([], model="anthropic/claude-haiku-5.5"), workspace=None, cfg=cfg)
    assert eng.max_inr == caps["haiku"]


# ============================================================================================ webhook refused: say why, in plain words
def _github(perms, scopes="repo, workflow"):
    def handler(request):
        if request.url.path.endswith("/hooks"):
            return httpx.Response(404, json={"message": "Not Found"}, headers={"x-oauth-scopes": scopes})
        return httpx.Response(200, json={"full_name": "samuel/shop-api", "owner": {"login": "samuel"}, "permissions": perms},
                              headers={"x-oauth-scopes": scopes})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_webhook_refusal_says_collaborator_not_admin_or_missing_permission():
    import push_watch
    api = "https://api.github.com/repos/samuel/shop-api"
    with _github({"admin": False, "push": True}) as c:
        out = push_watch.webhook_refusal(c, api, c.get(api + "/hooks"))
    assert out["why"] == "not_admin" and out["owner"] == "samuel" and out["role"] == "write" and "collaborator" in out["error"]
    with _github({"admin": True, "push": True}, scopes="read:user") as c:
        out = push_watch.webhook_refusal(c, api, c.get(api + "/hooks"))
    assert out["why"] == "no_scope" and "repo" in out["error"]


def test_the_page_explains_it_for_a_beginner():
    import web_app
    hook = {"ok": False, "why": "not_admin", "owner": "samuel", "repo": "samuel/shop-api", "error": "x"}
    html = web_app._push_summary({"webhook": hook, "queued": True}, {"id": "p1", "repo_owner": "samuel", "repo_name": "shop-api", "app_url": ""})
    for text in ("collaborator", "not an <b>admin</b>", "Nothing is broken", "every 3 minutes", "No AI is used",
                 "Is this because my app is not online?", "Collaborators page", "change the role to <b>Admin</b>", "Reconnect webhook",
                 "Tell the agent what's broken", "Live site address"):
        assert text in html, text


# ============================================================================================ ready to host (no hosting needed to work)
def test_ready_to_host_finds_the_usual_deploy_blockers(tmp_path):
    import hostready
    files = {"package.json": json.dumps({"dependencies": {"express": "4"}, "scripts": {}}),
             "server.js": "const app = require('express')()\napp.listen(3000)\nfetch('http://localhost:3000/api')\nconst k = process.env.STRIPE_KEY\n",
             "incident_agent_monitor.py": "import os\nos.getenv('AGENT_DAEMON_DISABLE')\n"}
    for p, t in {**files, ".env": "STRIPE_KEY=sk_live_x"}.items():
        (tmp_path / p).write_text(t, encoding="utf-8")
    r = hostready.assess(tmp_path, files)
    titles = " | ".join(f["title"] for f in r["findings"])
    assert r["host"] == "Render" and not r["ready"]
    for t in ("no start command", "fixed port", "calls localhost", ".env file with secrets", "not written down"):
        assert t in titles, t
    assert "Python dependencies" not in titles and r["env"] == ["STRIPE_KEY"]          # our own monitor file is ignored
    assert "Start Command: npm start" not in " ".join(r["steps"]) and "render.com" in r["steps"][0]
    assert "process.env.PORT" in hostready.request_text(r) or "PORT" in hostready.request_text(r)


def test_the_engineer_may_create_hosting_files_but_they_go_to_a_pull_request():
    from fixengine import prompts as P
    assert validator.agent_path_problem("vercel.json", existed=False) == "" and validator.agent_path_problem("Procfile", existed=True) == ""
    assert "hosted" in validator.agent_risk_notes({"render.yaml": "x"})[0]
    assert not P.is_secret_path(".env.example") and P.is_secret_path(".env") and P.is_secret_path(".env.local")
    assert validator.agent_change_problems({}, {".env.example": "OPENROUTER_API_KEY=your-key-here\n"}) == []
    assert "CI" in validator.agent_path_problem(".github/workflows/x.yml", existed=True)


def test_project_page_says_not_online_and_offers_host_ready(web_env):
    import hostready
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Your app is not online yet. That is fine" in page and "Everything else works from your GitHub repository" in page
    hostready.save(project_id, {"kind": "front-end (Vite)", "host": "Vercel", "ready": False, "env": ["VITE_X"],
                                "findings": [{"level": "error", "title": "The code calls localhost", "fix": "use /api", "code": True}],
                                "steps": ["Open vercel.com and sign in with GitHub."]})
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Ready to host?" in page and "Make it host-ready" in page and "How to put it online on Vercel" in page
    _, headers, _ = _request(f"/projects/{project_id}/host-ready", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "reported=1" in str(headers)
    inc = portal_db.list_incidents(project_id)[0]
    assert inc["signature"].startswith("user_report:")


# ============================================================================================ never a silent stop
def test_a_run_that_hits_its_limit_is_continued_with_its_edits(tmp_path, monkeypatch):
    run1 = [reply(call("edit_file", path="pricing.py", old_text="price * pct / 10\n", new_text="price * pct / 100\n"), cost=0.002),
            reply(call("list_files"), cost=0.002), reply(call("list_files"), cost=0.002)]
    run2 = [reply(call("run_checks"), cost=0.002),
            reply(call("finish_fixed", understanding="u", root_cause="divides by 10", changes_summary="divide by 100", client_message="Fixed.",
                       verification=[], owner_steps=[], risk="low", project_notes=""), cost=0.002)]
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": run1 + run2})
    engine.cfg["agent"]["max_inr_per_run"] = {"haiku": 0.3, "sonnet": 0.3, "opus": 0.3}
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "pr_opened"
    assert "pct / 100" in prs[0]["new_files"]["pricing.py"] and "sonnet" not in transports
    second_brief = json.dumps(transports["haiku"].calls[3]["messages"][1]["content"])
    assert "ALREADY APPLIED" in second_brief and "pricing.py" in second_brief


def test_the_case_cap_asks_keep_going_instead_of_stopping(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": list(FIX)})
    engine.cfg["agent"]["max_inr_per_case"] = 0.0
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "awaiting_client" and not transports.get("haiku", FakeTransport([])).calls
    row = portal_db.get_incident_row(inc)
    assert row["live_result"].startswith("BUDGET:")
    import incident_board
    card = incident_board.guide_html(row, pid, "tok", "")
    assert "Keep going" in card and "Send to human review" in card


def test_an_unavailable_stronger_mode_is_explained_with_the_fix(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": [reply(call("give_up", reason="too big", findings="the forms overlap"))]})
    store.set_flag("pause_sonnet", "1")
    store.set_flag("pause_opus", "1")
    inc = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "needs_human"
    why = store.get_bug_by_incident(inc)["stop_reason"] + store.get_bug_by_incident(inc)["review_report"]
    assert "High mode was not used because it is switched off right now" in why and "OpenRouter" in why


def test_the_report_box_teaches_how_to_write_a_request():
    import ui_flow
    card = ui_flow.report_card_html("p", "tok")
    for text in ("How to write a request the engineer can act on", "One problem (or one change) per request", "What you did",
                 "copied word for word", "Leave out", "Too broad"):
        assert text in card, text


# ============================================================================================ dashboard, speed, run again
def test_project_cards_never_put_a_link_inside_a_link(web_env):
    import re
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the Send button does nothing"})
    _, _, page = _request("/dashboard", cookie=cookie)
    card = page[page.index("class='card project-card'"):]
    card = card[:card.index("</article>")]
    assert "Open project" in card and "Latest:" in card
    assert not re.search(r"<a [^>]*>(?:(?!</a>).)*<a ", card, re.S)          # no <a> opened inside another <a>


def test_the_connection_pool_reuses_rolls_back_and_never_shares(monkeypatch):
    class Info:
        transaction_status = 0

    class Raw:
        made = 0

        def __init__(self):
            Raw.made += 1
            self.closed = self.broken = False
            self.info = Info()
            self.rollbacks = 0

        def execute(self, *a):
            return None

        def rollback(self):
            self.rollbacks += 1
            self.info.transaction_status = 0

        def close(self):
            self.closed = True
    import types
    fake = types.SimpleNamespace(connect=lambda *a, **k: Raw(), pq=types.SimpleNamespace(TransactionStatus=types.SimpleNamespace(IDLE=0)))
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake)
    monkeypatch.setitem(__import__("sys").modules, "psycopg.rows", types.SimpleNamespace(dict_row=None))
    monkeypatch.setitem(__import__("sys").modules, "psycopg.pq", fake.pq)
    monkeypatch.setattr(portal_db, "_database_url", lambda: "postgresql://x")
    portal_db._POOL.idle = []
    a = portal_db.get_connection()
    b = portal_db.get_connection()                         # nested: a different connection
    assert a._raw is not b._raw and Raw.made == 2
    a._raw.info.transaction_status = 2                     # left in a transaction
    a.close()
    assert a._raw.rollbacks == 1                           # rolled back before reuse
    c = portal_db.get_connection()
    assert c._raw is a._raw and Raw.made == 2              # reused, no new connection
    b.close(); c.close()
    monkeypatch.setenv("DB_POOL", "0")
    assert isinstance(portal_db.get_connection(), Raw)     # the switch turns pooling off


def test_run_again_reopens_the_same_case_without_retyping(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the cart total is wrong"})
    inc = portal_db.list_incidents(project_id)[0]
    portal_db.mark_remediation_needs_human(inc["id"], project_id, "stopped")
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Run again" in page
    _, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/rerun", method="POST", cookie=cookie, form={"csrf": csrf})
    assert "case=rerun" in str(headers) and portal_db.get_incident_row(inc["id"])["status"] == "diagnosing"
    assert len(portal_db.list_incidents(project_id)) == 1                   # the same case, not a new one


# ============================================================================================ budget scaling, pause emails, email check
def test_spending_limits_grow_with_the_budget(monkeypatch):
    monkeypatch.setenv("FIXENGINE_BUDGET_INR", "2000")
    b = fx_config.load()["budget"]
    assert b["spike_hour_min_inr"] == 200.0 and b["project_hour_cap_inr"] == 750.0


def test_a_project_pause_emails_the_admins(fx_db, cfg, monkeypatch):
    from fixengine import guard as fx_guard, notify
    sent = []
    monkeypatch.setattr(notify, "_to_admins", lambda subject, body="", kind="": sent.append(subject))
    uid, pid = H.make_user_and_project()
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id="i", fingerprint_json={"hash": "h"}, bug_class="medium", category="")
    aid = store.add_attempt(bug=bug, tier="sonnet", model="m", used_strong_diag=False, info_hash="x")
    store.finish_attempt(aid, result="fail", cost_inr=500.0)
    assert fx_guard.Guard(cfg).project_paused(pid) and any("paused for one project" in s for s in sent)
    assert fx_guard.Guard(cfg).user_ceiling_reached(uid) and any("monthly spending ceiling" in s for s in sent)


def test_email_check_names_what_is_missing():
    import email_health

    class Resp:
        def __init__(self, answers):
            self._a = answers

        def json(self):
            return {"Answer": [{"type": 16, "data": a} for a in self._a]}

    class Client:
        def get(self, url, params=None, timeout=None):
            name = params["name"]
            return Resp({"agentdaemon.xyz": ["v=spf1 include:zoho.in ~all"]}.get(name, []))
    res = email_health.check("agentdaemon.xyz", "brevo", client=Client())
    text = " ".join(res["problems"])
    assert not res["ok"] and "spf.brevo.com" in text and "DKIM" in text and "DMARC" in text and "No SPF" not in text
    steps = " ".join(email_health.fix_steps("agentdaemon.xyz", "brevo"))
    assert "v=spf1 include:zoho.in include:spf.brevo.com ~all" in steps and "_dmarc" in steps
