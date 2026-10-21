"""Tests for GitHub API access, token masking, and PR operations with mocked responses."""
import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from pr import _github, get_ci_status, mask_token, open_and_maybe_merge_pr, parse_github_owner_repo, wait_for_ci
from resolve_merged import pr_is_merged


def test_parse_github_owner_repo():
    assert parse_github_owner_repo("https://github.com/pranavrao1-ai/cofee-shop.git") == ("pranavrao1-ai", "cofee-shop")
    assert parse_github_owner_repo("https://github.com/pranavrao1-ai/cofee-shop") == ("pranavrao1-ai", "cofee-shop")
    assert parse_github_owner_repo("git@github.com:pranavrao1-ai/cofee-shop.git") == ("pranavrao1-ai", "cofee-shop")
    assert parse_github_owner_repo("pranavrao1-ai/cofee-shop") == ("pranavrao1-ai", "cofee-shop")
    assert parse_github_owner_repo("") == (None, None)


def test_mask_token():
    token = "ghp_super_secret_token_12345"
    text = f"Pushing to https://x-access-token:{token}@github.com/repo failed"
    masked = mask_token(text, token)
    assert token not in masked
    assert "***" in masked


def test_github_api_headers_and_parsing():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"id": 123, "html_url": "https://github.com/pranavrao1-ai/cofee-shop/pull/1"}'
    mock_resp.__enter__.return_value = mock_resp

    captured = []

    def mock_urlopen(req, timeout):
        captured.append(req)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = _github("https://api.github.com/repos/pranavrao1-ai/cofee-shop/pulls", "test_tok", {"title": "fix"}, "POST")

    assert res["id"] == 123
    assert len(captured) == 1
    req = captured[0]
    assert req.headers["Authorization"] == "Bearer test_tok"
    assert req.headers["Accept"] == "application/vnd.github+json"


def test_open_pr_success(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "mock_token")
    mock_pr = {"html_url": "https://github.com/pranavrao1-ai/cofee-shop/pull/5", "number": 5}

    with patch("pr.run_git", return_value=""), \
         patch("pr._github", return_value=mock_pr):
        url, merged = open_and_maybe_merge_pr(
            repo_folder=tmp_path,
            repo_url="https://github.com/pranavrao1-ai/cofee-shop.git",
            branch_name="fix/incident-1",
            base_branch="master",
            incident_id=1,
            auto_merge=False,
        )

    assert url == "https://github.com/pranavrao1-ai/cofee-shop/pull/5"
    assert not merged


def test_open_pr_already_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "mock_token")
    err = urllib.error.HTTPError(
        url="https://api.github.com/repos/pranavrao1-ai/cofee-shop/pulls",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(b'{"message":"A pull request already exists for this branch."}'),
    )

    with patch("pr.run_git", return_value=""), \
         patch("urllib.request.urlopen", side_effect=err):
        url, merged = open_and_maybe_merge_pr(
            repo_folder=tmp_path,
            repo_url="https://github.com/pranavrao1-ai/cofee-shop.git",
            branch_name="fix/incident-1",
            base_branch="master",
            incident_id=1,
        )

    assert url == "https://github.com/pranavrao1-ai/cofee-shop/pulls"
    assert not merged


def test_pr_is_merged():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"merged": true}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert pr_is_merged("https://github.com/pranavrao1-ai/cofee-shop/pull/5", "test_token") is True


def test_ci_requires_all_checks_to_succeed(monkeypatch):
    responses = [
        {"check_runs": [{"status": "completed", "conclusion": "success"}]},
        {"state": "success", "statuses": []},
    ]
    with patch("pr._github", side_effect=responses):
        assert get_ci_status("https://api.github.com/repos/o/r", "token", "abc") == "success"

    responses = [
        {"check_runs": [{"status": "completed", "conclusion": "failure"}]},
        {"state": "failure", "statuses": []},
    ]
    with patch("pr._github", side_effect=responses):
        assert get_ci_status("https://api.github.com/repos/o/r", "token", "abc") == "failed"


def test_auto_merge_waits_for_green_customer_ci(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "mock_token")
    monkeypatch.setenv("AGENT_CI_WAIT_SECONDS", "0")
    mock_pr = {"html_url": "https://github.com/pranavrao1-ai/cofee-shop/pull/9",
               "number": 9, "head": {"sha": "deadbeef"}}
    calls = []

    def github(url, token, payload, method):
        calls.append((url, method))
        if method == "POST":
            return mock_pr
        if url.endswith("/check-runs?per_page=100"):
            return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        if url.endswith("/status"):
            return {"state": "success", "statuses": []}
        if url.endswith("/merge"):
            return {"merged": True}
        raise AssertionError(url)

    with patch("pr.run_git", return_value=""), patch("pr._github", side_effect=github):
        url, merged = open_and_maybe_merge_pr(
            repo_folder=tmp_path,
            repo_url="https://github.com/pranavrao1-ai/cofee-shop.git",
            branch_name="fix/incident-9",
            incident_id=9,
            auto_merge=True,
        )

    assert url == mock_pr["html_url"]
    assert merged is True
    assert calls[-1][0].endswith("/pulls/9/merge")


def test_auto_merge_never_merges_without_customer_ci(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "mock_token")
    monkeypatch.setenv("AGENT_CI_WAIT_SECONDS", "0")
    monkeypatch.setenv("AGENT_CI_DISCOVERY_SECONDS", "0")
    mock_pr = {"html_url": "https://github.com/pranavrao1-ai/cofee-shop/pull/10",
               "number": 10, "head": {"sha": "cafebabe"}}
    calls = []

    def github(url, token, payload, method):
        calls.append((url, method))
        if method == "POST":
            return mock_pr
        return {"check_runs": []} if url.endswith("/check-runs?per_page=100") else {"state": "pending", "statuses": []}

    with patch("pr.run_git", return_value=""), patch("pr._github", side_effect=github):
        url, merged = open_and_maybe_merge_pr(
            repo_folder=tmp_path,
            repo_url="https://github.com/pranavrao1-ai/cofee-shop.git",
            branch_name="fix/incident-10",
            incident_id=10,
            auto_merge=True,
        )

    assert url == mock_pr["html_url"]
    assert merged is False
    assert not any(url.endswith("/merge") for url, _ in calls)
