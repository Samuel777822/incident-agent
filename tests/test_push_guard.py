"""Architecture v3: push guard, mixed-language repos, live stages, project slots, add-ons, admins and the architecture pages.

Everything runs offline: GitHub calls are stand-ins, the sandbox is either a fake runner or the local_unsafe runner on tiny repos.
"""
import contextlib
import hashlib
import hmac
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

import notifications
import plans
import portal_db
import push_watch
import web_app
from fixengine import adapters, config as fx_config, orchestrator, sandbox, store, validator
from tests import fx_helpers as H
from test_web_app import _request, web_env  # noqa: F401  (fixture)


def put(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def make_session(email):
    user_id = portal_db.create_user(email, "hash")
    csrf = "csrf-" + user_id[:8]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def project_for(user_id, **extra):
    return portal_db.create_project(user_id, name="Shop", repo_owner="demo", repo_name="shop", branch="main", mode=extra.pop("mode", "pr"),
                                    token_ciphertext="cipher", ingest_key_hash=hashlib.sha256(user_id.encode()).hexdigest(),
                                    ai_consent_at="2026-01-01T00:00:00+00:00", **extra)


# ------------------------------------------------------------------------------------------------ mixed-language repos
def test_every_stack_in_a_mixed_repo_is_found(tmp_path):
    put(tmp_path, {"backend/requirements.txt": "", "backend/app.py": "x = 1\n", "backend/templates/a.html": "{% if x %}<div>{% endif %}",
                   "frontend/package.json": json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"typescript": "5"}}),
                   "frontend/tsconfig.json": "{}", "frontend/src/a.ts": "let a: number = 1\n", "index.html": "<p>hi</p>"})
    p = sandbox.detect_profiles(tmp_path)
    assert isinstance(p, sandbox.StackSet)
    assert p.labels() == ["Python (backend)", "TypeScript (frontend)", "HTML/CSS/JS site"]
    static = p.parts[2]
    assert "--exclude backend" in static.build and "--exclude frontend" in static.build    # never re-checks the other stacks
    assert p.has_tests and "3 projects found" in p.notes[0]


def test_single_language_repo_is_exactly_the_old_profile(tmp_path):
    put(tmp_path, {"app.py": "x = 1\n", "test_app.py": "def test_x(): pass\n", "requirements.txt": ""})
    assert sandbox.detect_profiles(tmp_path) == sandbox.detect_profile(tmp_path)


def test_java_service_next_to_a_node_app(tmp_path):
    put(tmp_path, {"api/pom.xml": "<project/>", "api/src/main/java/A.java": "class A {}",
                   "web/package.json": json.dumps({"scripts": {"build": "vite build"}})})
    p = sandbox.detect_profiles(tmp_path)
    assert sorted(x.language for x in p.parts) == ["java", "node"]


class FakeRunner:
    def __init__(self, results):
        self.results, self.seen = results, []

    def run(self, root, profile):
        self.seen.append(profile.language)
        return self.results[profile.language]


def _ok(name="test"):
    return sandbox.SandboxResult(passed=True, tests_ran=name == "test", phases=[sandbox.PhaseResult(name, True, 0, 0.1, "ok")], failing=0)


def _bad(name="test", out="1 failed"):
    return sandbox.SandboxResult(passed=False, tests_ran=name == "test", phases=[sandbox.PhaseResult(name, False, 1, 0.1, out)],
                                 failing=1 if name == "test" else None, output=f"[{name}] exit 1\n{out}")


def test_repo_is_green_only_when_every_stack_passes(tmp_path):
    put(tmp_path, {"backend/requirements.txt": "", "backend/app.py": "x=1\n", "frontend/package.json": json.dumps({"scripts": {"test": "x"}})})
    prof = sandbox.detect_profiles(tmp_path)
    runner = FakeRunner({"python": _ok(), "node": _bad("test", "TypeError: total is not a function")})
    res = sandbox.run_profile(runner, tmp_path, prof)
    assert runner.seen == ["python", "node"] and not res.passed and res.failing == 1
    assert "[JavaScript/TypeScript (frontend)]" in res.output and "TypeError" in res.output
    rows = sandbox.stack_summary(prof, res)
    assert rows[0]["ok"] is True and rows[1] == {"label": "JavaScript/TypeScript (frontend)", "language": "node", "ok": False, "phase": "test"}


