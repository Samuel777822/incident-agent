"""v3.1: the report box on PostgreSQL, one case = one fix, the project-level pause, the on-call engineer loop, the live investigator,
the push policy and the live check after a push. Fakes only: no network, no Docker, no money."""
import json
import re
from pathlib import Path

import pytest

import cases
import portal_db
from fixengine import adapters, config as fx_config, investigator, oncall, orchestrator, project_map, prompts, repo_context, sandbox, store
from tests import fx_helpers as H
from tests.test_fixengine_core import cfg, fx_db  # noqa: F401  (fixtures)
from test_web_app import web_env  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


# ============================================================================================ P0: the % crash can never come back
def test_pg_sql_doubles_literal_percent_and_converts_placeholders():
    out = portal_db.pg_sql("SELECT 1 FROM t WHERE a=? AND sig LIKE 'user_report:%' AND b LIKE ?")
    assert out == "SELECT 1 FROM t WHERE a=%s AND sig LIKE 'user_report:%%' AND b LIKE %s"


def _sql_literals():
    """Every string literal in our own code that looks like SQL."""
    found = []
    for path in ROOT.glob("*.py"):
        found += [(path.name, m.group(2)) for m in re.finditer(r"([rfbu]?)(\"\"\"[\s\S]*?\"\"\"|\"[^\"\n]*\"|'[^'\n]*')", path.read_text(encoding="utf-8"))]
    for path in (ROOT / "fixengine").glob("*.py"):
        found += [(path.name, m.group(2)) for m in re.finditer(r"([rfbu]?)(\"\"\"[\s\S]*?\"\"\"|\"[^\"\n]*\"|'[^'\n]*')", path.read_text(encoding="utf-8"))]
    return [(f, s) for f, s in found if re.search(r"\b(SELECT|INSERT INTO|UPDATE \w+ SET|DELETE FROM)\b", s)]


def test_every_sql_string_survives_postgres_placeholder_formatting():
    """Run each SQL string through the same conversion production uses, then through Python's %-formatting (what psycopg's
    placeholder parser does): a stray single % would raise here, exactly like it crashed the report box on Postgres."""
    checked = 0
    for name, sql in _sql_literals():
        converted = portal_db.pg_sql(sql)
        n = len(re.findall(r"(?<!%)%s", converted.replace("%%", "")))
        try:
            converted % tuple(["x"] * n)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"{name}: SQL would break on PostgreSQL ({exc}): {sql[:120]}")
        checked += 1
    assert checked > 100


def test_no_sql_literal_hard_codes_a_like_wildcard():
    bad = [(f, s[:100]) for f, s in _sql_literals() if re.search(r"LIKE\s+'[^']*%", s)]
    assert bad == [], f"use LIKE ? with the pattern as a parameter: {bad}"


# ============================================================================================ one case, one fix
def _project():
    return H.make_user_and_project(mode="auto")


def _ev(project_id, message, evidence, ts, signature):
    return portal_db.ingest_event(project_id, timestamp=ts, level="ERROR", message=message,
                                  traceback="[evidence] " + json.dumps(evidence) + "\nstack", signature=signature)


def _jobs(incident_id):
    conn = portal_db.get_connection()
    try:
        return [dict(r) for r in portal_db._execute(conn, "SELECT * FROM incident_jobs WHERE incident_id=?", (incident_id,)).fetchall()]
    finally:
        conn.close()


def test_one_broken_api_becomes_one_case_not_three_paid_diagnoses(fx_db):
    _uid, pid = _project()
    now = portal_db._now()
    leader, _ = _ev(pid, "GET https://bible-api.example/isaiah/1 failed with HTTP 500",
                    {"kind": "failed_request", "page": "https://site.example/isaiah/1", "request": "GET https://bible-api.example/isaiah/1", "status": 500},
                    now, "http:bible-api.example:500")
    text, _ = _ev(pid, "Failed to load chapter", {"kind": "ui_error_text", "page": "https://site.example/isaiah/1", "dom": "div#error"},
                  now, "ui_error_text:Failed to load chapter")
    net, _ = _ev(pid, "GET https://bible-api.example/psalms/2 failed with HTTP 500",
                 {"kind": "failed_request", "page": "https://site.example/psalms/2", "request": "GET https://bible-api.example/psalms/2", "status": 500},
                 now, "http:bible-api.example:500:psalms")
    listed = portal_db.list_incidents(pid)
    assert [i["id"] for i in listed] == [leader] and listed[0]["merged_count"] == 2
    for follower in (text, net):
        row = portal_db.get_incident_row(follower)
        assert row["status"] == "merged" and row["case_id"] == leader and _jobs(follower) == []
    assert len(_jobs(leader)) == 1
    assert {f["id"] for f in portal_db.case_followers(leader)} == {text, net}


