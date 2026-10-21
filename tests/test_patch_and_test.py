"""Tests for patch validation, application, test runner execution, and autofix safety gates."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from autofix import attempt_autofix
from patcher import apply_patch, validate_patch
from tester import TestResult, classify_failure, extract_failure_summary, run_tests, sanitize_test_output


def test_validate_patch_success(tmp_path):
    target = tmp_path / "app.py"
    target.write_text('def add(a, b):\n    return a - b\n', encoding="utf-8")

    patch = {
        "file_path": "app.py",
        "old_text": "return a - b",
        "new_text": "return a + b",
        "explanation": "Fix addition operator",
    }
    valid, msg = validate_patch(tmp_path, patch)
    assert valid, msg


def test_validate_patch_rejects_test_file(tmp_path):
    target = tmp_path / "test_app.py"
    target.write_text('def test_foo(): pass\n', encoding="utf-8")

    patch = {
        "file_path": "test_app.py",
        "old_text": "def test_foo(): pass",
        "new_text": "def test_foo(): assert True",
    }
    valid, msg = validate_patch(tmp_path, patch)
    assert not valid
    assert "Refusing to patch test" in msg


def test_validate_patch_rejects_nonexistent_file(tmp_path):
    patch = {
        "file_path": "missing.py",
        "old_text": "foo",
        "new_text": "bar",
    }
    valid, msg = validate_patch(tmp_path, patch)
    assert not valid
    assert "does not exist" in msg


def test_validate_patch_rejects_old_text_not_found(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    patch = {
        "file_path": "app.py",
        "old_text": "x = 2",
        "new_text": "x = 3",
    }
    valid, msg = validate_patch(tmp_path, patch)
    assert not valid
    assert "not found" in msg


def test_apply_patch(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x = 10\n", encoding="utf-8")
    patch = {"file_path": "app.py", "old_text": "x = 10", "new_text": "x = 20"}
    new_content = apply_patch(tmp_path, patch)
    assert "x = 20" in new_content
    assert target.read_text(encoding="utf-8") == "x = 20\n"


def test_tester_sanitizes_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret_gh_token_9999")
    monkeypatch.setenv("GROQ_API_KEY", "secret_groq_key_8888")
    raw = "Failed on url https://x-access-token:secret_gh_token_9999@github.com with key secret_groq_key_8888"
    sanitized = sanitize_test_output(raw)
    assert "secret_gh_token_9999" not in sanitized
    assert "secret_groq_key_8888" not in sanitized
    assert "***" in sanitized


def test_classify_and_extract_summary():
    pytest_out = """
    === FAILURES ===
    ____ test_checkout ____
    AssertionError: assert 500 == 200
    === 1 failed in 0.2s ===
    """
    assert classify_failure(pytest_out, 1) == "assertion_failure"
    summary = extract_failure_summary(pytest_out)
    assert "AssertionError" in summary


def test_autofix_does_not_run_customer_tests_locally(tmp_path, temp_db):
    target = tmp_path / "catalog.py"
    target.write_text('PRODUCTS = {"cost": 220}\n', encoding="utf-8")

    incident = {"id": 1, "service": "coffee-shop", "message": "KeyError", "traceback": "..."}
    diagnosis = {
        "category": "code_bug",
        "still_present_in_current_code": "yes",
        "confidence": "high",
        "safe_to_auto_fix": True,
        "root_cause": "cost instead of price",
        "recommended_fix": "rename cost to price",
    }
    repo_cfg = {"mode": "pr", "branch": "master", "test_command": "pytest", "url": "https://github.com/pranavrao1-ai/cofee-shop.git"}

    mock_patch = {
        "file_path": "catalog.py",
        "old_text": '"cost": 220',
        "new_text": '"price": 220',
        "explanation": "Fix price key",
    }

    with patch("autofix.run_tests", side_effect=AssertionError("customer code must not run on our server")) as local_tests, \
         patch("autofix.generate_patch", return_value=mock_patch), \
         patch("autofix.create_fix_branch", return_value="fix/incident-1"), \
         patch("autofix.commit_fix"), \
         patch("autofix.open_and_maybe_merge_pr", return_value=("https://github.com/pranavrao1-ai/cofee-shop/pull/1", False)) as mock_pr, \
         patch("autofix._cleanup_workspace"):
        res = attempt_autofix(incident, diagnosis, tmp_path, repo_cfg, files_text="dummy")

    assert res["status"] == "pr_opened"
    local_tests.assert_not_called()
    mock_pr.assert_called_once()


def test_autofix_opens_pr_when_post_patch_tests_pass(tmp_path, temp_db):
    target = tmp_path / "catalog.py"
    target.write_text('PRODUCTS = {"cost": 220}\n', encoding="utf-8")

    incident = {"id": 1, "service": "coffee-shop", "message": "KeyError", "traceback": "..."}
    diagnosis = {
        "category": "code_bug",
        "still_present_in_current_code": "yes",
        "confidence": "high",
        "safe_to_auto_fix": True,
        "root_cause": "cost instead of price",
        "recommended_fix": "rename cost to price",
    }
    repo_cfg = {"mode": "pr", "branch": "master", "test_command": "pytest", "url": "https://github.com/pranavrao1-ai/cofee-shop.git"}

    mock_patch = {
        "file_path": "catalog.py",
        "old_text": '"cost": 220',
        "new_text": '"price": 220',
        "explanation": "Fix price key",
    }

    with patch("autofix.run_tests", side_effect=AssertionError("customer code must not run on our server")) as local_tests, \
         patch("autofix.generate_patch", return_value=mock_patch), \
         patch("autofix.create_fix_branch", return_value="fix/incident-1"), \
         patch("autofix.commit_fix"), \
         patch("autofix.open_and_maybe_merge_pr", return_value=("https://github.com/pranavrao1-ai/cofee-shop/pull/1", False)), \
         patch("autofix._cleanup_workspace"):
        res = attempt_autofix(incident, diagnosis, tmp_path, repo_cfg, files_text="dummy")

    assert res["status"] == "pr_opened"
    assert "pull/1" in res["pr_url"]
    local_tests.assert_not_called()
    from db import get_fixes
    saved = get_fixes(1)[0]
    assert 'PRODUCTS = {"cost": 220}' in saved["diff"]
    assert 'PRODUCTS = {"price": 220}' in saved["diff"]