def test_static_checker_skips_excluded_folders(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("static_check", Path(__file__).resolve().parent.parent / "sandbox" / "static_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    put(tmp_path, {"index.html": "<p>ok</p>", "frontend/public/index.html": "<div><span></div>", "templates/x.html": "{% if a %}<div>"})
    errors, _ = mod.check_site(tmp_path, None, ["frontend"])
    assert errors == []
    errors, _ = mod.check_site(tmp_path, None, [])
    assert any("frontend" in e[0] for e in errors)                                     # the broken file IS seen without --exclude


# ------------------------------------------------------------------------------------------------ webhook intake
def _hook_project(tmp_path, monkeypatch, watch="both"):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id, watch_mode=watch)
    secret = "s3cret-for-tests"
    portal_db.set_project_webhook(project_id, "77", push_watch._encrypt(secret))
    return user_id, project_id, secret


def _push_payload(sha="a" * 40, ref="refs/heads/main", message="update checkout"):
    return {"ref": ref, "after": sha, "head_commit": {"id": sha, "message": message, "author": {"username": "dev"}},
            "pusher": {"name": "dev"}}


def _signed(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signed_push_webhook_queues_one_check(web_env, tmp_path, monkeypatch):
    _user, project_id, secret = _hook_project(tmp_path, monkeypatch)
    body = json.dumps(_push_payload()).encode()
    headers = {"HTTP_X_GITHUB_EVENT": "push", "HTTP_X_HUB_SIGNATURE_256": _signed(secret, body)}
    status, _, out = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=body, headers=headers)
    assert status.startswith("202") and json.loads(out)["queued"] is True
    again = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=body, headers=headers)
    assert json.loads(again[2])["queued"] is False                                     # the same commit is never queued twice
    checks = portal_db.list_push_checks(project_id)
    assert len(checks) == 1 and checks[0]["sha"] == "a" * 40 and checks[0]["source"] == "webhook"


def test_webhook_rejects_bad_signatures_and_ignores_other_branches(web_env, tmp_path, monkeypatch):
    _user, project_id, secret = _hook_project(tmp_path, monkeypatch)
    body = json.dumps(_push_payload()).encode()
    bad = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=body,
                   headers={"HTTP_X_GITHUB_EVENT": "push", "HTTP_X_HUB_SIGNATURE_256": "sha256=" + "0" * 64})
    assert bad[0].startswith("401")
    other = json.dumps(_push_payload(ref="refs/heads/feature")).encode()
    st, _, out = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=other,
                          headers={"HTTP_X_GITHUB_EVENT": "push", "HTTP_X_HUB_SIGNATURE_256": _signed(secret, other)})
    assert st.startswith("202") and "not the tracked branch" in out
    fix = json.dumps(_push_payload(ref="refs/heads/agent-daemon/fix-1")).encode()
    st, _, out = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=fix,
                          headers={"HTTP_X_GITHUB_EVENT": "push", "HTTP_X_HUB_SIGNATURE_256": _signed(secret, fix)})
    assert "not the tracked branch" in out and portal_db.list_push_checks(project_id) == []
    ping = b"{}"
    st, _, out = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=ping,
                          headers={"HTTP_X_GITHUB_EVENT": "ping", "HTTP_X_HUB_SIGNATURE_256": _signed(secret, ping)})
    assert st.startswith("200") and "pong" in out


def test_runtime_only_projects_ignore_pushes(web_env, tmp_path, monkeypatch):
    _user, project_id, secret = _hook_project(tmp_path, monkeypatch, watch="runtime")
    body = json.dumps(_push_payload()).encode()
    st, _, out = _request(f"/webhooks/github/{project_id}", method="POST", raw_body=body,
                          headers={"HTTP_X_GITHUB_EVENT": "push", "HTTP_X_HUB_SIGNATURE_256": _signed(secret, body)})
    assert "push checks are off" in out and portal_db.list_push_checks(project_id) == []


def test_poller_queues_new_heads_only(web_env, tmp_path, monkeypatch):
    _user, project_id, _secret = _hook_project(tmp_path, monkeypatch)
    monkeypatch.setattr(push_watch, "branch_head", lambda p: {"sha": "b" * 40, "message": "m", "author": "dev"})
    assert push_watch.poll_once() == 1 and push_watch.poll_once() == 0


# ------------------------------------------------------------------------------------------------ running a check
def _snapshot(repo):
    @contextlib.contextmanager
    def provider(project):
        tmp = Path(tempfile.mkdtemp(prefix="fx-push-"))
        try:
            shutil.copytree(repo, tmp / "r")
            yield tmp / "r"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return provider


