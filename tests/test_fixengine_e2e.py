"""Whole-loop tests: fake models + a real pytest run (local_unsafe sandbox) + a fake GitHub. No network, no money."""
import json

import pytest

import portal_db
from fixengine import adapters, api, config as fx_config, orchestrator, sandbox, store
from fixengine.guard import Guard
from tests import fx_helpers as H


def reply(edit=None, diagnosis="pct should be divided by 100", cannot=False):
    return json.dumps({"diagnosis": diagnosis, "cannot_determine": cannot, "edits": [edit] if edit else []})


class World:
    def __init__(self, tmp_path, monkeypatch, scripts=None, configured=True, mode="pr"):
        monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
        monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
        portal_db.init_db()
        self.cfg = fx_config.load()
        self.cfg["sandbox"]["mode"] = "local_unsafe"
        self.repo = H.make_repo(tmp_path)
        self.user_id, self.project_id = H.make_user_and_project(mode=mode)
        self.prs = []
        scripts = scripts or {}
        self.adapters = {t: adapters.FakeAdapter(t, self.cfg, scripts.get(t)) for t in fx_config.TIERS}
        if not configured:
            for a in self.adapters.values():
                a.configured = lambda: False
        self.engine = orchestrator.Engine(self.cfg, adapters=self.adapters, runner=sandbox.LocalUnsafeRunner(self.cfg),
                                          repo_provider=H.repo_provider(self.repo), commits_provider=lambda p: "",
                                          pr_opener=self._open_pr)

    def _open_pr(self, project, **kw):
        self.prs.append(kw)
        return {"url": "https://github.com/acme/shop/pull/7", "number": 7, "branch": "agent-daemon/fix-x",
                "path": ", ".join(kw["new_files"]), "diff": kw["diff"], "ci_status": "pending"}

    def silence_warnings(self):
        self.cfg["warn_every_use"]["opus"] = False
        self.cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})

    def fill_haiku(self, n=15):
        """n earlier Normal-mode tries, backdated: they count toward the monthly quota but not the hourly rate limit."""
        filler = store.create_bug(project_id=self.project_id, user_id=self.user_id, incident_id="filler",
                                  fingerprint_json={"hash": "f"}, bug_class="easy", category="")
        for _ in range(n):
            aid = store.add_attempt(bug=filler, tier="haiku", model="m", used_strong_diag=False, info_hash=store.new_id())
            store.finish_attempt(aid, result="fail")
        store._run("UPDATE fx_attempts SET created_at=? WHERE bug_id=?", ("2026-11-02T01:00:00+00:00", filler["id"]))

    def run_once(self):
        incident_id = H.make_incident(self.project_id)
        claimed = H.claim()
        assert claimed and claimed["incident_id"] == incident_id
        return incident_id, self.engine.handle_incident(claimed)

    def bug(self, incident_id):
        return store.get_bug_by_incident(incident_id)

    def tiers(self, incident_id):
        return [(a["tier"], a["result"]) for a in store.list_attempts(self.bug(incident_id)["id"])]

    def incident(self, incident_id):
        conn = portal_db.get_connection()
        try:
            return dict(portal_db._execute(conn, "SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone())
        finally:
            conn.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return lambda **kw: World(tmp_path, monkeypatch, **kw)


def test_free_tries_then_haiku_fixes_it(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    incident_id, outcome = w.run_once()
    assert outcome == "pr_opened"
    assert w.tiers(incident_id) == [("groq", "unusable")] * 3 + [("haiku", "pass")]
    bug = w.bug(incident_id)
    assert bug["status"] == "pr_opened" and bug["baseline_failing"] == 1 and bug["pr_url"].endswith("/7")
    assert w.incident(incident_id)["status"] == "pr_opened" and w.incident(incident_id)["no_automerge"] == 0
    pr = w.prs[0]
    assert "pct / 100" in pr["new_files"]["pricing.py"] and "Tests that failed before the fix now pass" in pr["body"]
    assert bug["spent_inr"] > 0 and store.spend_inr(period=store.current_period()) == pytest.approx(bug["spent_inr"])
    assert len(store.list_decisions(bug["id"])) == 4


def test_each_try_sees_the_previous_failure_but_not_the_whole_history(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.WRONG_EDIT), reply(H.GOOD_EDIT)]})
    incident_id, outcome = w.run_once()
    assert outcome == "pr_opened" and w.tiers(incident_id)[-2:] == [("haiku", "fail"), ("haiku", "pass")]
    second_prompt = w.adapters["haiku"].seen_prompts[1]
    assert "WHAT WAS TRIED" in second_prompt and "SANDBOX OUTPUT FROM THE LAST ATTEMPT" in second_prompt
    assert "pct / 50" not in w.adapters["haiku"].seen_prompts[0]


