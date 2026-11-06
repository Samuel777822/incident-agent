import shutil
import subprocess

import pytest

from monitoring_adapters import BROWSER_SOURCE, JAVA_MONITOR_TEMPLATE, NODE_CJS_SOURCE, NODE_ESM_SOURCE
from monitoring_installer import (
    _insert_python_import,
    _insert_js_monitor,
    _patch_java_main,
    _java_package,
    _java_monitor_source,
    _inject_html_monitor,
    build_monitoring_config,
    detect_stacks,
)


def test_detect_stacks_supports_mixed_repositories_and_ignores_vendored_code():
    stacks = detect_stacks([
        "app.py", "package.json", "src/main.tsx", "pom.xml",
        "src/main/java/com/acme/Main.java", "index.html",
        "node_modules/pkg/example.py", "vendor/lib.js", ".venv/lib/site.py",
    ])
    assert stacks == {"python", "node", "java", "browser"}


def test_detect_stacks_does_not_mark_vendor_only_files():
    assert detect_stacks(["node_modules/pkg/index.js", "dist/bundle.js", "vendor/Foo.java"]) == set()


def test_python_import_respects_docstring_and_future_import_and_is_idempotent():
    source = '"""app docs"""\nfrom __future__ import annotations\n\ndef main():\n    pass\n'
    patched = _insert_python_import(source)
    assert patched.index("from __future__") < patched.index("import incident_agent_monitor")
    assert patched.count("import incident_agent_monitor") == 1
    assert _insert_python_import(patched) == patched


def test_js_monitor_injection_supports_cjs_and_esm_and_is_idempotent():
    cjs = _insert_js_monitor('"use strict";\nconsole.log("ready");\n', esm=False,
                              monitor_path="incident_agent_monitor.cjs")
    esm = _insert_js_monitor('export function start() {}\n', esm=True,
                             monitor_path="incident_agent_monitor.mjs")
    assert cjs.startswith('require("./incident_agent_monitor.cjs");')
    assert esm.startswith('import "./incident_agent_monitor.mjs";')
    assert _insert_js_monitor(cjs, esm=False, monitor_path="incident_agent_monitor.cjs") == cjs


def test_java_main_is_patched_and_package_is_preserved():
    source = 'package com.acme;\npublic class Main {\n  public static void main(String[] args) {\n    System.out.println("ok");\n  }\n}\n'
    patched = _patch_java_main(source)
    assert "AgentDaemonMonitor.install();" in patched
    assert _patch_java_main(patched) == patched
    assert _java_package(source) == "com.acme"
    helper = _java_monitor_source("com.acme")
    assert helper.startswith("package com.acme;")
    assert "{{" not in helper and "}}" not in helper


def test_html_injection_is_idempotent():
    html = "<html><body><h1>App</h1></body></html>"
    patched = _inject_html_monitor(html)
    assert patched.count("agent-daemon-monitor.js") == 1
    assert patched.index("agent-daemon-monitor.js") < patched.index("</body>")
    assert _inject_html_monitor(patched) == patched


def test_public_repository_config_never_contains_server_ingest_secret():
    config, private_embedded, public_embedded = build_monitoring_config(
        private_repo=False, ingest_url="https://daemon.test/ingest",
        ingest_key="server-secret", browser_ingest_url="https://daemon.test/ingest/browser",
        browser_ingest_key="public-project-token",
    )
    assert private_embedded is False
    assert public_embedded is True
    assert "ingest_key" not in config
    assert config["browser_ingest_key"] == "public-project-token"


def test_private_repository_config_contains_server_and_browser_credentials():
    config, private_embedded, public_embedded = build_monitoring_config(
        private_repo=True, ingest_url="https://daemon.test/ingest",
        ingest_key="server-secret", browser_ingest_url="https://daemon.test/ingest/browser",
        browser_ingest_key="public-project-token",
    )
    assert private_embedded is True and public_embedded is True
    assert config["ingest_key"] == "server-secret"
    assert config["browser_ingest_key"] == "public-project-token"


def test_runtime_adapter_sources_are_self_contained():
    assert "uncaughtExceptionMonitor" in NODE_CJS_SOURCE
    assert "uncaughtExceptionMonitor" in NODE_ESM_SOURCE
    assert "unhandledrejection" in BROWSER_SOURCE
    assert "java.util.logging" in JAVA_MONITOR_TEMPLATE


@pytest.mark.parametrize("source", [NODE_CJS_SOURCE, NODE_ESM_SOURCE])
def test_node_adapters_pass_node_syntax_check_when_node_is_available(tmp_path, source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed in this test environment")
    suffix = ".mjs" if source is NODE_ESM_SOURCE else ".cjs"
    file = tmp_path / ("adapter" + suffix)
    file.write_text(source, encoding="utf-8")
    result = subprocess.run([node, "--check", str(file)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