def _claim(project_id, user_id, sha="c" * 40, message="change"):
    portal_db.enqueue_push_check(project_id, user_id, sha, "main", source="webhook", commit_message=message)
    return portal_db.claim_next_push_check()


def test_a_green_push_passes_and_closes_old_push_incidents(web_env, tmp_path):
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    old, _ = portal_db.ingest_event(project_id, timestamp="2026-01-01T00:00:00Z", level="ERROR", message="x", signature="Push check: x")
    portal_db.mark_incident_source(old, "push", "d" * 40)
    repo = put(tmp_path / "repo", {"app.py": "x = 1\n", "requirements.txt": ""})
    check = _claim(project_id, user_id)
    statuses = []
    out = push_watch.run_check(check, runner=FakeRunner({"python": _ok("build")}), snapshot=_snapshot(repo),
                               notify_fn=lambda *a: None)
    assert out == "passed"
    row = portal_db.list_push_checks(project_id)[0]
    assert row["status"] == "passed" and json.loads(row["stacks_json"])[0]["ok"] is True
    assert portal_db.get_incident_row(old)["status"] == "resolved"
    project = portal_db.get_project(project_id, user_id)
    assert project["last_check_status"] == "passed" and project["status"] == "connected"


def test_a_red_push_opens_a_push_incident_and_emails_the_owner(web_env, tmp_path):
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    repo = put(tmp_path / "repo", {"app.py": "x = 1\n", "test_app.py": "def test_x(): assert 0\n", "requirements.txt": ""})
    check = _claim(project_id, user_id)
    told = []
    out = push_watch.run_check(check, runner=FakeRunner({"python": _bad("test", "FAILED test_app.py::test_x - AssertionError\n1 failed")}),
                               snapshot=_snapshot(repo), notify_fn=lambda *a: told.append(a))
    assert out == "failed" and told
    row = portal_db.list_push_checks(project_id)[0]
    inc = portal_db.get_incident_row(row["incident_id"])
    assert inc["source"] == "push" and inc["commit_sha"] == "c" * 40 and inc["stage"] == "queued"
    assert inc["signature"].startswith("Push check:")
    job = H.claim()
    assert job["incident_id"] == inc["id"] and job["source"] == "push"                 # the worker hands it to the fix engine


def test_the_agents_own_fix_failing_again_goes_to_a_human(web_env, tmp_path):
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    repo = put(tmp_path / "repo", {"app.py": "x = 1\n", "requirements.txt": ""})
    check = _claim(project_id, user_id, message="Merge Agent Daemon fix #3 [agent-daemon]")
    push_watch.run_check(check, runner=FakeRunner({"python": _bad("build", "SyntaxError: invalid syntax")}),
                         snapshot=_snapshot(repo), notify_fn=lambda *a: None)
    inc = portal_db.get_incident_row(portal_db.list_push_checks(project_id)[0]["incident_id"])
    assert inc["status"] == "needs_human" and inc["stage"] == "needs_human"           # no fix loops


def test_no_sandbox_means_the_check_waits_honestly(web_env, monkeypatch):
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    monkeypatch.setenv("FIXENGINE_SANDBOX_MODE", "remote")
    monkeypatch.delenv("FIXENGINE_SANDBOX_URL", raising=False)
    check = _claim(project_id, user_id)
    assert push_watch.run_check(check) == "waiting"
    row = portal_db.list_push_checks(project_id)[0]
    assert row["status"] == "queued" and row["stage"] == "waiting_sandbox" and "FIXENGINE_SANDBOX_URL" in row["stage_detail"]