def test_an_owner_report_joins_the_problem_the_monitor_just_saw(fx_db):
    _uid, pid = _project()
    now = portal_db._now()
    leader, _ = _ev(pid, "GET https://bible-api.example/isaiah/1 failed with HTTP 404",
                    {"kind": "failed_request", "page": "https://site.example/isaiah/1", "request": "GET https://bible-api.example/isaiah/1", "status": 404},
                    now, "http:bible-api.example:404")
    report, _ = _ev(pid, "[user report] Isaiah 1 is not loading", {"kind": "user_report", "owner_report": "Isaiah 1 is not loading"},
                    now, "user_report:abc")
    assert portal_db.get_incident_row(report)["case_id"] == leader


def test_unrelated_problems_stay_separate_cases(fx_db):
    _uid, pid = _project()
    now = portal_db._now()
    a, _ = _ev(pid, "TypeError in cart.js", {"kind": "js_error", "page": "https://site.example/cart"}, now, "js:cart")
    b, _ = _ev(pid, "GET https://pay.example/x failed with HTTP 500",
               {"kind": "failed_request", "page": "https://site.example/checkout", "request": "GET https://pay.example/x", "status": 500}, now, "http:pay")
    assert a != b and portal_db.get_incident_row(b)["case_id"] == ""
    assert len(portal_db.list_incidents(pid)) == 2


def test_two_reports_that_say_the_same_thing_are_one_case_but_different_ones_are_not():
    k1 = cases.key_for("user_report:1", "[user report] x", '[evidence] {"kind":"user_report","owner_report":"Isaiah chapter 1 does not load"}')
    k2 = cases.key_for("user_report:2", "[user report] x", '[evidence] {"kind":"user_report","owner_report":"isaiah chapter 1 is not loading at all"}')
    k3 = cases.key_for("user_report:3", "[user report] x", '[evidence] {"kind":"user_report","owner_report":"problem number 3 on the page"}')
    k4 = cases.key_for("user_report:4", "[user report] x", '[evidence] {"kind":"user_report","owner_report":"problem number 4 on the page"}')
    now = "2026-11-10T10:00:00+00:00"
    assert cases.related(k2, k1, new_ts=now, old_ts=now)
    assert not cases.related(k4, k3, new_ts=now, old_ts=now)


def test_same_signature_is_one_open_incident_and_the_index_exists(fx_db):
    _uid, pid = _project()
    a, _ = H.make_incident(pid, ts="2026-11-10T10:00:00Z"), None
    b = H.make_incident(pid, ts="2026-11-10T10:00:05Z")
    assert a == b and portal_db.get_incident_row(a)["occurrences"] == 2
    conn = portal_db.get_connection()
    try:
        names = {r[1] for r in conn.execute("PRAGMA index_list(incidents)").fetchall()}
    finally:
        conn.close()
    assert "idx_incidents_one_open" in names


def test_old_duplicate_open_incidents_are_merged_before_the_unique_index(fx_db):
    _uid, pid = _project()
    conn = portal_db.get_connection()
    try:
        conn.execute("DROP INDEX idx_incidents_one_open")
        for i, ts in enumerate(("2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00")):
            conn.execute("INSERT INTO incidents(id,project_id,signature,first_seen,last_seen,created_at) VALUES(?,?,?,?,?,?)",
                         (f"dup{i}", pid, "same", ts, ts, ts))
        conn.commit()
        portal_db._ensure_one_open_incident_index(conn)
    finally:
        conn.close()
    assert portal_db.get_incident_row("dup0")["status"] == "merged" and portal_db.get_incident_row("dup0")["case_id"] == "dup1"
    assert portal_db.get_incident_row("dup1")["status"] == "diagnosing"


