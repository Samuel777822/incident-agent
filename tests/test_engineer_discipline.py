"""The engineer works like a careful senior developer:
it writes a test, runs everything, never finishes on red, reviews its own diff, never rewrites whole files, remembers the project,
and NEVER throws away the owner's newer changes when its fix is written to GitHub."""
import json

from fixengine import agent, config as fx_config, orchestrator, sandbox, store
from tests import fx_helpers as H
from tests.test_v4_agent import FIX, FakeTransport, OkRunner, _engine, _ws, call, reply
from tests.test_fixengine_core import cfg, fx_db  # noqa: F401  (fixtures)

LONG = "".join(f"line {i}\n" for i in range(1, 101))
FILES = {"app.py": LONG, "small.py": "x = 1\n"}
DONE = dict(understanding="u explained in plain words", root_cause="r explained in plain words", changes_summary="c explained in plain words", client_message="m explained in plain words", verification=[], owner_steps=[], risk="low",
            impact_checked="nothing else uses it", project_notes="n")


class GreenRunner(OkRunner):
    """Passes and says tests ran (a project with a test command)."""

    def run(self, root, profile):
        res = super().run(root, profile)
        res.tests_ran = True
        return res


def _run(tmp_path, script, runner=None, files=FILES):
    ws = _ws(tmp_path, files)
    eng = agent.Engineer(transport=FakeTransport(script), workspace=ws, cfg=fx_config.load(), runner=runner or GreenRunner(),
                         profile=sandbox.Profile(language="python", test="pytest"))
    res = eng.run([{"type": "text", "text": "fix it"}])
    ws.close()
    return res, eng


def _tool_answers(eng_transport_calls):
    return [m["content"] for c in eng_transport_calls for m in c["messages"] if m.get("role") == "tool"]


# ---- tests: write one, run it, never finish without one (or a real reason) ---------------------------------------------------
def test_finishing_without_a_test_or_a_reason_is_refused_once(tmp_path):
    script = [reply(call("edit_file", path="small.py", old_text="x = 1", new_text="x = 2")), reply(call("run_checks")),
              reply(call("finish_fixed", tests_written=[], why_no_test="", **DONE)),
              reply(call("write_file", path="tests/test_small.py", content="from small import x\n\ndef test_x():\n    assert x == 2\n")),
              reply(call("run_checks")),
              reply(call("finish_fixed", tests_written=["tests/test_small.py"], why_no_test="", **DONE))]
    t = FakeTransport(script)
    ws = _ws(tmp_path, FILES)
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=GreenRunner(),
                         profile=sandbox.Profile(language="python", test="pytest")).run([{"type": "text", "text": "x"}])
    ws.close()
    answers = _tool_answers(t.calls)
    assert any("write a test that reproduces the problem" in a for a in answers)
    assert res.outcome == "fixed" and "tests/test_small.py" in res.new_files and res.data["tests_written"] == ["tests/test_small.py"]


def test_tests_written_must_be_files_it_really_added(tmp_path):
    script = [reply(call("edit_file", path="small.py", old_text="x = 1", new_text="x = 2")), reply(call("run_checks")),
              reply(call("finish_fixed", tests_written=["tests/test_imaginary.py"], why_no_test="", **DONE))]
    t = FakeTransport(script)
    ws = _ws(tmp_path, FILES)
    agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=GreenRunner(),
                   profile=sandbox.Profile(language="python", test="pytest")).run([{"type": "text", "text": "x"}])
    ws.close()
    assert any("did not add: tests/test_imaginary.py" in a for a in _tool_answers(t.calls))


def test_a_good_reason_for_no_test_is_accepted(tmp_path):
    res, _ = _run(tmp_path, [reply(call("edit_file", path="small.py", old_text="x = 1", new_text="x = 2")), reply(call("run_checks")),
                             reply(call("finish_fixed", tests_written=[], why_no_test="only a colour in the stylesheet changed", **DONE))])
    assert res.outcome == "fixed"