# ------------------------------------------------------------------------------------------------ the engine on a push incident
class PushWorld:
    def __init__(self, tmp_path, monkeypatch, repo_files, scripts, mode="pr"):
        monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
        monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
        portal_db.init_db()
        self.cfg = fx_config.load()
        self.cfg["sandbox"]["mode"] = "local_unsafe"
        self.cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
        self.cfg["warn_every_use"]["opus"] = False
        self.repo = put(tmp_path / "repo", repo_files)
        self.user_id, self.project_id = H.make_user_and_project(mode=mode)
        self.prs = []
        self.adapters = {t: adapters.FakeAdapter(t, self.cfg, scripts.get(t)) for t in fx_config.TIERS}
        self.engine = orchestrator.Engine(self.cfg, adapters=self.adapters, runner=sandbox.LocalUnsafeRunner(self.cfg),
                                          repo_provider=H.repo_provider(self.repo), commits_provider=lambda p: "",
                                          pr_opener=self._open_pr)

    def _open_pr(self, project, **kw):
        self.prs.append(kw)
        return {"url": "https://github.com/acme/shop/pull/9", "number": 9, "branch": "agent-daemon/fix-x", "head_sha": "f" * 40,
                "path": ", ".join(kw["new_files"]), "diff": kw["diff"], "ci_status": "pending"}

    def push_incident(self, message, output):
        inc, _ = portal_db.ingest_event(self.project_id, timestamp="2020-01-01T10:00:00Z", level="ERROR", message=message,
                                        traceback=output, signature="Push check: x")
        portal_db.mark_incident_source(inc, "push", "e" * 40)
        return inc


def _reply(edit):
    return json.dumps({"diagnosis": "pct must be divided by 100", "cannot_determine": False, "edits": [edit]})


def test_engine_fixes_a_broken_push_proves_it_and_marks_the_fix_commit(tmp_path, monkeypatch):
    marked = []
    monkeypatch.setattr(push_watch, "set_commit_status", lambda project, sha, state, desc: marked.append((sha, state)) or True)
    w = PushWorld(tmp_path, monkeypatch, {"pricing.py": H.BUGGY_PRICING, "tests/test_pricing.py": H.BUGGY_TEST, "requirements.txt": ""},
                  {"groq": ["garbage"], "haiku": [_reply(H.GOOD_EDIT)]}, mode="auto")
    inc = w.push_incident("Push eeeeeee broke the build", "FAILED tests/test_pricing.py::test_ten_percent_off\n1 failed")
    outcome = w.engine.handle_incident(H.claim())
    assert outcome == "pr_opened" and w.prs
    assert w.prs[0]["title"].endswith("[agent-daemon]")                                    # marked, so its own merge never loops
    assert "Tests that failed before the fix now pass" in w.prs[0]["body"]
    assert marked == [("f" * 40, "success")]                                                # Auto mode sees a passing check
    row = portal_db.get_incident_row(inc)
    assert row["stage"] == "merging" and row["stage_tier"] == "haiku"


def test_a_build_break_without_tests_is_proven_by_the_same_check(tmp_path, monkeypatch):
    files = {"app.py": "def total(x):\n    return x +\n", "requirements.txt": ""}
    edit = {"file_path": "app.py", "old_text": "    return x +\n", "new_text": "    return x + 1\n"}
    w = PushWorld(tmp_path, monkeypatch, files, {"groq": [_reply(edit)]})
    w.push_incident("Push broke the build: SyntaxError", "[build] exit 1\n  File app.py, line 2\nSyntaxError: invalid syntax")
    assert w.engine.handle_incident(H.claim()) == "pr_opened"
    assert validator.VERIFY_TEXT["check_fixed"] in w.prs[0]["body"]


def test_a_push_that_is_already_fixed_spends_no_tries(tmp_path, monkeypatch):
    w = PushWorld(tmp_path, monkeypatch, {"app.py": "x = 1\n", "requirements.txt": ""}, {"groq": ["should not be called"]})
    inc = w.push_incident("Push broke", "[build] exit 1")
    assert w.engine.handle_incident(H.claim()) == "resolved"
    assert w.adapters["groq"].seen_prompts == []
    assert portal_db.get_incident_row(inc)["status"] == "resolved"
    assert store.list_attempts(store.get_bug_by_incident(inc)["id"]) == []


def test_verification_levels_for_push_bugs():
    R = sandbox.SandboxResult
    assert validator.verification_level(baseline_failing=-1, baseline_had_tests=False, result=R(passed=True),
                                         check_failed_before=True) == "check_fixed"
    assert validator.verification_level(baseline_failing=2, baseline_had_tests=True, result=R(passed=True, tests_ran=True),
                                         check_failed_before=True) == "tests_fixed"
    # a runtime bug whose baseline failed in an unknown way is still NOT treated as proven
    assert validator.verification_level(baseline_failing=-1, baseline_had_tests=False, result=R(passed=True)) == "build_only"


