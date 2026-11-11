"""The independent reviewer: a different model checks a fix that no test could prove. It is OUR quality check:
it never uses the customer's tries, it works through OpenRouter like the engineer, and when it cannot run, the admins hear why."""
import json

from fixengine import orchestrator, store
from tests import fx_helpers as H
from tests.test_fixengine_core import cfg, fx_db  # noqa: F401  (fixtures)
from tests.test_v4_agent import OkRunner

CLAIMED = {"incident_id": "i1", "project_id": "p1",
           "first_event": {"traceback": "[evidence] " + json.dumps({"kind": "user_report", "owner_report": "the chatbot fails"}) + "\n"}}
WIN = {"tier": "haiku", "diff": "--- a/api.mjs\n+++ b/api.mjs\n-model: 'x:free'\n+models: ['openrouter/free']\n", "diagnosis": "one free model"}


class Reviewer:
    def __init__(self, tier, answer=None, error=None):
        self.model, self.answer, self.error, self.effort, self.calls = f"anthropic/claude-{tier}", answer, error, "high", []

    def complete(self, messages, tools, **kw):
        self.calls.append({"messages": messages, "tools": tools, "effort": self.effort, **kw})
        if self.error:
            raise RuntimeError(self.error)
        return {"message": {"content": self.answer}, "usage": {"prompt_tokens": 900, "completion_tokens": 60, "cost": 0.002}}


def _engine(cfg, reviewers):
    return orchestrator.Engine(cfg, adapters={}, runner=OkRunner(), repo_provider=lambda p: None,
                               agent_transport=lambda tier: reviewers[tier])


def _bug():
    uid, pid = H.make_user_and_project()
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id="i1", fingerprint_json={"hash": "h"}, bug_class="easy", category="")
    return uid, pid, bug


def test_a_review_never_uses_the_customers_tries_even_when_they_have_none(fx_db, cfg):
    uid, pid, bug = _bug()
    for _ in range(30):                                     # every Normal and High try of the month is used
        a = store.add_attempt(bug=bug, tier="haiku", model="m", used_strong_diag=False, info_hash="x")
        store.finish_attempt(a, result="fail")
    for _ in range(6):
        a = store.add_attempt(bug=bug, tier="sonnet", model="m", used_strong_diag=False, info_hash="y")
        store.finish_attempt(a, result="fail")
    reviewers = {"sonnet": Reviewer("sonnet", '{"approve": true, "reason": "fixes the cause"}'), "opus": Reviewer("opus", "{}")}
    verdict = _engine(cfg, reviewers)._independent_review(CLAIMED, {"user_id": uid}, bug, WIN, {"kind": "user_report"})
    assert verdict == {"approve": True, "reason": "fixes the cause"}
    assert store.tier_used(uid, "sonnet") == 6                # the review did not count as a try
    call = reviewers["sonnet"].calls[0]
    assert call["tools"] is None and call["effort"] == "" and "the chatbot fails" in call["messages"][1]["content"]


def test_the_reviewer_is_a_different_model_and_skips_a_mode_an_admin_paused(fx_db, cfg):
    uid, pid, bug = _bug()
    store.set_flag("pause_sonnet", "1")
    reviewers = {"sonnet": Reviewer("sonnet", '{"approve": true, "reason": "x"}'),
                 "opus": Reviewer("opus", '{"approve": false, "reason": "it hides the error"}')}
    verdict = _engine(cfg, reviewers)._independent_review(CLAIMED, {"user_id": uid}, bug, WIN, {})
    assert verdict["reason"] == "it hides the error" and reviewers["sonnet"].calls == []
    rows = [a for a in store.list_attempts(bug["id"]) if a["result"] == "review"]
    assert len(rows) == 1 and rows[0]["tier"] == "opus" and rows[0]["diagnosis"].startswith("rejected:")


def test_when_no_reviewer_answers_the_reason_is_specific_and_admins_hear_once(fx_db, cfg, monkeypatch):
    sent = []
    monkeypatch.setattr("fixengine.notify._to_admins", lambda subject, body="", kind="": sent.append(body))
    uid, pid, bug = _bug()
    reviewers = {"sonnet": Reviewer("sonnet", error="OpenRouter says the account has no credit left (HTTP 402)"),
                 "opus": Reviewer("opus", error="OpenRouter did not answer")}
    engine = _engine(cfg, reviewers)
    verdict = engine._independent_review(CLAIMED, {"user_id": uid}, bug, WIN, {})
    engine._independent_review(CLAIMED, {"user_id": uid}, bug, WIN, {})
    assert verdict["approve"] is False and "no credit left" in verdict["reason"]
    assert len(sent) == 1 and "no credit left" in sent[0]
