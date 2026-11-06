"""Dress rehearsal on ~1,250-line repos (the size vibe-coded apps actually are), still with scripted fake models."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
import make_cases  # noqa: E402

from fixengine import prompts, repo_context, store  # noqa: E402
from tests import fx_helpers as H  # noqa: E402
from tests.test_fixengine_e2e import World, reply  # noqa: E402,F401

FIXES = {
    "easy_nameerror": {"file_path": "reports.py", "old_text": "round(totl, 2)", "new_text": "round(total, 2)"},
    "medium_logic_discount": {"file_path": "pricing.py", "old_text": "pct / 10, 2)", "new_text": "pct / 100, 2)"},
    "medium_cross_file_rename": {"file_path": "orders.py", "old_text": "inventory.get_stock(sku)", "new_text": "inventory.fetch_stock(sku)"},
}


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    out = tmp_path_factory.mktemp("cases")
    make_cases.ROOT = out
    make_cases.main()
    return out


@pytest.mark.parametrize("name", list(FIXES))
def test_selected_context_is_small_and_contains_the_buggy_file(cases, name):
    repo = cases / name / "repo"
    incident = json.loads((cases / name / "incident.json").read_text())
    files = repo_context.scan_repo(repo)["files"]
    total_tokens = repo_context.repo_tokens(files)
    chosen, tests = repo_context.select(files, incident["traceback"], 3000)
    assert total_tokens > 8000                                              # a genuinely big repo
    assert FIXES[name]["file_path"] in chosen
    sent = sum(prompts.estimate_tokens(t) for t in {**chosen, **tests}.values())
    assert sent < 3600 and sent < total_tokens * 0.5                          # fits the budget (20% extra allowed for test context)
    assert len(chosen) < len(files) / 2                                     # not the whole repo


@pytest.mark.parametrize("name", list(FIXES))
def test_full_loop_on_a_big_repo_ends_in_a_verified_pr(cases, name, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, scripts={"groq": ["garbage"], "haiku": [reply(FIXES[name])]})
    w.repo = cases / name / "repo"
    from fixengine import orchestrator, sandbox
    w.engine = orchestrator.Engine(w.cfg, adapters=w.adapters, runner=sandbox.LocalUnsafeRunner(w.cfg), repo_provider=H.repo_provider(w.repo),
                                   commits_provider=lambda p: "", pr_opener=w._open_pr)
    incident = json.loads((cases / name / "incident.json").read_text())
    incident_id = H.make_incident(w.project_id, message=incident["message"], traceback=incident["traceback"])
    claimed = H.claim()
    assert w.engine.handle_incident(claimed) == "pr_opened"
    bug = store.get_bug_by_incident(incident_id)
    assert bug["baseline_failing"] >= 1
    assert w.prs and "Tests that failed before the fix now pass" in w.prs[0]["body"]
    assert list(w.prs[0]["new_files"]) == [FIXES[name]["file_path"]]