def test_escalates_to_sonnet_after_the_haiku_floor_and_logs_why(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.WRONG_EDIT)], "sonnet": [reply(H.GOOD_EDIT, "root cause found")]})
    incident_id, outcome = w.run_once()
    tiers = [t for t, _ in w.tiers(incident_id)]
    assert outcome == "pr_opened"
    assert tiers[:3] == ["groq"] * 3 and tiers[3:5] == ["haiku", "haiku"] and "sonnet" in tiers
    assert tiers.index("sonnet") >= 5                                   # never before the Haiku floor
    decisions = store.list_decisions(w.bug(incident_id)["id"])
    assert any("lowest expected cost" in d["reason"] for d in decisions) and all(d["options_json"] for d in decisions[3:])
    costs = {a["tier"]: a["cost_inr"] for a in store.list_attempts(w.bug(incident_id)["id"])}
    assert costs["sonnet"] > costs["haiku"] > costs["groq"] == 0


def test_a_strong_models_diagnosis_is_handed_to_the_cheap_model_on_drop_back(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.WRONG_EDIT), reply(H.WRONG_EDIT), reply(H.GOOD_EDIT)],
                       "sonnet": [reply(H.WRONG_EDIT, "the divisor must be 100, not 10")]})
    incident_id, outcome = w.run_once()
    tiers = [t for t, _ in w.tiers(incident_id)]
    assert outcome == "pr_opened" and tiers[5:7] == ["sonnet", "haiku"]
    assert "the divisor must be 100" in w.adapters["haiku"].seen_prompts[-1]
    assert w.bug(incident_id)["strong_diagnosis"].startswith("the divisor")


def test_without_api_keys_it_stops_politely_and_writes_a_review(world):
    w = world(configured=False)
    incident_id, outcome = w.run_once()
    assert outcome == "needs_human" and w.tiers(incident_id) == []
    bug = w.bug(incident_id)
    assert "No AI model is configured" in bug["stop_reason"] and "Human review needed" in bug["review_report"]
    assert w.incident(incident_id)["status"] == "needs_human" and not w.prs


def test_unsafe_patches_are_rejected_and_never_reach_github(world):
    evil = {"file_path": "tests/test_pricing.py", "old_text": "== 180", "new_text": "== 20"}
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(evil)], "sonnet": [reply(evil)], "opus": [reply(evil)]})
    w.silence_warnings()
    incident_id, outcome = w.run_once()
    assert outcome == "needs_human" and not w.prs
    attempts = store.list_attempts(w.bug(incident_id)["id"])
    assert all(a["result"] in ("unusable", "fail") for a in attempts)
    assert any("tests may not be edited" in a["error_summary"] for a in attempts)


def test_hard_cap_per_bug_keeps_the_spend_bounded(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.WRONG_EDIT)], "sonnet": [reply(H.WRONG_EDIT)], "opus": [reply(H.WRONG_EDIT)]})
    w.silence_warnings()
    w.adapters["sonnet"].tokens = (50000, 3000)
    w.adapters["opus"].tokens = (50000, 3000)
    incident_id, outcome = w.run_once()
    bug = w.bug(incident_id)
    assert outcome == "needs_human"
    assert bug["spent_inr"] <= w.cfg["caps"]["per_bug_cost_inr"] + 0.01 and bug["tries"] <= w.cfg["caps"]["per_bug_max_tries"]