# ------------------------------------------------------------------------------------------------ dashboard stages
def test_dashboard_shows_mode_stage_and_tries_left(web_env):
    user_id, _, cookie = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    inc, _ = portal_db.ingest_event(project_id, timestamp="2026-01-01T00:00:00Z", level="ERROR", message="boom", signature="Push check: boom")
    portal_db.mark_incident_source(inc, "push", "abcdef1234567")
    portal_db.set_incident_stage(inc, "thinking", "lowest expected cost", "sonnet")
    portal_db.enqueue_push_check(project_id, user_id, "1" * 40, "main", source="webhook", commit_message="add cart")
    status, _, body = _request("/dashboard", cookie=cookie)
    assert status == "200 OK"
    assert "The Lead engineer is writing a fix" in body and "Lead engineer bar left" in body
    assert "commit abcdef1" in body and "Agent right now" in body and "Engineer" in body and "Your AI this month" in body
    assert "add cart" in body and "Waiting in line" in body
    st, _, frag = _request("/dashboard/live", cookie=cookie)
    assert st == "200 OK" and "The Lead engineer is writing a fix" in frag and "<html" not in frag
    for stage, text in (("testing_fix", "Testing the fix in the sandbox"), ("pushing", "Pushing the fix to GitHub"),
                        ("merging", "merging into your branch"), ("merged", "the fixed version is on GitHub")):
        portal_db.set_incident_stage(inc, stage, "", "sonnet")
        assert text in _request("/dashboard/live", cookie=cookie)[2]


def test_project_page_lists_push_checks_with_stacks(web_env):
    user_id, csrf, cookie = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = project_for(user_id)
    cid, _ = portal_db.enqueue_push_check(project_id, user_id, "2" * 40, "main", source="webhook", commit_message="new page")
    portal_db.finish_push_check(cid, "failed", output="boom", stacks=[{"label": "Python (backend)", "ok": True, "phase": "test"},
                                                                         {"label": "TypeScript (frontend)", "ok": False, "phase": "build"}])
    _, _, body = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Push guard" in body and "new page" in body and "TypeScript (frontend) at build" in body
    assert "Check latest commit now" in body and "Reconnect webhook" in body
    st, headers, _ = _request(f"/projects/{project_id}/watch", method="POST", cookie=cookie, form={"csrf": csrf, "watch_mode": "runtime"})
    assert st.startswith("303") and portal_db.get_project(project_id, user_id)["watch_mode"] == "runtime"
    st, _, frag = _request(f"/projects/{project_id}/incidents/live?part=checks", cookie=cookie)
    assert st == "200 OK" and "new page" in frag


