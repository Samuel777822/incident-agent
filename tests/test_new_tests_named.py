"""The engineer's own new test files always run, even when the project's test script names fixed files.

Bible-Well, 11 Nov 2026: package.json had "test": "node --test tests/openrouter.test.mjs". The engineer wrote
tests/mobile-login-button.test.mjs, which never ran: not in its checks, not in the final check, and the "fails without the fix" probe
ran only the old test and wrongly reported "the new test also passes WITHOUT the fix"."""
import json
from pathlib import Path

from fixengine import agent, config as fx_config, orchestrator, sandbox
from tests.test_fixengine_core import cfg  # noqa: F401  (fixture)
from tests.test_new_tests_run import SeesTests
from tests.test_v4_agent import FakeTransport, call, reply

NEW_TEST = "import { test } from 'node:test'\nimport assert from 'node:assert/strict'\ntest('wide', () => assert.ok(true))\n"


def _bible_well(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "package.json").write_text(json.dumps({"name": "bw", "scripts": {"build": "vite build",
                                                                             "test": "node --test tests/openrouter.test.mjs"},
                                                   "dependencies": {"vite": "5"}}))
    (root / "tests" / "openrouter.test.mjs").write_text("import { test } from 'node:test'\ntest('old', () => {})\n")
    (root / "src" / "App.css").write_text(".bw-google-btn { padding: 15px 32px; }\n")
    return root


def test_test_files_are_recognised():
    for p in ("tests/mobile-login-button.test.mjs", "src/App.test.tsx", "tests/test_api.py", "api/thing_test.py",
              "__tests__/x.js", "web/spec/a.spec.ts"):
        assert sandbox.is_test_file(p), p
    for p in ("src/App.css", "api/openrouter.mjs", "package.json", "src/types.d.ts", "node_modules/x/tests/a.test.js"):
        assert not sandbox.is_test_file(p), p


def test_a_fixed_test_script_still_runs_the_new_test_file(tmp_path):
    root = _bible_well(tmp_path)
    (root / "tests" / "mobile-login-button.test.mjs").write_text(NEW_TEST)
    prof = sandbox.refresh_profile(root, None)
    assert prof.test == "npm test --silent"
    named = sandbox.with_new_tests(prof, root, ["tests/mobile-login-button.test.mjs"])
    assert named.test == "npm test --silent && node --test tests/mobile-login-button.test.mjs"
    assert prof.test == "npm test --silent"                                  # the original profile is not changed


def test_the_probe_runs_only_the_new_tests_and_no_start_up(tmp_path):
    root = _bible_well(tmp_path)
    (root / "tests" / "mobile-login-button.test.mjs").write_text(NEW_TEST)
    prof = sandbox.refresh_profile(root, None)
    only = sandbox.with_new_tests(prof, root, ["tests/mobile-login-button.test.mjs"], only=True)
    assert only.test == "node --test tests/mobile-login-button.test.mjs" and only.smoke is None
    assert sandbox.with_new_tests(prof, root, ["src/App.css"], only=True) is None        # nothing to run: caller runs the suite


def test_vitest_jest_and_python_tests_get_their_own_runner(tmp_path):
    root = tmp_path / "r"
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run src/old.test.ts"},
                                                           "devDependencies": {"vitest": "1"}}))
    (root / "web" / "src" / "btn.test.ts").write_text("import { it } from 'vitest'\nit('x', () => {})\n")
    (root / "api").mkdir()
    (root / "api" / "requirements.txt").write_text("flask\n")
    (root / "api" / "app.py").write_text("x = 1\n")
    (root / "api" / "test_app.py").write_text("def test_x():\n    assert True\n")
    prof = sandbox.refresh_profile(root, None)
    assert isinstance(prof, sandbox.StackSet)
    named = sandbox.with_new_tests(prof, root, ["web/src/btn.test.ts", "api/test_app.py"])
    tests = {p.language: p.test for p in named.parts}
    assert tests["node"].endswith("npx --no-install vitest run src/btn.test.ts")
    assert tests["python"].endswith("python -m pytest -q -p no:cacheprovider test_app.py")
    jest_root = tmp_path / "j"
    jest_root.mkdir()
    (jest_root / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "29"}}))
    (jest_root / "b.test.js").write_text("test('x', () => {})\n")
    assert sandbox.with_new_tests(sandbox.refresh_profile(jest_root, None), jest_root, ["b.test.js"], only=True).test == \
        "npx --no-install jest b.test.js"


def test_run_checks_names_the_engineers_new_test_file(tmp_path):
    root = _bible_well(tmp_path)
    files = {p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}
    ws = agent.Workspace(root, files)
    runner = SeesTests()
    script = [reply(call("write_file", path="tests/mobile-login-button.test.mjs", content=NEW_TEST)), reply(call("run_checks"))]
    agent.Engineer(transport=FakeTransport(script), workspace=ws, cfg=fx_config.load(), runner=runner,
                   profile=sandbox.detect_profiles(root, files)).run([{"type": "text", "text": "make the button full width"}])
    ws.close()
    assert runner.profiles, "run_checks did not reach the sandbox"
    assert "node --test tests/mobile-login-button.test.mjs" in runner.profiles[-1].test


class Records:
    def __init__(self, passed):
        self.passed, self.profiles = passed, []

    def run(self, root, profile):
        self.profiles.append(profile)
        return sandbox.SandboxResult(passed=self.passed, tests_ran=True, phases=[sandbox.PhaseResult("test", self.passed, 0, 1.0, "")])


def test_the_probe_judges_the_new_test_alone(tmp_path, cfg):
    root = _bible_well(tmp_path)
    o = orchestrator.Engine(cfg, adapters={}, runner=Records(passed=False), repo_provider=lambda p: None)                 # the new test fails on the original code: it really tests the problem
    prof = sandbox.detect_profiles(root)
    assert o._test_catches_bug(root, prof, {"tests/mobile-login-button.test.mjs": NEW_TEST}) is True
    assert o.runner.profiles[-1].test == "node --test tests/mobile-login-button.test.mjs"
    o.runner = Records(passed=True)
    assert o._test_catches_bug(root, prof, {"tests/mobile-login-button.test.mjs": NEW_TEST}) is False


def test_the_browser_checks_own_shots_are_never_taken_for_the_owners(monkeypatch):
    import portal_db
    shots = [{"mime": "image/png", "data": b"\x89PNG", "note": orchestrator.AFTER_SHOT_NOTE + "home-phone"},
             {"mime": "image/png", "data": b"\x89PNG", "note": "with the request: the button is small"}]
    monkeypatch.setattr(portal_db, "case_images", lambda incident_id, limit=3: shots)
    got = orchestrator.Engine._owner_images("case")
    assert [g["note"] for g in got] == ["with the request: the button is small"]