# ---- never finish on red ---------------------------------------------------------------------------------------------------------
def test_finishing_on_failed_checks_is_refused(tmp_path):
    res, _ = _run(tmp_path, [reply(call("edit_file", path="small.py", old_text="x = 1", new_text="x = 2")), reply(call("run_checks")),
                             reply(call("finish_fixed", tests_written=[], why_no_test="no test runner in this project", **DONE))],
                  runner=OkRunner(passed=False))
    assert res.outcome != "fixed"


def test_a_green_run_shows_the_whole_diff_for_a_self_review(tmp_path):
    t = FakeTransport([reply(call("edit_file", path="small.py", old_text="x = 1", new_text="x = 2")), reply(call("run_checks"))])
    ws = _ws(tmp_path, FILES)
    agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=GreenRunner(),
                   profile=sandbox.Profile(language="python", test="pytest")).run([{"type": "text", "text": "x"}])
    ws.close()
    review = [a for a in _tool_answers(t.calls) if "BEFORE YOU FINISH" in a]
    assert review and "-x = 1" in review[0] and "+x = 2" in review[0] and "nothing the owner built is removed" in review[0]


# ---- no whole-file rewrites of existing code ------------------------------------------------------------------------------------
def test_rewriting_a_long_existing_file_is_refused_but_small_and_new_files_are_fine(tmp_path):
    t = FakeTransport([reply(call("write_file", path="app.py", content="print('rewritten from memory')\n"),
                             call("write_file", path="small.py", content="x = 3\n"),
                             call("write_file", path="new_module.py", content="y = 1\n"))])
    ws = _ws(tmp_path, FILES)
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=GreenRunner(),
                         profile=sandbox.Profile(language="python")).run([{"type": "text", "text": "x"}])
    ws.close()
    answers = _tool_answers(t.calls)
    assert any("Rewriting a whole existing file drops code" in a for a in answers)
    assert "app.py" not in res.new_files and res.new_files.get("small.py") == "x = 3\n" and "new_module.py" in res.new_files


# ---- memory of the project ----------------------------------------------------------------------------------------------------------
def test_every_run_is_remembered_and_shown_to_the_next_run(tmp_path, monkeypatch):
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": list(FIX)})
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "pr_opened"
    memory = orchestrator.project_memory_text(pid)
    assert "fixed" in memory and "pricing.py" in memory and "divides the percent by 10" in memory
    orchestrator.remember_event(pid, "the fix for case abc made the live site worse and was undone")
    brief = agent.build_brief(request_text="r", incident_text="", evidence_text="", live_text="", case_reports=[], replies=[], baseline="",
                              notes="", history="", commits="", project_map="m", code="", memory=orchestrator.project_memory_text(pid))
    text = json.dumps(brief)
    assert "WHAT YOU DID BEFORE ON THIS PROJECT" in text and "made the live site worse" in text


def test_memory_keeps_only_the_latest_items(fx_db):
    class R:
        outcome, data, new_files = "fixed", {"root_cause": "c"}, {"a.py": "x"}
    for i in range(40):
        orchestrator.remember("p1", f"request {i}", R())
    text = orchestrator.project_memory_text("p1")
    assert "request 39" in text and "request 0\"" not in text and text.count("\n") == orchestrator.MEMORY_ITEMS - 1


# ---- the owner's newer changes are never overwritten ---------------------------------------------------------------------------
class BranchGH:
    """A fake GitHub branch the owner keeps editing. Records exactly what the agent writes."""

    def __init__(self, owner_version, sha="s1"):
        self.files, self.sha, self.pushed = {"pricing.py": owner_version}, sha, []

    def read_files(self, project, paths):
        return {"sha": self.sha, "files": {p: self.files.get(p) for p in paths}}

    def push_fix_branch(self, project, *, bug_id, new_files, title, expected_base=""):
        assert expected_base == self.sha
        self.pushed.append(dict(new_files))
        return {"branch": "agent-daemon/fix-x", "head_sha": "h" * 40, "base_sha": self.sha}

    def checks_state(self, project, sha):
        return "pending"