# ------------------------------------------------------------------------------------------------ projects: 1 included, Rs 30 each
def test_second_project_needs_a_paid_slot(web_env, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(web_app, "validate_repository_access", lambda **kw: {"private": True, "default_branch": "main"})
    monkeypatch.setattr(web_app, "resolve_branch", lambda **kw: "main")
    user_id, csrf, cookie = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    form = {"csrf": csrf, "name": "One", "repo": "demo/one", "github_token": "ghp_" + "x" * 30, "mode": "pr", "watch_mode": "push",
            "allow_install": "yes", "allow_ai_processing": "yes", "allow_remediation": "yes"}
    first = _request("/projects/new", method="POST", cookie=cookie, form=form)
    assert first[0].startswith("201") and "Push guard is on" in first[2]
    assert portal_db.list_projects(user_id)[0]["watch_mode"] == "push"
    blocked = _request("/projects/new", method="POST", cookie=cookie, form={**form, "name": "Two", "repo": "demo/two"})
    assert blocked[0].startswith("402") and "/billing/pay?plan=project_slot" in blocked[2] and f"₹{plans.PROJECT_SLOT_PRICE}" in blocked[2]
    _, _, dash = _request("/dashboard", cookie=cookie)
    assert "Add a project · ₹30" in dash and "Projects: 1 of 1 used" in dash
    # pay Rs 30 by UPI, admin confirms -> one more slot
    _request("/billing/pay", method="POST", cookie=cookie, form={"csrf": csrf, "plan": "project_slot", "transaction_ref": "123456789012"})
    payment = [p for p in portal_db.admin_list_manual_payments() if p["plan"] == "project_slot"][0]
    assert payment["amount"] == 30
    assert portal_db.approve_manual_payment(payment["id"], "admin1@example.com")["product"] == "project_slot"
    second = _request("/projects/new", method="POST", cookie=cookie, form={**form, "name": "Two", "repo": "demo/two"})
    assert second[0].startswith("201") and len(portal_db.list_projects(user_id)) == 2


def test_addon_prices_are_fixed_and_need_an_active_plan(web_env):
    user_id, csrf, cookie = make_session("dev@example.com")
    with pytest.raises(ValueError):
        portal_db.create_manual_payment_request(user_id, 30, "project_slot", "123456789012")        # no plan yet
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    with pytest.raises(ValueError):
        portal_db.create_manual_payment_request(user_id, 10, "project_slot", "123456789013")        # wrong amount
    pay = portal_db.create_manual_payment_request(user_id, 99, "topup_engineer", "123456789014")
    result = portal_db.approve_manual_payment(pay["id"], "admin1@example.com")
    assert result["credited"] == {"tier": "haiku", "inr": 58}
    _, _, page = _request("/billing", cookie=cookie)
    assert "Add-ons" in page and "plan=project_slot" in page and "plan=topup_engineer" in page
    assert "plan=topup_lead" not in page and "pack_" not in page            # Basic: no Lead top-up; old packs are not sold
    _, _, upi = _request("/billing/pay?plan=topup_engineer", cookie=cookie)
    assert "am=99.00" in upi and "Engineer top-up" in upi
    status, _, lead = _request("/billing/pay?plan=topup_lead", cookie=cookie)
    assert status == "402 Payment Required" and "part of Pro" in lead


def test_plan_cards_list_each_monthly_quota(web_env):
    _, _, cookie = make_session("dev@example.com")
    _, _, page = _request("/billing", cookie=cookie)
    for line in ("<b>Engineer</b> · ≈ 14 small fixes a month", "<b>Engineer</b> · ≈ 28 small fixes a month",
                 "<b>Lead engineer</b> · ≈ 7 reviews or rescues a month"):
        assert line in page
    assert plans.product_grant_text("project_slot") == "add 1 project slot"


def test_admin_confirm_button_says_what_it_grants(web_env, monkeypatch):
    user_id, *_ = make_session("dev@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    portal_db.create_manual_payment_request(user_id, 30, "project_slot", "999988887777")
    admin_id, _, admin_cookie = make_session("admin1@example.com")
    _, _, page = _request("/admin", cookie=admin_cookie)
    assert "I received ₹30 · add 1 project slot" in page and "Java Integration Launch" not in page and "waitlist" not in page.lower()


# ------------------------------------------------------------------------------------------------ admins, support, pages
def test_default_admins_and_support_address(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    assert notifications.admin_emails() == ["abhaysamuel@agentdaemon.xyz", "pranavvrao@agentdaemon.xyz"]
    assert web_app._admin_emails() == {"abhaysamuel@agentdaemon.xyz", "pranavvrao@agentdaemon.xyz"}
    assert notifications.support_email() == "contact@agentdaemon.xyz"


def test_how_it_works_is_public_and_explains_the_algorithm(web_env):
    st, _, body = _request("/how-it-works")
    assert st == "200 OK" and "Push guard" in body and "Live error watch" in body
    # v4.1: the page explains the engineer (Normal first, stronger only if needed, steps for the owner), not the old router maths
    assert "How the agent fixes a problem" in body and "Normal goes first" in body and "Stronger only if needed" in body
    assert "Is it a code problem?" in body and "Sure or not sure" in body and "Dijkstra" not in body


def test_admin_architecture_is_admin_only_and_the_simulator_uses_the_real_router(web_env):
    _, _, cookie = make_session("dev@example.com")
    assert _request("/admin/architecture", cookie=cookie)[0].startswith("404")
    _, _, admin = make_session("admin1@example.com")
    st, _, body = _request("/admin/architecture", cookie=admin)
    assert st == "200 OK" and "The engineer (model architecture)" in body and "How the engineer works" in body
    assert "Old engine (fallback only" in body and "BaseAdapter.call" in body and "Memoization" in body       # old router kept for reference
    st, _, out = _request("/admin/architecture?simulate=1&bug_class=hard&free_tries=3&haiku_tries=2", cookie=admin)
    data = json.loads(out)
    assert data["action"] in ("sonnet", "opus", "stop") and data["options"]


def test_java_waitlist_is_gone(web_env):
    assert _request("/api/java-waitlist", method="POST", form={"email": "a@b.co"})[0].startswith(("303", "404"))
    _, _, home = _request("/")
    assert "java-announcement" not in home and "Java Integration" not in home