def test_events_in_the_check_window_after_a_push_are_attached_not_new_work(fx_db):
    _uid, pid = _project()
    inc = H.make_incident(pid, ts="2026-11-10T10:00:00Z")
    portal_db.resolve_incident(inc, pid, "pushed")
    portal_db.start_check_window(inc, 300)
    again = H.make_incident(pid, ts="2026-11-10T10:01:00Z")
    assert again == inc and portal_db.get_incident_row(inc)["status"] == "resolved"
    portal_db.start_check_window(inc, 30)
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE incidents SET check_until='2000-01-01T00:00:00+00:00' WHERE id=?", (inc,))
        conn.commit()
    finally:
        conn.close()
    later = H.make_incident(pid, ts="2026-11-10T11:00:00Z")
    assert later != inc


def test_only_one_active_fix_per_project(fx_db):
    _uid, pid = _project()
    first = H.make_incident(pid, ts="2020-01-01T10:00:00Z")
    _ev(pid, "something else broke", {"kind": "js_error", "page": "https://site.example/other"}, "2020-01-01T10:00:01Z", "js:other")
    claimed = H.claim()
    assert claimed["incident_id"] == first
    assert H.claim() is None                     # the second waits while the first is being fixed
    portal_db.resolve_incident(first, pid, "done")
    assert H.claim() is not None


def test_report_box_same_text_twice_is_one_case(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    form = {"csrf": csrf, "text": "Isaiah chapter 1 is not loading", "page": "/isaiah/1"}
    _, h1, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form=form)
    _, h2, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form=form)
    assert "reported=1" in str(h1) and "reported=dup" in str(h2) and len(portal_db.list_incidents(project_id)) == 1
    _, _, page = _request(f"/projects/{project_id}?reported=dup", cookie=cookie)
    assert "Already working on this" in page.replace("&#x27;", "'")


def test_client_reply_goes_to_the_same_case_and_requeues_it(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the Send button does nothing"})
    inc = portal_db.list_incidents(project_id)[0]
    portal_db.resolve_incident(inc["id"], project_id, "pushed")
    status, headers, _ = _request(f"/projects/{project_id}/incidents/{inc['id']}/reply", method="POST", cookie=cookie,
                                  form={"csrf": csrf, "text": "it still does not work on Psalms"})
    assert status.startswith("30") and "replied=1" in str(headers)
    assert len(portal_db.list_incidents(project_id)) == 1 and portal_db.get_incident_row(inc["id"])["status"] == "diagnosing"
    assert store.client_replies(inc["id"]) == ["it still does not work on Psalms"]
    _, _, page = _request(f"/projects/{project_id}/incidents/{inc['id']}", cookie=cookie)
    assert "Reply to the agent" in page


# ============================================================================================ the project pause
def test_project_pause_text_is_plain_and_says_when(fx_db, cfg):
    from fixengine import guard as fx_guard
    uid, pid = H.make_user_and_project()
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id="i", fingerprint_json={"hash": "h"}, bug_class="medium", category="")
    aid = store.add_attempt(bug=bug, tier="sonnet", model="m", used_strong_diag=False, info_hash="x")
    store.finish_attempt(aid, result="fail", cost_inr=151.0)
    text = fx_guard.Guard(cfg).project_paused(pid)
    assert "continues by itself at" in text and "IST" in text and "used up or capped" not in text


# ============================================================================================ the on-call engineer: prompt and parsing
def test_new_answer_format_is_parsed_into_diagnosis_and_extras():
    raw = json.dumps({"understanding": "Isaiah 1 shows an error", "findings": ["api answers 404 for 'isaiah 1'"],
                      "root_cause": "app.js builds /isaiah 1 instead of /isaiah/1", "plan": "join with a slash",
                      "edits": [{"file_path": "app.js", "old_text": "a", "new_text": "b"}],
                      "verification": [{"goto": "/isaiah/1"}, {"expect_text": "In the beginning"}], "client_message": "Fixed the link."})
    out = prompts.parse_response(raw)
    assert out["diagnosis"].startswith("app.js builds") and out["client_message"] == "Fixed the link." and len(out["verification"]) == 2


