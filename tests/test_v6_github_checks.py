"""v6: GitHub Actions as the test sandbox. Measured on Bible-Well: ~30 s from push to results. These tests cover the generated
workflow, reading its results, the runner's working-copy diff and cleanup, upgrading old workflows, and "nothing ran = not tested"."""
import io
import json
import zipfile
from pathlib import Path

import yaml

from fixengine import github_checks, orchestrator, sandbox


def _node_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "test": "node --test tests/a.test.mjs",
                                                               "lint": "eslint ."}, "devDependencies": {"vite": "5"}}))
    (root / "package-lock.json").write_text("{}")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "App.css").write_text(".a{}\n")
    (root / "old.txt").write_text("bye\n")
    return root


def test_the_workflow_runs_only_on_our_branches_reads_only_and_reports_every_step(tmp_path):
    src = github_checks.workflow_source(sandbox.detect_profiles(_node_repo(tmp_path / "r")))
    assert src.startswith("# agent-daemon-check v3") and github_checks.is_current(src)
    y = yaml.safe_load(src)
    on = y.get("on") or y.get(True)
    assert on["push"]["branches"] == ["agent-daemon/**"] and y["permissions"] == {"contents": "read"}
    names = [s.get("name") for s in y["jobs"]["check"]["steps"]]
    assert {"s0-node install", "s0-node build", "s0-node lint", "s0-node test", "facts"} <= set(names)
    steps = [s for s in y["jobs"]["check"]["steps"] if str(s.get("name", "")).startswith("s0-")]
    assert all(s["continue-on-error"] is True for s in steps)
    assert "secrets." not in src
    assert not github_checks.is_current("# agent-daemon-check v2\nname: x")


def _facts(steps):
    return {"version": 3, "steps": [{"stack": "s0-node", "name": n, "rc": rc, "seconds": 1, "tail": t} for n, rc, t in steps]}


