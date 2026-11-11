"""A test the engineer writes must actually run in the sandbox (Bible-Well, 11 Nov 2026: the engineer added
tests/openrouter.test.mjs and a "test" script, but the sandbox still used the profile read before the change, so the test never
ran and the fix was marked NOT VERIFIED)."""
import json

from fixengine import agent, config as fx_config, orchestrator, sandbox, validator
from tests.test_fixengine_core import cfg  # noqa: F401  (fixture)
from tests.test_v4_agent import FakeTransport, call, reply


def _node_repo(tmp_path, with_test_script=False):
    root = tmp_path / "repo"
    (root / "api").mkdir(parents=True)
    scripts = {"build": "vite build"}
    if with_test_script:
        scripts["test"] = "node --test tests/"
    (root / "package.json").write_text(json.dumps({"name": "bw", "scripts": scripts, "dependencies": {"vite": "5"}}))
    (root / "api" / "openrouter.mjs").write_text("export const MODEL = 'google/gemma-4-26b-a4b-it:free'\n")
    return root


def test_the_profile_is_read_again_after_a_test_script_is_added(tmp_path):
    root = _node_repo(tmp_path)
    before = sandbox.detect_profiles(root)
    assert not getattr(before, "test", None)
    data = json.loads((root / "package.json").read_text())
    data["scripts"]["test"] = "node --test tests/"
    (root / "package.json").write_text(json.dumps(data))
    after = sandbox.refresh_profile(root, before)
    assert after.test and "test" in after.test