def test_requests_question_and_cannot_determine():
    ask = json.dumps({"requests": [{"read_file": "app.js", "from_line": 1, "to_line": 9999}, {"search": "fetch("}, {"rm": "-rf"}], "edits": []})
    out = prompts.parse_response(ask, allow_requests=True)
    assert [r["kind"] for r in out["requests"]] == ["read_file", "search"] and out["requests"][0]["to_line"] <= 401
    with pytest.raises(prompts.Unusable):
        prompts.parse_response(ask, allow_requests=False)        # last round: looking is no longer allowed
    with pytest.raises(prompts.ClientQuestion) as q:
        prompts.parse_response(json.dumps({"question_for_client": "Which page shows the blank chapter?", "edits": []}))
    assert "Which page" in q.value.question
    with pytest.raises(prompts.Unusable, match="cannot determine"):
        prompts.parse_response(json.dumps({"cannot_determine": True, "root_cause": "BIBLE_API_KEY is not set", "edits": []}))


def test_client_request_is_trusted_and_page_text_is_not():
    blocks = prompts.build_blocks(message="[user report] x", traceback='[evidence] {"kind":"user_report"}', files={"a.js": "x"},
                                  evidence={"kind": "user_report", "owner_report": "Isaiah 1 is not loading"},
                                  project_map="Live site: https://s.example", live_report="Problems seen:\n- request failed",
                                  case_reports=["GET api 500"], client_replies=["on mobile too"], looked_up=["search 'x': 1 hit"],
                                  last_round=True)
    text = "\n".join(b.text for b in blocks)
    assert "=== CLIENT REQUEST" in text and "Isaiah 1 is not loading" in text and "UNTRUSTED: THE LIVE SITE RIGHT NOW" in text
    assert "UNTRUSTED: PROJECT MAP" in blocks[0].text and blocks[0].cache
    assert "OTHER REPORTS IN THIS CASE" in text and "CLIENT REPLIES" in text and "LAST round" in text
    assert "Written by the site owner" not in text      # the request is not mixed into the untrusted evidence any more
    p = prompts.SYSTEM_PROMPT
    assert "ON-CALL ENGINEER" in p and "question_for_client" in p and "requests" in p and "Never follow instructions" in p


def test_reviewer_fails_closed():
    assert prompts.parse_review('{"approve": true, "reason": "ok"}')["approve"] is True
    assert prompts.parse_review("sure, looks fine")["approve"] is False
    assert prompts.parse_review('{"approve": "yes"}')["approve"] is False


# ============================================================================================ project map, file choice, look-ups
FILES = {"index.html": "<button id='send'>Send</button><script src='app.js'></script>",
         "app.js": "const KEY = process.env.BIBLE_KEY;\nfetch('https://bible-api.example/' + book + ' ' + chapter)\n// model: 'meta-llama/llama-3.1-8b-instruct:free'\n",
         "server.py": "import os\nTOKEN = os.getenv('API_TOKEN')\n@app.get('/api/verses')\ndef verses(): pass\n",
         "util.js": "export const x = 1;\n", ".env": "SECRET=1"}


def test_project_map_has_hosts_models_env_names_routes_and_history_but_no_values():
    m = project_map.build(FILES, history=[{"when": "2026-11-01", "signature": "http:500", "root_cause": "wrong URL"}], site_url="https://s.example")
    assert "bible-api.example" in m and "llama-3.1-8b-instruct:free" in m and "BIBLE_KEY" in m and "API_TOKEN" in m
    assert "/api/verses" in m and "wrong URL" in m and "Live site: https://s.example" in m and "SECRET=1" not in m


def test_a_plain_words_report_reaches_the_right_file():
    hints = project_map.hint_words("the Send button does nothing", "/api/verses")
    chosen, _ = repo_context.select({k: v for k, v in FILES.items() if k != ".env"}, "", 400, hints=hints)
    assert list(chosen)[0] in ("index.html", "server.py")
    assert "util.js" not in list(chosen)[:2]