def test_results_lint_never_fails_a_check_and_nothing_ran_is_never_green():
    ok = github_checks.to_result(_facts([("install", 0, ""), ("build", 0, ""), ("lint", 1, "29 problems"), ("test", 0, "# pass 17")]))
    assert ok.passed and ok.tests_ran and ok.failing == 0
    red = github_checks.to_result(_facts([("install", 0, ""), ("build", 0, ""), ("test", 1, "# fail 2\nnot ok")]))
    assert not red.passed and red.failing == 2 and "exit 1" in red.output
    nothing = github_checks.to_result(_facts([]))
    assert not nothing.passed and not nothing.tests_ran
    assert github_checks.nothing_ran(_facts([("install", 0, ""), ("lint", 0, "")])) and not github_checks.nothing_ran(None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("results.json", json.dumps(_facts([("test", 0, "")])))
    assert github_checks.read_facts(buf.getvalue())["steps"][0]["name"] == "test"


def test_the_runner_sends_only_what_changed_waits_for_github_and_deletes_its_branch(tmp_path, monkeypatch, cfg):
    from fixengine import git_ops
    base = _node_repo(tmp_path / "base")
    work = _node_repo(tmp_path / "work")
    (work / "src" / "App.css").write_text(".a{width:100%}\n")
    (work / "tests").mkdir()
    (work / "tests" / "a.test.mjs").write_text("import { test } from 'node:test'\n")
    (work / "old.txt").unlink()
    pushed, deleted_branches, polls = [], [], []
    monkeypatch.setattr(git_ops, "push_check_commit", lambda project, **kw: pushed.append(kw) or {"head_sha": "abc", "branch": kw["branch"]})
    monkeypatch.setattr(git_ops, "delete_branch", lambda project, branch: deleted_branches.append(branch))

    def bundle(project, sha):
        polls.append(sha)
        return {"state": "pending"} if len(polls) < 2 else {"state": "done", "facts": _facts([("build", 0, ""), ("test", 0, "# pass 1")])}
    monkeypatch.setattr(git_ops, "check_bundle", bundle)
    monkeypatch.setattr(sandbox.time, "sleep", lambda s: None)
    sandbox.set_check_context({"id": "p"}, base)
    try:
        res = sandbox.GitHubRunner(cfg).run(work, sandbox.detect_profiles(work))
    finally:
        sandbox.set_check_context(None)
    assert res.passed and res.tests_ran
    sent = pushed[0]
    assert set(sent["files"]) == {"src/App.css", "tests/a.test.mjs", github_checks.WORKFLOW_PATH}      # unchanged files are not sent
    assert sent["deleted"] == ["old.txt"] and sent["branch"].startswith("agent-daemon/check-")
    assert deleted_branches == [sent["branch"]]


def test_github_problems_are_a_fault_never_a_red_or_green_result(tmp_path, monkeypatch, cfg):
    from fixengine import git_ops
    repo = _node_repo(tmp_path / "r")
    monkeypatch.setattr(git_ops, "push_check_commit", lambda project, **kw: (_ for _ in ()).throw(RuntimeError("403 workflow scope")))
    sandbox.set_check_context({"id": "p"}, repo)
    try:
        res = sandbox.GitHubRunner(cfg).run(repo, sandbox.detect_profiles(repo))
    finally:
        sandbox.set_check_context(None)
    assert res.system_fault and "workflow" in res.error
    assert sandbox.GitHubRunner(cfg).run(repo, sandbox.detect_profiles(repo)).system_fault      # no case context: refuse


def test_an_old_test_workflow_is_upgraded_by_our_code_on_the_fix_branch(cfg):
    import monitoring_installer

    class GH:
        def read_files(self, project, paths):
            return {"sha": "x", "files": {monitoring_installer.WORKFLOW_PATH: "name: tests\non: push\n# python only\n"}}
    e = orchestrator.Engine(cfg, adapters={}, runner=None, repo_provider=lambda p: None, gh=GH())
    out = e._workflow_upgrades({"id": "p"})
    assert out[monitoring_installer.WORKFLOW_PATH].startswith(monitoring_installer.WORKFLOW_VERSION_LINE)

    class Current(GH):
        def read_files(self, project, paths):
            return {"sha": "x", "files": {monitoring_installer.WORKFLOW_PATH: monitoring_installer.WORKFLOW_SOURCE}}
    assert orchestrator.Engine(cfg, adapters={}, runner=None, repo_provider=lambda p: None, gh=Current())._workflow_upgrades({}) == {}


def test_a_green_github_status_that_ran_nothing_is_not_proof(cfg):
    class GH:
        def check_bundle(self, project, sha):
            return {"state": "done", "facts": _facts([("install", 0, "")])}
    e = orchestrator.Engine(cfg, adapters={}, runner=None, repo_provider=lambda p: None, gh=GH())
    state = {"head_sha": "abc"}
    assert e._github_ran_nothing({}, state) and state["checks_ran_nothing"]

    class Ran(GH):
        def check_bundle(self, project, sha):
            return {"state": "done", "facts": _facts([("build", 0, ""), ("test", 0, "")])}
    assert not orchestrator.Engine(cfg, adapters={}, runner=None, repo_provider=lambda p: None, gh=Ran())._github_ran_nothing({}, {"head_sha": "a"})


def _fake_github(monkeypatch, facts):
    from fixengine import git_ops
    pushed = []
    monkeypatch.setattr(git_ops, "push_check_commit", lambda project, **kw: pushed.append(kw) or {"head_sha": "abc", "branch": kw["branch"]})
    monkeypatch.setattr(git_ops, "delete_branch", lambda project, branch: None)
    monkeypatch.setattr(git_ops, "check_bundle", lambda project, sha: {"state": "done", "facts": facts})
    monkeypatch.setattr(sandbox.time, "sleep", lambda s: None)
    return pushed


def test_a_two_stack_project_is_checked_in_one_github_run_with_the_usual_stack_names(tmp_path, monkeypatch, cfg):
    repo = _node_repo(tmp_path / "r")
    (repo / "api").mkdir()
    (repo / "api" / "app.py").write_text("x = 1\n")
    (repo / "api" / "test_app.py").write_text("def test_x():\n    assert True\n")
    profile = sandbox.detect_profiles(repo)
    assert isinstance(profile, sandbox.StackSet) and len(profile.parts) == 2
    keys = [f"s{i}-{p.language}" for i, p in enumerate(profile.parts)]
    facts = {"version": 3, "steps": [{"stack": keys[0], "name": "build", "rc": 0, "seconds": 1, "tail": ""},
                                     {"stack": keys[1], "name": "test", "rc": 1, "seconds": 1, "tail": "1 failed"}]}
    pushed = _fake_github(monkeypatch, facts)
    sandbox.set_check_context({"id": "p"}, repo)
    try:
        res = sandbox.run_profile(sandbox.GitHubRunner(cfg), repo, profile)
    finally:
        sandbox.set_check_context(None)
    assert len(pushed) == 1                                            # one push and one wait for every stack
    labels = [sandbox.stack_label(p) for p in profile.parts]
    assert [ph.name for ph in res.phases] == [f"{labels[0]}: build", f"{labels[1]}: test"]
    rows = sandbox.stack_summary(profile, res)
    assert rows[0]["ok"] is True and rows[1]["ok"] is False and rows[1]["phase"] == "test"
    assert f"[{labels[1]} test]" in res.output and "s1-" not in res.output


def test_the_push_guard_checks_the_exact_pushed_commit_and_github_mode_counts_as_ready(tmp_path, monkeypatch, cfg):
    import push_watch
    repo = _node_repo(tmp_path / "r")
    pushed = _fake_github(monkeypatch, _facts([("build", 0, ""), ("test", 0, "")]))
    sandbox.set_check_context({"id": "p"}, repo, base_sha="feedbeef")
    try:
        res = sandbox.GitHubRunner(cfg).run(repo, sandbox.detect_profiles(repo))
    finally:
        sandbox.set_check_context(None)
    assert res.passed and pushed[0]["base_sha"] == "feedbeef"
    assert set(pushed[0]["files"]) == {github_checks.WORKFLOW_PATH} and pushed[0]["deleted"] == []   # the commit as pushed
    monkeypatch.setenv("FIXENGINE_SANDBOX_MODE", "github")
    assert push_watch.sandbox_ready(cfg) == (True, "")
    assert isinstance(sandbox.make_runner(cfg), sandbox.GitHubRunner)


def test_a_red_build_never_reports_zero_failing_tests():
    res = github_checks.to_result(_facts([("install", 0, ""), ("build", 1, "error TS2304"), ("test", 0, "# pass 3")]))
    assert not res.passed and res.failing is None


from tests.test_fixengine_core import cfg  # noqa: E402,F401  (fixture)
