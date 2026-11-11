"""The real GitHub calls, against a small simulated GitHub: read the branch, refuse when it moved, undo only the agent's lines."""
import base64
import hashlib

import pytest

import portal_remediation
import repo_guard
from fixengine import git_ops


class FakeGitHub:
    """Commits, trees and blobs in memory, answering the same URLs git_ops calls."""

    def __init__(self):
        self.blobs, self.trees, self.commits, self.refs = {}, {}, {}, {}

    def blob(self, text):
        sha = hashlib.sha1(text.encode()).hexdigest()
        self.blobs[sha] = text
        return sha

    def commit(self, files, parent=None):
        tree = hashlib.sha1(repr(sorted(files.items())).encode()).hexdigest()
        self.trees[tree] = {p: self.blob(t) for p, t in files.items()}
        sha = hashlib.sha1((tree + str(parent)).encode()).hexdigest()
        self.commits[sha] = {"tree": tree, "parent": parent}
        return sha

    def files(self, sha):
        return {p: self.blobs[b] for p, b in self.trees[self.commits[sha]["tree"]].items()}

    def api(self, client, method, url, payload=None):
        path = url.split("/repos/acme/shop", 1)[1]
        if method == "GET" and path.startswith("/git/ref/heads/"):
            return {"object": {"sha": self.refs[path.rsplit("/", 1)[1]]}}
        if method == "GET" and path.startswith("/git/commits/"):
            c = self.commits[path.rsplit("/", 1)[1]]
            return {"tree": {"sha": c["tree"]}}
        if method == "GET" and path.startswith("/git/trees/"):
            tree = path.split("/git/trees/", 1)[1].split("?", 1)[0]
            return {"tree": [{"path": p, "sha": b, "type": "blob"} for p, b in self.trees[tree].items()]}
        if method == "GET" and path.startswith("/git/blobs/"):
            return {"content": base64.b64encode(self.blobs[path.rsplit("/", 1)[1]].encode()).decode()}
        if method == "POST" and path == "/git/blobs":
            return {"sha": self.blob(payload["content"])}
        if method == "POST" and path == "/git/trees":
            files = {p: self.blobs[b] for p, b in self.trees[payload["base_tree"]].items()}
            for e in payload["tree"]:
                if e["sha"] is None:
                    files.pop(e["path"], None)
                else:
                    files[e["path"]] = self.blobs[e["sha"]]
            tree = hashlib.sha1(repr(sorted(files.items())).encode()).hexdigest()
            self.trees[tree] = {p: self.blob(t) for p, t in files.items()}
            return {"sha": tree}
        if method == "POST" and path == "/git/commits":
            sha = hashlib.sha1((payload["tree"] + payload["parents"][0]).encode()).hexdigest()
            self.commits[sha] = {"tree": payload["tree"], "parent": payload["parents"][0]}
            return {"sha": sha}
        if method == "POST" and path == "/git/refs":
            self.refs[payload["ref"].rsplit("/", 1)[1]] = payload["sha"]
            return {}
        if method == "PATCH" and path.startswith("/git/refs/heads/"):
            self.refs[path.rsplit("/", 1)[1]] = payload["sha"]
            return {}
        raise AssertionError(f"unexpected call {method} {path}")


PROJECT = {"repo_owner": "acme", "repo_name": "shop", "branch": "main", "github_token_ciphertext": "x"}


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(portal_remediation, "_api", fake.api)
    monkeypatch.setattr(git_ops, "_token", lambda c: "token")
    monkeypatch.setattr(repo_guard, "ensure_private", lambda *a, **k: {"private": True})
    return fake


def test_read_files_returns_the_branch_as_it_is_now(gh):
    gh.refs["main"] = gh.commit({"a.py": "one\n", "b.py": "two\n"})
    out = git_ops.read_files(PROJECT, ["a.py", "missing.py"])
    assert out["sha"] == gh.refs["main"] and out["files"] == {"a.py": "one\n", "missing.py": None}


def test_a_push_onto_a_branch_that_moved_writes_nothing(gh):
    first = gh.commit({"a.py": "one\n"})
    gh.refs["main"] = gh.commit({"a.py": "one\nowner pushed\n"}, parent=first)
    with pytest.raises(git_ops.BranchMoved):
        git_ops.push_fix_branch(PROJECT, bug_id="b" * 20, new_files={"a.py": "fixed\n"}, title="fix", expected_base=first)
    assert not any(k.startswith("fix-") for k in gh.refs)                         # no branch created


def test_a_push_onto_the_expected_branch_keeps_the_other_files(gh):
    gh.refs["main"] = gh.commit({"a.py": "one\n", "b.py": "owner file\n"})
    out = git_ops.push_fix_branch(PROJECT, bug_id="b" * 20, new_files={"a.py": "fixed\n"}, title="fix", expected_base=gh.refs["main"])
    assert gh.files(out["head_sha"]) == {"a.py": "fixed\n", "b.py": "owner file\n"}


def test_undo_takes_back_only_the_agents_lines_and_keeps_later_owner_edits(gh):
    before = gh.commit({"p.py": "a\nb = 10\nc\nd\n", "other.py": "x\n"})
    fix = gh.commit({"p.py": "a\nb = 100\nc\nd\n", "other.py": "x\n", "new_by_agent.py": "helper\n"}, parent=before)
    later = gh.commit({"p.py": "a\nb = 100\nc\nd = 'owner later'\n", "other.py": "x\nowner\n", "new_by_agent.py": "helper\n"}, parent=fix)
    gh.refs["main"] = later
    outcome = git_ops.revert_files(PROJECT, base_sha=before, paths=["p.py", "new_by_agent.py"], title="undo", fix_sha=fix)
    now = gh.files(gh.refs["main"])
    assert outcome == "ok"
    assert now["p.py"] == "a\nb = 10\nc\nd = 'owner later'\n"                       # the fix is gone, the owner's later edit stays
    assert "new_by_agent.py" not in now and now["other.py"] == "x\nowner\n"


def test_undo_leaves_a_file_alone_when_the_owner_rewrote_the_same_lines(gh):
    before = gh.commit({"p.py": "a\nb = 10\nc\n"})
    fix = gh.commit({"p.py": "a\nb = 100\nc\n"}, parent=before)
    gh.refs["main"] = gh.commit({"p.py": "a\nb = 1000  # owner\nc\n"}, parent=fix)
    head = gh.refs["main"]
    assert git_ops.revert_files(PROJECT, base_sha=before, paths=["p.py"], title="undo", fix_sha=fix) == "conflict"
    assert gh.refs["main"] == head                                                 # nothing written