def test_lookups_read_search_and_check_models():
    assert "2|" in oncall.read_file(FILES, "app.js", 1, 2) and "no such file" in oncall.read_file(FILES, "nope.js", 1, 2)
    assert "app.js:2:" in oncall.search(FILES, "bible-api")
    from fixengine import model_catalog
    model_catalog.set_for_tests("openrouter", [{"id": "meta-llama/llama-3.3-70b-instruct:free", "created": 2}])
    try:
        out = oncall.check_model("meta-llama/llama-3.1-8b-instruct:free")
        assert "NOT served" in out and "llama-3.3-70b-instruct:free" in out
    finally:
        model_catalog.clear()
    pages = []
    res = oncall.run_requests([{"kind": "open_page", "value": "/isaiah/1"}, {"kind": "open_page", "value": "/a"}, {"kind": "open_page", "value": "/b"}],
                              files=FILES, site_url="https://s.example/", investigate_fn=lambda url, steps: pages.append(url) or {"ok": True, "url": url})
    assert pages == ["https://s.example/isaiah/1", "https://s.example/a"] and "no more live page visits" in res[2]
    assert "not known" in oncall.run_requests([{"kind": "open_page", "value": "/"}], files=FILES)[0]


# ============================================================================================ the live investigator
def test_investigator_refuses_private_addresses():
    for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://localhost:8099/run", "file:///etc/passwd"):
        assert investigator.investigate(url)["mode"] == "refused"


def test_steps_are_whitelisted_and_pages_stay_on_the_clients_site():
    assert investigator.clean_steps([{"goto": "/"}, {"evaluate": "fetch('x')"}, {"click": "#a"}]) == [{"goto": "/"}, {"click": "#a"}]
    assert investigator.page_url("https://s.example", "/isaiah/1") == "https://s.example/isaiah/1"
    assert investigator.page_url("https://s.example/", "https://evil.example/x") == "https://s.example/"


def test_docker_run_has_network_memory_limit_and_reads_one_json_line(monkeypatch):
    monkeypatch.setattr(investigator, "_safe", lambda url: url)
    cfg = fx_config.load()
    seen = {}

    def fake_exec(argv, timeout, cwd=None, env=None):
        seen["argv"] = argv
        return 0, "noise\nFXRESULT " + json.dumps({"ok": True, "mode": "browser", "status": 200}) + "\n", False
    out = investigator.run_in_docker({"url": "https://s.example/", "steps": [{"click": "#x"}, {"bad": 1}]}, cfg, exec_fn=fake_exec)
    argv = seen["argv"]
    assert out["ok"] and argv[argv.index("--network") + 1] == "fx-investigate" and argv[argv.index("--memory") + 1] == "1g"
    assert "--cap-drop" in argv and "--read-only" in argv


def test_compare_before_and_after():
    broken = {"ok": True, "status": 200, "failed_requests": [{"host": "api.x", "path": "/isaiah/1", "status": 404, "method": "GET"}],
              "visible_errors": ["Failed to load chapter"]}
    clean = {"ok": True, "status": 200}
    worse = {"ok": True, "status": 500, "page_errors": ["TypeError: a", "TypeError: b"]}
    assert investigator.compare(broken, clean) == "fixed"
    assert investigator.compare(broken, broken) == "same"
    assert investigator.compare(clean, worse) == "worse"
    assert "request failed: GET api.x/isaiah/1 -> HTTP 404" in investigator.format_report(broken)


def test_fallback_is_an_honest_plain_fetch(monkeypatch):
    monkeypatch.setattr(investigator, "_safe", lambda url: url)
    monkeypatch.setenv("FIXENGINE_SANDBOX_MODE", "remote")
    monkeypatch.delenv("FIXENGINE_SANDBOX_URL", raising=False)
    out = investigator.investigate("https://s.example/", fetcher=lambda url: (200, "<title>Bible</title><p>Failed to load chapter.</p>", url))
    assert out["mode"] == "fetch" and "could not open your site in a real browser" in out["note"] and out["title"] == "Bible"


# ============================================================================================ the whole loop for an owner's report
class _GH:
    def __init__(self):
        self.calls = []

    def push_fix_branch(self, project, *, bug_id, new_files, title):
        self.calls.append("push_branch")
        return {"branch": "agent-daemon/fix-x", "head_sha": "h" * 40, "base_sha": "b" * 40}

    def checks_state(self, project, sha):
        return "success"

    def fast_forward_base(self, project, head_sha, base_sha):
        self.calls.append("fast_forward")
        return "ok"

    def delete_branch(self, project, branch):
        pass

    def open_pr_for_branch(self, project, *, branch, title, body):
        self.calls.append("pr")
        return {"url": "https://github.com/acme/shop/pull/9", "number": 9, "branch": branch}

    def revert_files(self, project, *, base_sha, paths, title):
        self.calls.append("revert")
        return "ok"