def _auto_engine(tmp_path, monkeypatch, gh):
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    engine, transports, prs, pid = _engine(tmp_path, monkeypatch, {"haiku": list(FIX)}, mode="auto")
    engine.gh = gh
    return engine, pid


def test_the_owner_s_newer_edit_in_another_line_is_kept(tmp_path, monkeypatch):
    owner = H.BUGGY_PRICING.replace('raise ValueError("negative price computed")', 'raise ValueError("price below zero")  # owner wording')
    gh = BranchGH(owner)
    engine, pid = _auto_engine(tmp_path, monkeypatch, gh)
    H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "github_testing"
    written = gh.pushed[0]["pricing.py"]
    assert "price * pct / 100" in written and "# owner wording" in written           # the fix AND the owner's edit


def test_the_same_lines_changed_by_the_owner_means_nothing_is_written(tmp_path, monkeypatch):
    owner = H.BUGGY_PRICING.replace("price * pct / 10", "price * pct / 100.0")       # the owner fixed it themselves, differently
    gh = BranchGH(owner)
    engine, pid = _auto_engine(tmp_path, monkeypatch, gh)
    incident_id = H.make_incident(pid)
    assert engine.handle_incident(H.claim()) == "waiting"
    assert gh.pushed == []                                                            # nothing overwritten
    bug = store.get_bug_by_incident(incident_id)
    assert "the owner changed the same lines in pricing.py" in store.gh_state(bug["id"])["conflict_note"]
    import portal_db
    assert "Nothing was overwritten" in portal_db.get_incident_row(incident_id)["stage_detail"]


def test_an_earlier_runs_edits_are_merged_onto_todays_code(fx_db, cfg):
    uid, pid = H.make_user_and_project()
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id="i", fingerprint_json={"hash": "h"}, bug_class="medium", category="")
    base = "a\nb\nc\nd\ne\n"
    store.save_gh_state(bug["id"], {"wip_files": {"f.py": "a\nB-agent\nc\nd\ne\n", "g.py": "1\nagent\n"},
                                    "wip_base": {"f.py": base, "g.py": "1\n2\n"}})
    today = {"f.py": "a\nb\nc\nd\nE-owner\n", "g.py": "1\nowner\n"}
    engine = orchestrator.Engine(cfg, adapters={}, runner=OkRunner(), repo_provider=lambda p: None)
    seeded = engine._seed_files(store.get_bug(bug["id"]), today)
    assert seeded == {"f.py": "a\nB-agent\nc\nd\nE-owner\n"}                           # g.py: same line changed by both -> dropped
    note = engine._seed_note(store.get_bug(bug["id"]), today)
    assert "g.py" in note and "redo what is still needed" in note


def test_undoing_a_fix_keeps_what_the_owner_changed_later():
    from fixengine import merge3
    before = "a\nb = 10\nc\nd\n"
    fixed = "a\nb = 100\nc\nd\n"
    now = "a\nb = 100\nc\nd = 'owner later'\n"
    assert merge3.merge(fixed, now, before) == "a\nb = 10\nc\nd = 'owner later'\n"


# ---- the new test must really catch the bug -------------------------------------------------------------------------------------
def test_a_test_that_also_passes_without_the_fix_is_flagged(tmp_path, cfg):
    class Always(OkRunner):
        def run(self, root, profile):
            res = super().run(root, profile)
            res.tests_ran = True
            return res
    engine = orchestrator.Engine(cfg, adapters={}, runner=Always(), repo_provider=lambda p: None)
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    assert engine._test_catches_bug(root, sandbox.Profile(language="python", test="pytest"), {"tests/test_a.py": "def test(): pass\n"}) is False

    class FailsWithoutFix(Always):
        def run(self, root, profile):
            res = super().run(root, profile)
            res.passed = False
            return res
    engine.runner = FailsWithoutFix()
    assert engine._test_catches_bug(root, sandbox.Profile(language="python", test="pytest"), {"tests/test_a.py": "def test(): pass\n"}) is True
