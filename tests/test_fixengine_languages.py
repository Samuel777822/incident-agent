"""Plan v3: HTML/CSS, JavaScript, TypeScript and Java support.

Everything here runs offline with fake models. Tests that need Node or a JDK skip themselves when the tool is missing, so
run them on a machine that has `node` (and `javac` for the Java ones) to get the full picture:
    python -m pytest tests/test_fixengine_languages.py -q
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import portal_db
from fixengine import adapters, config as fx_config, fingerprint, orchestrator, prompts, repo_context, sandbox, store, triage, validator
from tests import fx_helpers as H

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
import make_cases_v2 as v2                                                         # noqa: E402

HAVE_NODE = shutil.which("node") is not None and shutil.which("npm") is not None


def _javac_works() -> bool:
    jc = v2.javac_argv()
    return bool(jc) and subprocess.run(jc + ["-version"], capture_output=True).returncode == 0


HAVE_JAVAC = _javac_works()


def put(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def load_static_check():
    spec = importlib.util.spec_from_file_location("static_check", ROOT / "sandbox" / "static_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------- profile detection
def test_python_profile_is_unchanged(tmp_path):
    put(tmp_path, {"app.py": "x = 1\n", "test_app.py": "def test_x(): pass\n", "requirements.txt": ""})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "python" and p.has_tests and p.workdir == ""


def test_javascript_project_without_dependencies_needs_no_install(tmp_path):
    put(tmp_path, {"package.json": json.dumps({"scripts": {"test": "node --test", "start": "node server.js"}}), "server.js": "1\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "node" and p.install is None and p.test == "npm test --silent" and p.smoke == "npm start"


def test_typescript_project_gets_a_type_check_step(tmp_path):
    put(tmp_path, {"package.json": json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"typescript": "^5", "vitest": "^2"}}),
                   "tsconfig.json": "{}", "src/a.ts": "export const a: number = 1;\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "node" and p.build == "npx --no-install tsc --noEmit" and p.install.startswith("npm install --ignore-scripts")


def test_typescript_build_script_that_runs_tsc_is_not_run_twice(tmp_path):
    put(tmp_path, {"package.json": json.dumps({"scripts": {"build": "tsc -p ."}, "devDependencies": {"typescript": "^5"}}),
                   "tsconfig.json": "{}", "a.ts": "1\n"})
    assert sandbox.detect_profile(tmp_path).build == "npx --no-install tsc --noEmit"


def test_typescript_without_the_dependency_is_noted_not_guessed(tmp_path):
    put(tmp_path, {"package.json": json.dumps({"scripts": {}}), "tsconfig.json": "{}", "a.ts": "1\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.build is None and any("typescript is not a dependency" in n for n in p.notes)


def test_static_site_profile_checks_and_serves_the_site(tmp_path):
    put(tmp_path, {"index.html": "<p>hi</p>", "css/site.css": "a { color: red; }\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "static" and "static_check.py" in p.build and "http.server" in p.smoke and not p.has_tests


def test_static_site_inside_public_folder(tmp_path):
    put(tmp_path, {"public/index.html": "<p>hi</p>", "README.md": "x"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "static" and "--site-root public" in p.build and p.smoke.startswith("cd public &&")


def test_maven_project(tmp_path):
    put(tmp_path, {"pom.xml": "<project/>", "src/main/java/App.java": "class App {}\n", "src/test/java/AppTest.java": "class AppTest {}\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "java" and "mvn" in p.install and "-o" in p.build and p.has_tests and "mvn" in p.test


def test_gradle_project_needs_the_wrapper(tmp_path):
    put(tmp_path, {"build.gradle": "", "src/main/java/App.java": "class App {}\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "java" and p.build is None and any("gradlew" in n for n in p.notes)
    put(tmp_path, {"gradlew": "#!/bin/sh\n"})
    assert "gradlew" in (sandbox.detect_profile(tmp_path).build or "")


def test_plain_java_project_compiles_everything_and_runs_main_style_tests(tmp_path):
    put(tmp_path, {"src/main/java/com/x/A.java": "package com.x;\npublic class A {}\n",
                   "src/test/java/com/x/AllTests.java": "package com.x;\npublic class AllTests { public static void main(String[] a) {} }\n"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "java" and "javac" in p.build and p.test == "java -cp .fx_out com.x.AllTests" and p.has_tests


def test_junit_without_a_build_file_is_explained(tmp_path):
    put(tmp_path, {"A.java": "class A {}\n", "ATest.java": "import org.junit.Test;\nclass ATest { @Test void t() {} public static void main(String[] a){} }\n"})
    p = sandbox.detect_profile(tmp_path)
    assert not p.has_tests and any("JUnit" in n for n in p.notes)


def test_project_in_a_subfolder_is_found(tmp_path):
    put(tmp_path, {"frontend/package.json": json.dumps({"scripts": {"test": "jest"}}), "README.md": "x"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "node" and p.workdir == "frontend" and any("frontend" in n for n in p.notes)


def test_python_backend_wins_and_the_other_part_is_mentioned(tmp_path):
    put(tmp_path, {"main.py": "x = 1\n", "web/package.json": "{}"})
    p = sandbox.detect_profile(tmp_path)
    assert p.language == "python" and any("Node" in n for n in p.notes)


def test_nothing_recognisable(tmp_path):
    put(tmp_path, {"notes.txt": "hello"})
    assert sandbox.detect_profile(tmp_path).language == "none"


# ------------------------------------------------------------------------------------------------- the static checker
def test_static_checker_accepts_a_clean_site(tmp_path):
    sc = load_static_check()
    v2.static_base(tmp_path)
    errors, checked = sc.check_site(tmp_path)
    assert errors == [] and checked >= 8


def test_static_checker_finds_each_kind_of_mistake(tmp_path):
    sc = load_static_check()
    put(tmp_path, {
        "index.html": '<html><head><link rel="stylesheet" href="css/missing.css"></head><body>\n<div><span>x</div>\n<img src="nope.png">\n</body></html>\n',
        "css/ok.css": ".a { color: red;\n",
        "css/bad.css": ".b { color red; }\n",
        "data.json": '{"a": 1,}',
    })
    messages = [m for _f, _l, m in sc.check_site(tmp_path)[0]]
    joined = " | ".join(messages)
    assert "missing file css/missing.css" in joined and "missing file nope.png" in joined
    assert "unclosed <span>" in joined and "missing }" in joined
    assert "declaration without ':'" in joined and "invalid JSON" in joined


def test_static_checker_allows_optional_end_tags_and_void_elements(tmp_path):
    sc = load_static_check()
    put(tmp_path, {"index.html": "<ul><li>one<li>two</ul><p>para<br><img src='data:image/png;base64,AAAA' alt=''>\n"})
    assert sc.check_site(tmp_path)[0] == []


def test_static_checker_ignores_external_and_template_links(tmp_path):
    sc = load_static_check()
    put(tmp_path, {"index.html": '<a href="https://example.com/x.html">a</a><a href="mailto:a@b.c">m</a><a href="#top">t</a>'
                                 '<a href="/about">clean url</a><img src="{{ logo }}">\n'})
    assert sc.check_site(tmp_path)[0] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_static_checker_reports_javascript_syntax_errors(tmp_path):
    sc = load_static_check()
    put(tmp_path, {"index.html": "<script>function (</script>\n", "app.js": "let = ;\n"})
    messages = " | ".join(m for _f, _l, m in sc.check_site(tmp_path)[0])
    assert "SyntaxError" in messages and "inline <script>" in messages


def test_static_checker_output_is_understood_by_the_engine(tmp_path):
    out = "index.html:14: unclosed <div>\ncss/site.css:30: missing } (block opened here is never closed)\nstatic_check: 2 errors in 3 files\n"
    fp = fingerprint.fingerprint("page broken", out)
    assert fp["error_type"].startswith("Static_") and fp["files"] == ["index.html", "site.css"]
    assert sandbox.parse_failing(out) == 2
    assert triage.classify(error_type=fp["error_type"], message="", traceback=out, frame_count=2, files_in_trace=2,
                           repo_tokens=3000, has_tests=False)["category"] == "markup_or_style"


# ------------------------------------------------------------------------------- reading errors from other languages
def test_java_stack_trace_points_at_the_innermost_root_cause():
    trace = ('Exception in thread "main" java.lang.IllegalStateException: boom\n\tat com.shop.Users.add(Users.java:23)\n'
             "\tat com.shop.Main.main(Main.java:9)\nCaused by: java.lang.NullPointerException: x\n\tat com.shop.Store.get(Store.java:5)\n"
             "\tat com.shop.Users.add(Users.java:20)\n")
    fp = fingerprint.fingerprint("fail", trace)
    assert fp["error_type"] == "NullPointerException" and fp["where"] == "Store.java:get"


def test_javac_and_tsc_errors_are_understood():
    javac = "src/main/java/com/shop/Orders.java:12: error: cannot find symbol\n  symbol: variable totl\n1 error\n"
    assert fingerprint.app_frames(javac)[0][:2] == ("src/main/java/com/shop/Orders.java", 12)
    assert fingerprint.fingerprint("compile failed", javac)["error_type"] == "CannotFindSymbol"
    tsc = "src/orders.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    assert fingerprint.fingerprint("tsc", tsc)["error_type"] == "TS2322"
    assert triage.classify(error_type="TS2322", message="", traceback=tsc, frame_count=1, files_in_trace=1,
                           repo_tokens=2000, has_tests=True)["bug_class"] == "easy"


def test_javascript_trace_reports_the_innermost_frame_not_the_outermost():
    trace = "TypeError: x is undefined\n    at lineTotal (/app/src/pricing.js:12:20)\n    at createOrder (/app/src/orders.js:30:9)\n"
    fp = fingerprint.fingerprint("t", trace)
    assert fp["error_type"] == "TypeError" and fp["where"] == "pricing.js:lineTotal"


def test_context_follows_java_imports_and_html_references():
    paths = {"src/main/java/com/shop/Users.java", "src/main/java/com/shop/Main.java", "index.html", "css/site.css", "js/app.js"}
    assert repo_context.imports_of("src/main/java/com/shop/Main.java", "package com.shop;\nimport com.shop.Users;\n", paths) == ["src/main/java/com/shop/Users.java"]
    assert set(repo_context.imports_of("index.html", '<link rel="stylesheet" href="css/site.css"><script src="js/app.js"></script>', paths)) == {"css/site.css", "js/app.js"}
    assert repo_context.is_test_path("src/test/java/com/shop/UsersTest.java") and not repo_context.is_test_path("src/main/java/com/shop/Users.java")


def test_new_file_types_are_editable_and_build_files_are_protected():
    repo = {"A.java": "class A { int x = 1; }\n", "site.css": "a { color: red; }\n", "index.html": "<p>a</p>\n", "pom.xml": "<project/>\n",
            "tsconfig.json": "{}\n"}
    for path, old, new in (("A.java", "x = 1", "x = 2"), ("site.css", "red", "blue"), ("index.html", "<p>a</p>", "<p>b</p>")):
        validator.check_edits([{"file_path": path, "old_text": old, "new_text": new}], repo)
    for path in ("pom.xml", "tsconfig.json"):
        with pytest.raises(validator.PolicyError):
            validator.check_edits([{"file_path": path, "old_text": "{}" if path.endswith("json") else "<project/>", "new_text": "x"}], repo)
    assert prompts.new_suspicious("a", 'Runtime.getRuntime().exec("rm -rf /")')
    assert prompts.new_suspicious("a", '<script src="https://evil.example/x.js"></script>')


# ------------------------------------------------------------------------------------------- docker command plans
def _fake_exec(calls):
    def run(argv, timeout, cwd=None, env=None):
        calls.append(argv)
        return 0, "ok", False
    return run


def _plan(tmp_path, profile_files, cfg):
    put(tmp_path, profile_files)
    calls = []
    res = sandbox.DockerRunner(cfg, _fake_exec(calls)).run(tmp_path, sandbox.detect_profile(tmp_path))
    return res, calls


def test_docker_plan_for_maven_uses_the_java_image_and_only_installs_with_network(tmp_path):
    cfg = fx_config.load()
    res, calls = _plan(tmp_path, {"pom.xml": "<project/>", "src/main/java/App.java": "class App {}\n", "src/test/java/AppTest.java": "class AppTest {}\n"}, cfg)
    assert [p.name for p in res.phases] == ["install", "build", "test"]
    assert all(cfg["sandbox"]["image_java"] in c for c in calls)
    assert [c[c.index("--network") + 1] for c in calls] == ["bridge", "none", "none"]


def test_docker_plan_for_static_site_mounts_the_checker_and_uses_the_node_image(tmp_path):
    cfg = fx_config.load()
    res, calls = _plan(tmp_path, {"index.html": "<p>x</p>"}, cfg)
    assert [p.name for p in res.phases] == ["build", "smoke"]
    assert all(cfg["sandbox"]["image_node"] in c for c in calls)
    assert any(arg.endswith(":/opt/static_check.py:ro") for arg in calls[0])
    assert all(c[c.index("--network") + 1] == "none" for c in calls)


def test_docker_plan_runs_a_subfolder_project_from_its_folder(tmp_path):
    cfg = fx_config.load()
    res, calls = _plan(tmp_path, {"web/package.json": json.dumps({"scripts": {"test": "jest"}})}, cfg)
    assert calls[-1][-1].startswith("cd web && npm test")


# -------------------------------------------------------------------------- real runs (local_unsafe, throw-away repos)
def _local_runner(monkeypatch):
    monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
    cfg = fx_config.load()
    cfg["sandbox"]["timeout_seconds"] = 60
    return sandbox.LocalUnsafeRunner(cfg)


def test_the_sample_static_site_passes_and_a_broken_copy_fails(tmp_path, monkeypatch):
    runner = _local_runner(monkeypatch)
    good = tmp_path / "good"
    v2.static_base(good)
    res = runner.run(good, sandbox.detect_profile(good))
    assert res.passed and res.smoke_ran
    bad = tmp_path / "bad"
    v2.static_base(bad)
    (bad / "products.html").write_text((bad / "products.html").read_text().replace("css/styles.css", "css/style.css"))
    res = runner.run(bad, sandbox.detect_profile(bad))
    assert not res.passed and "missing file css/style.css" in res.output


@pytest.mark.skipif(not HAVE_NODE, reason="node/npm are not installed")
def test_the_sample_javascript_project_passes_and_a_bug_fails(tmp_path, monkeypatch):
    runner = _local_runner(monkeypatch)
    good = tmp_path / "good"
    v2.js_base(good)
    res = runner.run(good, sandbox.detect_profile(good))
    assert res.passed and res.tests_ran and res.smoke_ran
    bad = tmp_path / "bad"
    v2.js_base(bad)
    v2.apply_bug(bad, next(b for b in v2.JS_BUGS if b["name"] == "js_medium_logic_discount"))
    res = runner.run(bad, sandbox.detect_profile(bad))
    assert not res.passed and res.failing and res.failing > 0


@pytest.mark.skipif(not (HAVE_NODE and shutil.which("tsc")), reason="node and a global tsc are needed (the Docker image installs typescript itself)")
def test_the_sample_typescript_project_is_type_checked_and_tested(tmp_path, monkeypatch):
    runner = _local_runner(monkeypatch)
    good = tmp_path / "good"
    v2.ts_base(good)
    profile = sandbox.detect_profile(good)
    profile.install = None                                    # typescript comes from the global install in this test
    assert runner.run(good, profile).passed
    bad = tmp_path / "bad"
    v2.ts_base(bad)
    v2.apply_bug(bad, next(b for b in v2.TS_BUGS if b["name"] == "ts_easy_wrong_argument_type"))
    profile = sandbox.detect_profile(bad)
    profile.install = None
    res = runner.run(bad, profile)
    assert not res.passed and "TS2345" in res.output


@pytest.mark.skipif(not HAVE_JAVAC, reason="a JDK (javac) is not installed")
def test_the_sample_java_project_compiles_passes_and_a_bug_fails(tmp_path, monkeypatch):
    runner = _local_runner(monkeypatch)
    good = tmp_path / "good"
    v2.java_base(good)
    res = runner.run(good, sandbox.detect_profile(good))
    assert res.passed and res.tests_ran
    bad = tmp_path / "bad"
    v2.java_base(bad)
    v2.apply_bug(bad, next(b for b in v2.JAVA_BUGS if b["name"] == "java_easy_typo_variable"))
    res = runner.run(bad, sandbox.detect_profile(bad))
    assert not res.passed and "cannot find symbol" in res.output


# ----------------------------------------------------- the whole loop on each new language (fake model, real sandbox run)
class LangWorld:
    def __init__(self, tmp_path, monkeypatch, make_base, bug, scripts):
        monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
        monkeypatch.setenv("FIXENGINE_ALLOW_UNSAFE_LOCAL", "1")
        portal_db.init_db()
        self.cfg = fx_config.load()
        self.cfg["sandbox"]["mode"] = "local_unsafe"
        self.cfg["sandbox"]["timeout_seconds"] = 60
        self.repo = tmp_path / "customer"
        make_base(self.repo)
        v2.apply_bug(self.repo, bug)
        self.user_id, self.project_id = H.make_user_and_project(mode="pr")
        self.prs = []
        self.adapters = {t: adapters.FakeAdapter(t, self.cfg, scripts.get(t)) for t in fx_config.TIERS}
        self.engine = orchestrator.Engine(self.cfg, adapters=self.adapters, runner=sandbox.LocalUnsafeRunner(self.cfg),
                                          repo_provider=H.repo_provider(self.repo), commits_provider=lambda p: "", pr_opener=self._pr)

    def _pr(self, project, **kw):
        self.prs.append(kw)
        return {"url": "https://github.com/acme/shop/pull/9", "number": 9, "branch": "fx/x", "path": ", ".join(kw["new_files"]),
                "diff": kw["diff"], "ci_status": "pending"}

    def run(self, message, traceback):
        incident_id = H.make_incident(self.project_id, message=message, traceback=traceback)
        claimed = H.claim()
        outcome = self.engine.handle_incident(claimed)
        bug = store.get_bug_by_incident(incident_id)
        return outcome, bug, [(a["tier"], a["result"]) for a in store.list_attempts(bug["id"])]


def _reply(edit):
    return json.dumps({"diagnosis": "root cause found", "cannot_determine": False, "edits": [edit]})


def _bug(name):
    return next(b for group in (v2.JAVA_BUGS, v2.JS_BUGS, v2.TS_BUGS, v2.STATIC_BUGS) for b in group if b["name"] == name)


def test_whole_loop_fixes_a_static_site(tmp_path, monkeypatch):
    bug = _bug("static_easy_wrong_stylesheet_name")
    edit = {"file_path": "products.html", "old_text": 'href="css/style.css"', "new_text": 'href="css/styles.css"'}
    w = LangWorld(tmp_path, monkeypatch, v2.static_base, bug, {"groq": ["garbage"], "haiku": [_reply(edit)]})
    outcome, row, tries = w.run(bug["message"], bug["fallback"])
    assert outcome == "pr_opened" and tries[-1] == ("haiku", "pass")
    assert "css/styles.css" in w.prs[0]["new_files"]["products.html"]
    assert "NOT proven" in w.prs[0]["body"] or "NOT VERIFIED" in w.prs[0]["body"] or "starts" in w.prs[0]["body"]


@pytest.mark.skipif(not HAVE_NODE, reason="node/npm are not installed")
def test_whole_loop_fixes_a_javascript_bug_and_the_tests_prove_it(tmp_path, monkeypatch):
    bug = _bug("js_medium_logic_discount")
    edit = {"file_path": "src/pricing.js", "old_text": "(price * pct) / 10)", "new_text": "(price * pct) / 100)"}
    w = LangWorld(tmp_path, monkeypatch, v2.js_base, bug, {"groq": ["garbage"], "haiku": [_reply(edit)]})
    outcome, row, tries = w.run(bug["message"], bug["fallback"])
    assert outcome == "pr_opened" and tries[-1] == ("haiku", "pass") and row["baseline_failing"] > 0
    assert "Tests that failed before the fix now pass" in w.prs[0]["body"]
    assert "src/pricing.js" in "".join(w.adapters["haiku"].seen_prompts)             # the right file reached the model


@pytest.mark.skipif(not HAVE_JAVAC, reason="a JDK (javac) is not installed")
def test_whole_loop_fixes_a_java_bug_and_the_tests_prove_it(tmp_path, monkeypatch):
    bug = _bug("java_medium_logic_discount")
    edit = {"file_path": "src/main/java/com/shop/Pricing.java", "old_text": "price * pct / 10)", "new_text": "price * pct / 100)"}
    w = LangWorld(tmp_path, monkeypatch, v2.java_base, bug, {"groq": ["garbage"], "haiku": [_reply(edit)]})
    outcome, row, tries = w.run(bug["message"], bug["fallback"])
    assert outcome == "pr_opened" and row["baseline_failing"] > 0
    assert "Tests that failed before the fix now pass" in w.prs[0]["body"]


def test_a_model_that_edits_the_build_file_is_refused(tmp_path, monkeypatch):
    bug = _bug("static_easy_wrong_stylesheet_name")
    edit = {"file_path": "package.json", "old_text": "{}", "new_text": "{}"}
    w = LangWorld(tmp_path, monkeypatch, v2.static_base, bug, {"groq": ["garbage"], "haiku": [_reply(edit)]})
    _o, _row, tries = w.run(bug["message"], bug["fallback"])
    assert ("haiku", "pass") not in tries


# ---------------------------------------------------------------------------------------------- benchmark integrity
def test_every_generated_case_has_a_repo_an_incident_and_a_known_language():
    cases = ROOT / "bench" / "cases"
    if not cases.exists():
        pytest.skip("run python bench/make_all_cases.py first")
    for case in sorted(p for p in cases.iterdir() if p.is_dir()):
        assert (case / "repo").is_dir() and (case / "incident.json").is_file(), case.name
        incident = json.loads((case / "incident.json").read_text())
        assert incident["message"] and incident["traceback"], case.name
        assert sandbox.detect_profile(case / "repo").language in ("python", "node", "java", "static"), case.name


def test_the_sandbox_abuse_script_is_wired_up_and_every_check_script_is_valid_python():
    import sandbox_abuse_check as abuse
    assert len(abuse.CHECKS) == 8
    for name, (script, expect) in abuse.CHECKS.items():
        compile(script, name, "exec")
        assert expect in ("killed", "exit0")