def _report_world(tmp_path, monkeypatch, scripts, live):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
    monkeypatch.setenv("AGENT_DIRECT_PUSH", "1")
    portal_db.init_db()
    cfg = fx_config.load()
    cfg["sandbox"]["mode"] = "local_unsafe"
    cfg["warn_every_use"]["opus"] = False
    cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
    repo = H.make_repo(tmp_path)
    uid, pid = H.make_user_and_project(mode="auto")
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE projects SET app_url='https://site.example/' WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()
    import site_probe
    monkeypatch.setattr(site_probe, "safe_url", lambda url: url)
    fake = {t: adapters.FakeAdapter(t, cfg, scripts.get(t)) for t in fx_config.TIERS}
    gh = _GH()
    looked = []

    def investigate(url, steps=None):
        looked.append((url, steps))
        return live(len(looked))
    engine = orchestrator.Engine(cfg, adapters=fake, runner=sandbox.LocalUnsafeRunner(cfg), repo_provider=H.repo_provider(repo),
                                 commits_provider=lambda p: "", gh=gh, investigate=investigate)
    portal_db.ingest_event(pid, timestamp="2020-01-01T10:00:00Z", level="ERROR", message="[user report] the discount is wrong",
                           traceback='[evidence] {"kind": "user_report", "owner_report": "the 10% discount shows the wrong price", "page": "/cart"}\n',
                           signature="user_report:1")
    return engine, fake, gh, looked, pid


BROKEN = {"ok": True, "mode": "browser", "status": 200, "visible_errors": ["Error: negative price computed"]}
CLEAN = {"ok": True, "mode": "browser", "status": 200}


def test_owner_report_starts_with_high_mode_looks_first_then_fixes(tmp_path, monkeypatch):
    look = json.dumps({"understanding": "wrong price", "requests": [{"search": "pct / 10"}], "edits": []})
    fix = json.dumps({"root_cause": "pricing.py divides by 10", "plan": "divide by 100", "edits": [H.GOOD_EDIT],
                      "client_message": "The discount used the wrong maths; it is fixed.", "verification": [{"goto": "/cart"}]})
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch, {"sonnet": [look, fix]}, lambda n: BROKEN)
    claimed = H.claim()
    outcome = engine.handle_incident(claimed)
    row = portal_db.get_incident_row(claimed["incident_id"])
    assert outcome == "github_testing", (outcome, row.get("stage_detail"))
    bug = store.get_bug_by_incident(claimed["incident_id"])
    attempts = store.list_attempts(bug["id"])
    assert [a["tier"] for a in attempts if a["result"] != "review"][0] == "sonnet"       # no blind climb from the free model
    assert looked and looked[0][0] == "https://site.example/cart"                          # it opened the reported page first
    second_prompt = fake["sonnet"].seen_prompts[1]
    assert "RESULTS OF YOUR REQUESTS" in second_prompt and "pricing.py:2:" in second_prompt
    assert "CLIENT REQUEST" in fake["sonnet"].seen_prompts[0]
    # GitHub is green and the sandbox PROVED it (a failing test now passes): pushed, then the live site is checked.
    engine.process_proofs()
    assert "fast_forward" in gh.calls and store.get_bug(bug["id"])["status"] == "verifying"
    row = portal_db.get_incident_row(claimed["incident_id"])
    assert "Check again in 30 seconds" in row["stage_detail"] and row["check_until"]
    state = store.gh_state(bug["id"])
    state["verify"]["since"] = 0
    store.save_gh_state(bug["id"], state)
    looked.clear()
    engine.investigate = lambda url, steps=None: looked.append((url, steps)) or CLEAN
    engine.process_proofs()
    assert store.get_bug(bug["id"])["status"] == "resolved" and looked[0][1] == [{"goto": "/cart"}]
    assert "Verified on your live site" in portal_db.get_incident_row(claimed["incident_id"])["live_result"]


