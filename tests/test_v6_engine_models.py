"""v6 (13 Nov 2026): two engineers only. Haiku is the Engineer, Sonnet the Lead engineer; Opus is never used (cost)."""
from fixengine import orchestrator


def test_the_engine_uses_the_engineer_then_the_lead_and_never_opus():
    assert orchestrator.Engine.AGENT_TIERS == ("haiku", "sonnet")
    assert all("opus" not in order for order in orchestrator.Engine.REVIEW_ORDER.values())
    assert "Extra" not in " ".join(orchestrator.Engine.STAGE_TEXT.values())


def test_still_broken_escalates_to_the_lead_and_stops_there(monkeypatch):
    import web_app
    from fixengine import store

    class Bug(dict):
        pass
    rows = {"a": [{"tier": "haiku", "result": "fail"}], "b": [{"tier": "sonnet", "result": "fail"}], "c": []}
    monkeypatch.setattr(store, "list_attempts", lambda bug_id: rows[bug_id])
    assert web_app._next_tier({"id": "a"}) == "sonnet"
    assert web_app._next_tier({"id": "b"}) == ""            # after the Lead engineer there is no stronger model
    assert web_app._next_tier({"id": "c"}) == "sonnet"