def test_sandbox_outage_does_not_burn_the_users_tries(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    real = w.engine.runner
    state = {"n": 0}

    class Flaky:
        def run(self, repo, profile):
            state["n"] += 1
            if state["n"] == 2:                    # call 1 is the baseline; free tries return junk and never reach the sandbox
                return sandbox.SandboxResult(system_fault=True, error="host down")
            return real.run(repo, profile)
    w.engine.runner = Flaky()
    incident_id, outcome = w.run_once()
    assert outcome == "waiting"
    assert ("haiku", "system_fault") in w.tiers(incident_id)
    assert Guard(w.cfg).quota(w.user_id, "haiku")["used"] == 0           # the try is restored
    assert w.bug(incident_id)["spent_inr"] > 0                           # the money really was spent, and is recorded


def test_provider_outage_waits_and_pauses_after_repeated_faults(world):
    err = adapters.AdapterError("outage", "Anthropic unavailable")
    w = world(scripts={"groq": ["garbage"], "haiku": [err]})
    incident_id, outcome = w.run_once()
    assert outcome == "waiting"
    for _ in range(2):                           # the worker comes back for it after the wait
        store._run("UPDATE incident_jobs SET available_at='2020-01-01T00:00:00+00:00'")
        claimed = H.claim()
        assert claimed and w.engine.handle_incident(claimed) in ("waiting", "needs_human")
    assert "haiku" in store.paused_tiers()
    assert any(a["kind"] == "provider_outage" for a in store.list_admin_actions())
    assert Guard(w.cfg).quota(w.user_id, "haiku")["used"] == 0           # outages never cost the user a try


def test_bad_api_key_pauses_the_model_and_alerts_admins(world, monkeypatch):
    sent = []
    monkeypatch.setattr("fixengine.notify._to_admins", lambda s, b="", k="x": sent.append(s))
    w = world(scripts={"groq": ["garbage"], "haiku": [adapters.AdapterError("auth", "Anthropic rejected the API key (HTTP 401)")]})
    incident_id, outcome = w.run_once()
    assert outcome == "waiting" and "haiku" in store.paused_tiers() and any("paused" in s for s in sent)


def test_warning_waits_for_the_user_then_continues(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    w.fill_haiku(15)                                                 # the plan's Normal-mode warning point
    incident_id, outcome = w.run_once()
    assert outcome == "awaiting_choice"
    choice = store.list_user_choices(w.user_id)[0]
    assert w.incident(incident_id)["status"] == "awaiting_choice" and choice["expires_at"]
    assert not w.prs
    assert api.answer_choice(choice["id"], "auto", w.user_id)
    claimed = H.claim()
    assert claimed and w.engine.handle_incident(claimed) == "pr_opened"


def test_ask_mode_never_times_out_but_auto_mode_does(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    w.fill_haiku(15)
    store.set_mode(w.user_id, "ask")
    incident_id, outcome = w.run_once()
    assert outcome == "awaiting_choice" and store.list_user_choices(w.user_id)[0]["expires_at"] is None
    assert w.engine.resume_expired_choices() == 0


def test_auto_mode_timeout_resumes_the_bug(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    w.fill_haiku(15)
    incident_id, outcome = w.run_once()
    choice = store.list_user_choices(w.user_id)[0]
    store._run("UPDATE fx_pending_choices SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (choice["id"],))
    assert w.engine.resume_expired_choices() == 1
    assert w.engine.handle_incident(H.claim()) == "pr_opened"


def test_user_can_send_a_bug_to_human_review(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    w.fill_haiku(15)
    incident_id, outcome = w.run_once()
    choice = store.list_user_choices(w.user_id)[0]
    assert not api.answer_choice(choice["id"], "auto", "someone-else")      # not your choice
    assert api.answer_choice(choice["id"], "review", w.user_id)
    assert not api.answer_choice(choice["id"], "auto", w.user_id)           # a choice can only be answered once
    assert w.engine.handle_incident(H.claim()) == "needs_human"
    assert "you chose human review" in w.bug(incident_id)["stop_reason"]


def test_quota_exhaustion_ends_in_review_with_an_admin_check(world, monkeypatch):
    monkeypatch.setattr("fixengine.notify._to_admins", lambda *a, **k: None)
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.WRONG_EDIT)], "sonnet": [reply(H.WRONG_EDIT)], "opus": [reply(H.WRONG_EDIT)]})
    w.cfg["quotas"].update({"sonnet": 1, "opus": 0, "haiku": 3})
    w.silence_warnings()
    w.cfg["router"]["give_up_penalty_inr"] = 500
    incident_id, outcome = w.run_once()
    bug = w.bug(incident_id)
    assert outcome == "needs_human" and "used up" in bug["stop_reason"]
    assert store.list_admin_actions()[0]["kind"] in ("auto_grant", "hold")


def test_engine_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("FIXENGINE_ENABLED", raising=False)
    import portal_worker
    portal_worker._ENGINE = None
    assert portal_worker._engine() is None
    monkeypatch.setenv("FIXENGINE_ENABLED", "1")
    assert orchestrator.enabled()


def test_unverified_fix_blocks_auto_merge(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]}, mode="auto")
    (w.repo / "tests" / "test_pricing.py").unlink()                      # no tests -> the sandbox can only check the build
    incident_id, outcome = w.run_once()
    assert outcome == "pr_opened" and w.incident(incident_id)["no_automerge"] == 1
    assert "NOT" in w.prs[0]["body"]
    assert incident_id not in [r["incident_id"] for r in portal_db.list_auto_prs()]


def test_verified_fix_in_auto_mode_stays_eligible_for_ci_gated_merge(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]}, mode="auto")
    incident_id, outcome = w.run_once()
    assert outcome == "pr_opened" and incident_id in [r["incident_id"] for r in portal_db.list_auto_prs()]


def test_reopen_after_review_requeues_the_incident(world):
    w = world(configured=False)
    incident_id, _ = w.run_once()
    assert not api.reopen_bug(w.bug(incident_id)["id"], "other")
    assert api.reopen_bug(w.bug(incident_id)["id"], w.user_id)
    assert H.claim()["incident_id"] == incident_id


def test_a_crashed_worker_does_not_burn_a_try(world):
    w = world(scripts={"groq": ["garbage"], "haiku": [reply(H.GOOD_EDIT)]})
    filler = store.create_bug(project_id=w.project_id, user_id=w.user_id, incident_id="old", fingerprint_json={"hash": "q"}, bug_class="easy", category="")
    aid = store.add_attempt(bug=filler, tier="sonnet", model="m", used_strong_diag=False, info_hash="z")      # never finished
    assert Guard(w.cfg).quota(w.user_id, "sonnet")["used"] == 1
    assert store.recover_pending(filler["id"]) == 1
    assert Guard(w.cfg).quota(w.user_id, "sonnet")["used"] == 0