def test_unproven_live_fix_is_held_for_review_when_the_reviewer_says_no(tmp_path, monkeypatch):
    fix = json.dumps({"root_cause": "x", "plan": "y", "edits": [H.GOOD_EDIT]})
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch,
                                                  {"sonnet": [fix], "opus": ['{"approve": false, "reason": "not grounded in the evidence"}'],
                                                   "haiku": ['{"approve": false, "reason": "no"}']}, lambda n: BROKEN)
    claimed = H.claim()
    win = {"level": "tests_pass_not_reproduced", "tier": "sonnet", "diff": "-a\n+b", "diagnosis": "x"}
    bug = store.create_bug(project_id=pid, user_id=store.get_project_row(pid)["user_id"], incident_id=claimed["incident_id"],
                           fingerprint_json={"hash": "h"}, bug_class="medium", category="user_report")
    reason = engine._push_policy(claimed, store.get_project_row(pid), bug, win, {"kind": "user_report", "live_text": "", "reports": []})
    assert "reviewer did not approve" in reason and "not grounded" in reason
    assert any(a["result"] == "review" for a in store.list_attempts(bug["id"]))
    assert engine._push_policy(claimed, store.get_project_row(pid), bug, {**win, "level": "journey_fixed"}, {"kind": "user_report"}) == ""
    assert engine._push_policy(claimed, store.get_project_row(pid), bug, win, {"kind": ""}) == ""     # server crashes: unchanged


def _verifying_bug(engine, pid, claimed, state):
    project = store.get_project_row(pid)
    bug = store.create_bug(project_id=pid, user_id=project["user_id"], incident_id=claimed["incident_id"],
                           fingerprint_json={"hash": "h"}, bug_class="medium", category="user_report")
    store.save_gh_state(bug["id"], {"verify": {"since": 0, "round": 1}, "base_sha": "b" * 40, "files": ["pricing.py"],
                                    "live_before": {**BROKEN, "page": "https://site.example/cart", "steps_used": []}, **state})
    store.update_bug(bug["id"], status="verifying")
    return bug


def test_live_check_after_push_says_verified(tmp_path, monkeypatch):
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch, {}, lambda n: CLEAN)
    claimed = H.claim()
    bug = _verifying_bug(engine, pid, claimed, {})
    engine.process_proofs()
    assert store.get_bug(bug["id"])["status"] == "resolved"
    assert portal_db.get_incident_row(claimed["incident_id"])["live_result"].startswith("Verified on your live site")


def test_live_check_reverts_when_the_site_got_worse(tmp_path, monkeypatch):
    worse = {"ok": True, "mode": "browser", "status": 500, "page_errors": ["TypeError: a", "TypeError: b"], "visible_errors": ["Error 500"]}
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch, {}, lambda n: worse)
    claimed = H.claim()
    bug = _verifying_bug(engine, pid, claimed, {})
    engine.process_proofs()
    assert "revert" in gh.calls and store.get_bug(bug["id"])["status"] == "needs_human"
    assert "UNDID" in portal_db.get_incident_row(claimed["incident_id"])["live_result"]


def test_live_check_still_failing_goes_back_to_the_model_once(tmp_path, monkeypatch):
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch, {}, lambda n: BROKEN)
    claimed = H.claim()
    bug = _verifying_bug(engine, pid, claimed, {})
    engine.process_proofs()
    assert store.get_bug(bug["id"])["status"] == "open"
    row = portal_db.get_incident_row(claimed["incident_id"])
    assert row["status"] == "diagnosing" and "Still failing on your live site" in row["stage_detail"]


def test_question_for_the_client_parks_the_case(tmp_path, monkeypatch):
    q = json.dumps({"question_for_client": "Which product shows the wrong price?", "edits": []})
    engine, fake, gh, looked, pid = _report_world(tmp_path, monkeypatch, {"sonnet": [q]}, lambda n: BROKEN)
    claimed = H.claim()
    outcome = engine.handle_incident(claimed)
    if outcome not in ("awaiting_client",):
        pytest.skip(f"the local sandbox cannot run on this machine ({outcome})")
    row = portal_db.get_incident_row(claimed["incident_id"])
    assert row["status"] == "awaiting_choice" and row["live_result"].startswith("QUESTION: Which product")


def test_bench_has_web_cases():
    names = {p.name for p in (ROOT / "bench" / "web_cases").iterdir() if p.is_dir()}
    assert {"broken_api", "dead_button", "retired_free_model", "vague_report", "duplicate_flood"} <= names
    for name in names:
        case = json.loads((ROOT / "bench" / "web_cases" / name / "case.json").read_text(encoding="utf-8"))
        assert case["expect"] and case["events"]