def test_refresh_keeps_the_original_when_nothing_can_be_detected(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    original = sandbox.Profile(language="python", test="pytest")
    assert sandbox.refresh_profile(empty, original) is original


class SeesTests:
    """A runner that reports whether the profile it was given had a test command."""

    def __init__(self):
        self.profiles = []

    def run(self, root, profile):
        self.profiles.append(profile)
        ran = bool(getattr(profile, "test", None))
        return sandbox.SandboxResult(passed=True, tests_ran=ran, phases=[sandbox.PhaseResult("test", True, 0, 1.0, "ok")], output="ok")


def test_run_checks_runs_the_test_the_engineer_just_added(tmp_path):
    root = _node_repo(tmp_path)
    files = {"package.json": (root / "package.json").read_text(), "api/openrouter.mjs": (root / "api" / "openrouter.mjs").read_text()}
    ws = agent.Workspace(root, files)
    new_pkg = json.loads(files["package.json"])
    new_pkg["scripts"]["test"] = "node --test tests/"
    runner = SeesTests()
    script = [reply(call("write_file", path="tests/openrouter.test.mjs", content="import test from 'node:test'\ntest('x', () => {})\n"),
                    call("write_file", path="package.json", content=json.dumps(new_pkg))),
              reply(call("run_checks"))]
    agent.Engineer(transport=FakeTransport(script), workspace=ws, cfg=fx_config.load(), runner=runner,
                   profile=sandbox.detect_profiles(root, files)).run([{"type": "text", "text": "x"}])
    ws.close()
    assert runner.profiles and getattr(runner.profiles[-1], "test", None)              # the new test command was used


def test_a_new_test_that_fails_without_the_fix_is_real_proof():
    assert "new_test_fixed" in validator.PROVEN_LEVELS and "FAILS on the old code" in validator.VERIFY_TEXT["new_test_fixed"]


def test_the_proof_run_includes_the_test_setup_file(tmp_path, cfg):
    root = _node_repo(tmp_path)
    runner = SeesTests()
    engine = orchestrator.Engine(cfg, adapters={}, runner=runner, repo_provider=lambda p: None)
    pkg = json.loads((root / "package.json").read_text())
    pkg["scripts"]["test"] = "node --test tests/"
    engine._test_catches_bug(root, sandbox.detect_profiles(root), {"package.json": json.dumps(pkg), "tests/a.test.mjs": "x"})
    assert getattr(runner.profiles[-1], "test", None)                                 # the probe used the new test script
    assert "package.json" in orchestrator.TEST_SETUP_FILES


def test_adding_a_test_script_is_not_a_risky_dependency_change():
    old = json.dumps({"name": "bw", "scripts": {"build": "vite build"}, "dependencies": {"vite": "5"}})
    test_only = json.dumps({"name": "bw", "scripts": {"build": "vite build", "test": "node --test tests/"}, "dependencies": {"vite": "5"}})
    new_dep = json.dumps({"name": "bw", "scripts": {"build": "vite build"}, "dependencies": {"vite": "5", "axios": "1"}})
    new_build = json.dumps({"name": "bw", "scripts": {"build": "vite build --mode x"}, "dependencies": {"vite": "5"}})
    assert validator.agent_risk_notes({"package.json": test_only}, {"package.json": old}) == []
    assert validator.agent_risk_notes({"package.json": new_dep}, {"package.json": old})
    assert validator.agent_risk_notes({"package.json": new_build}, {"package.json": old})
    assert validator.agent_risk_notes({"requirements.txt": "x"})                     # other build files still need a look


def test_the_engineer_is_told_to_keep_logging_when_it_fails_gracefully():
    assert "still log the real reason" in agent.SYSTEM_PROMPT


# ---- second Bible-Well run (mobile background): the report was blank and the node:test file never ran ----------------------------
def test_node_builtin_tests_run_without_a_test_script(tmp_path):
    root = _node_repo(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "mobile-background.test.mjs").write_text("import { test } from 'node:test'\ntest('x', () => {})\n")
    prof = sandbox.detect_profiles(root)
    assert prof.test == "node --test 'tests/mobile-background.test.mjs'" and prof.has_tests


def test_a_test_script_still_wins_over_the_builtin_runner(tmp_path):
    root = _node_repo(tmp_path, with_test_script=True)
    (root / "tests").mkdir()
    (root / "tests" / "a.test.mjs").write_text("x")
    assert sandbox.detect_profiles(root).test == "npm test --silent"


def test_a_blank_report_is_refused_until_it_is_written(tmp_path):
    root = _node_repo(tmp_path)
    files = {"package.json": (root / "package.json").read_text(), "api/openrouter.mjs": (root / "api" / "openrouter.mjs").read_text()}
    ws = agent.Workspace(root, files)
    blank = dict(understanding="", root_cause="", changes_summary="", client_message="", verification=[], owner_steps=[], risk="",
                 tests_written=[], why_no_test="only a stylesheet rule changed", impact_checked="", project_notes="")
    full = dict(blank, understanding="The photo zooms on phones", root_cause="background-attachment: fixed is ignored by iOS Safari",
                changes_summary="moved the photo to a fixed ::before layer", client_message="The background now fits phones. Your photos are "
                "1.9 MB; smaller copies would load faster.", risk="low")
    t = FakeTransport([reply(call("edit_file", path="api/openrouter.mjs", old_text="free'", new_text="free' // x")), reply(call("run_checks")),
                       reply(call("finish_fixed", **blank)), reply(call("finish_fixed", **full))])

    class Green:
        def run(self, root, profile):
            return sandbox.SandboxResult(passed=True, tests_ran=True, phases=[sandbox.PhaseResult("build", True, 0, 1.0, "ok")], output="ok")
    res = agent.Engineer(transport=t, workspace=ws, cfg=fx_config.load(), runner=Green(),
                         profile=sandbox.detect_profiles(root, files)).run([{"type": "text", "text": "x"}])
    ws.close()
    answers = [m["content"] for c in t.calls for m in c["messages"] if m.get("role") == "tool"]
    assert any("the report is incomplete: understanding, root_cause, changes_summary, client_message, risk" in a for a in answers)
    assert res.outcome == "fixed" and res.data["root_cause"].startswith("background-attachment") and res.data["risk"] == "low"
