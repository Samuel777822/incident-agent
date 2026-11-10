"""v3.2: stop the ladder when the owner must act, real tries only in the hourly limit, sign-in evidence, the site audit,
the live-site address setting. Fakes only."""
import json

import portal_db
import site_audit
from fixengine import adapters, config as fx_config, investigator, orchestrator, prompts, sandbox, store
from tests import fx_helpers as H
from tests.test_fixengine_core import cfg, fx_db  # noqa: F401  (fixtures)
from test_web_app import web_env  # noqa: F401  (fixture)

OWNER = json.dumps({"understanding": "Google sign-in returns to the login page",
                    "root_cause": "the redirect URI sent by the code is not allowed in the Google console",
                    "cannot_determine": True, "edits": [], "client_message": "Your code is right; Google rejects the return address.",
                    "owner_steps": ["In Google Cloud Console > Credentials > your OAuth client, add https://site.example/auth/google/callback to Authorized redirect URIs",
                                    "Wait a minute, then try Continue with Google again"]})


def _world(tmp_path, monkeypatch, scripts):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
    portal_db.init_db()
    c = fx_config.load()
    c["sandbox"]["mode"] = "local_unsafe"
    c["warn_every_use"]["opus"] = False
    c["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
    repo = H.make_repo(tmp_path)
    _uid, pid = H.make_user_and_project(mode="pr")
    fake = {t: adapters.FakeAdapter(t, c, scripts.get(t)) for t in fx_config.TIERS}
    engine = orchestrator.Engine(c, adapters=fake, runner=sandbox.LocalUnsafeRunner(c), repo_provider=H.repo_provider(repo),
                                 commits_provider=lambda p: "", pr_opener=lambda project, **kw: {})
    return engine, fake, pid


def test_owner_action_is_parsed_with_its_steps():
    try:
        prompts.parse_response(OWNER)
    except prompts.OwnerAction as exc:
        assert len(exc.steps) == 2 and "Authorized redirect URIs" in exc.steps[0] and str(exc).startswith("cannot determine:")
    else:
        raise AssertionError("expected OwnerAction")
    assert "owner_steps" in prompts.SYSTEM_PROMPT and "redirect_uri" in prompts.SYSTEM_PROMPT and "SameSite" in prompts.SYSTEM_PROMPT


def test_a_cause_outside_the_code_stops_the_ladder_and_tells_the_owner(tmp_path, monkeypatch):
    engine, fake, pid = _world(tmp_path, monkeypatch, {"groq": ["garbage"], "haiku": [OWNER], "sonnet": [OWNER], "opus": [OWNER]})
    inc = H.make_incident(pid)
    outcome = engine.handle_incident(H.claim())
    assert outcome == "needs_owner"
    assert fake["haiku"].calls == 1 and fake["sonnet"].calls == 1 and fake["opus"].calls == 0      # one cheap try, one confirmation, stop
    row = portal_db.get_incident_row(inc)
    assert row["live_result"].startswith("NEEDS YOU") and "1. In Google Cloud Console" in row["live_result"]
    assert row["stage"] == "needs_you" and row["status"] == "needs_human"
    import live_status
    assert live_status.incident_view(row, "auto")["headline"].startswith("Needs you")


def test_only_real_tries_count_toward_the_hourly_limit(fx_db, cfg):
    uid, pid = H.make_user_and_project()
    bug = store.create_bug(project_id=pid, user_id=uid, incident_id="i", fingerprint_json={"hash": "h"}, bug_class="medium", category="")
    for result in ["system_fault"] * 40 + ["review"] * 5 + ["fail"] * 3:
        aid = store.add_attempt(bug=bug, tier="haiku", model="m", used_strong_diag=False, info_hash=store.new_id())
        store.finish_attempt(aid, result=result)
    assert store.tries_last_hour(uid) == 3 and 55 <= store.minutes_until_try_frees(uid) <= 61
    assert cfg["caps"]["tries_per_hour_per_user"] == 30 and cfg["tokens"]["context_tokens"] <= 20000


def test_sign_in_evidence_reaches_the_model_and_the_button_is_clicked():
    steps = investigator.default_steps("Continue with Google, I pick an account and it sends me back to the login screen")
    assert steps[0] == {"click": "text=/Google/i"}
    text = investigator.format_report({"ok": True, "mode": "browser", "url": "https://s.example/login", "status": 200,
                                       "navigations": [{"host": "s.example", "path": "/login"}, {"host": "accounts.google.com", "path": "/o/oauth2/v2/auth"}],
                                       "url_errors": ["s.example/login error=OAuthCallback"],
                                       "oauth": {"provider": "accounts.google.com", "redirect_uri": "http://localhost:3000/api/auth/callback", "has_state": False}})
    assert "redirect_uri=http://localhost:3000/api/auth/callback" in text and "state=NO" in text
    assert "s.example/login -> accounts.google.com/o/oauth2/v2/auth" in text and "error in the address" in text


REPORT = {"ok": True, "mode": "browser", "status": 200, "ms": 900,
          "failed_requests": [{"host": "api.site.example", "path": "/v1/verses", "method": "GET", "status": 500, "type": "fetch", "body": "boom"},
                              {"host": "api.site.example", "path": "/v1/books", "method": "GET", "status": 500, "type": "fetch", "body": "boom"},
                              {"host": "cdn.ads.example", "path": "/t.js", "method": "GET", "status": 0, "type": "script", "body": ""},
                              {"host": "site.example", "path": "/logo.png", "method": "GET", "status": 404, "type": "image", "body": ""}],
          "page_errors": ["TypeError: verses is undefined"]}


def test_audit_turns_real_breakage_into_events_and_ignores_noise():
    events = site_audit.events_from(REPORT, "https://site.example/")
    assert [e["evidence"]["kind"] for e in events] == ["failed_request", "js_error"]          # one per failing API folder, no ads, no images
    assert "found by the site audit" in events[0]["message"]


def test_audit_on_connect_opens_one_case_and_is_not_repeated_today(fx_db, monkeypatch):
    import site_probe
    monkeypatch.setattr(site_probe, "safe_url", lambda url: url)
    _uid, pid = H.make_user_and_project(mode="auto")
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE projects SET app_url='https://site.example/' WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()
    visits = []
    look = lambda url, steps=None: visits.append(url) or REPORT
    assert site_audit.sweep(look) == 1 and visits == ["https://site.example/"]
    found = portal_db.list_incidents(pid)
    assert len(found) == 1 and found[0]["merged_count"] == 1                 # the API failure and the JS error: ONE case
    assert site_audit.sweep(look) == 0 and len(visits) == 1                  # not again today
    store.set_flag(f"audit_next:{pid}", "")
    assert site_audit.audit_one({"id": pid, "app_url": "https://site.example/"}, lambda u, s=None: {"ok": True, "mode": "fetch"}) == 0
    assert store.get_flag(f"audit_next:{pid}") != ""                         # no browser: nothing invented, retry in an hour


def test_live_site_address_can_be_set_and_is_learned_from_a_report(web_env, monkeypatch):
    import site_probe
    from test_v3_web import _setup
    from test_web_app import _request
    monkeypatch.setattr(site_probe, "safe_url", lambda url: url if url.startswith("https://") and "localhost" not in url else "")
    _user, csrf, cookie, project_id = _setup()
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Live site address" in page and "Not set." in page
    _, headers, _ = _request(f"/projects/{project_id}/site-url", method="POST", cookie=cookie, form={"csrf": csrf, "app_url": "http://localhost:3000"})
    assert "reported=badsite" in str(headers)
    _, headers, _ = _request(f"/projects/{project_id}/site-url", method="POST", cookie=cookie, form={"csrf": csrf, "app_url": "my-site.example/app?x=1"})
    assert "reported=site" in str(headers) and portal_db.get_project_any(project_id)["app_url"] == "https://my-site.example/"
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE projects SET app_url='' WHERE id=?", (project_id,))
        conn.commit()
    finally:
        conn.close()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie,
             form={"csrf": csrf, "text": "Continue with Google sends me back to login", "page": "https://other.example/login"})
    assert portal_db.get_project_any(project_id)["app_url"] == "https://other.example/"
