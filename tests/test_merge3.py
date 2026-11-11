"""The owner's newer edits must never be thrown away when the engineer's fix is written."""
import random

from fixengine import merge3

BASE = "".join(f"line {i}\n" for i in range(1, 21))


def _edit(text, n, new):
    lines = text.splitlines(keepends=True)
    lines[n - 1] = new + "\n"
    return "".join(lines)


def test_both_sides_kept_when_they_change_different_lines():
    ours = _edit(BASE, 3, "line 3 FIXED BY THE AGENT")
    theirs = _edit(BASE, 15, "line 15 CHANGED BY THE OWNER")
    out = merge3.merge(BASE, ours, theirs)
    assert "FIXED BY THE AGENT" in out and "CHANGED BY THE OWNER" in out and out.count("\n") == 20


def test_same_line_changed_differently_is_a_conflict():
    assert merge3.merge(BASE, _edit(BASE, 7, "agent"), _edit(BASE, 7, "owner")) is None


def test_identical_change_on_both_sides_is_not_a_conflict():
    same = _edit(BASE, 7, "the same fix")
    assert merge3.merge(BASE, same, same) == same


def test_nobody_else_changed_the_file():
    ours = _edit(BASE, 2, "agent")
    assert merge3.merge(BASE, ours, BASE) == ours
    assert merge3.merge(BASE, BASE, _edit(BASE, 2, "owner")) == _edit(BASE, 2, "owner")


def test_insertions_and_deletions_on_different_places_merge():
    ours = BASE.replace("line 5\n", "line 5\nnew agent line\n")
    theirs = BASE.replace("line 18\n", "")
    out = merge3.merge(BASE, ours, theirs)
    assert "new agent line" in out and "line 18\n" not in out and "line 19\n" in out


def test_adjacent_changes_merge_in_order():
    ours = _edit(BASE, 4, "agent 4")
    theirs = _edit(BASE, 5, "owner 5")
    out = merge3.merge(BASE, ours, theirs).splitlines()
    assert out[3] == "agent 4" and out[4] == "owner 5"


def test_two_insertions_at_the_same_place_conflict():
    ours = BASE.replace("line 9\n", "line 9\nagent\n")
    theirs = BASE.replace("line 9\n", "line 9\nowner\n")
    assert merge3.merge(BASE, ours, theirs) is None


def test_insertion_inside_lines_the_other_side_rewrote_conflicts():
    ours = BASE.replace("line 10\nline 11\nline 12\n", "rewritten block\n")
    theirs = BASE.replace("line 11\n", "line 11\nowner inserted\n")
    assert merge3.merge(BASE, ours, theirs) is None


def test_new_and_deleted_files():
    assert merge3.merge(None, "new file\n", None) == "new file\n"
    assert merge3.merge(None, "agent version\n", "owner version\n") is None      # both created it differently
    assert merge3.merge(BASE, _edit(BASE, 1, "x"), None) is None                   # the owner deleted it meanwhile


def test_merge_files_reports_only_real_work_and_conflicts():
    base = {"a.py": BASE, "b.py": BASE, "c.py": BASE}
    ours = {"a.py": _edit(BASE, 1, "agent"), "b.py": _edit(BASE, 2, "agent"), "c.py": _edit(BASE, 3, "agent")}
    theirs = {"a.py": _edit(BASE, 20, "owner"), "b.py": _edit(BASE, 2, "owner"), "c.py": _edit(BASE, 3, "agent")}
    merged, conflicts = merge3.merge_files(base, ours, theirs)
    assert conflicts == ["b.py"] and "owner" in merged["a.py"] and "agent" in merged["a.py"]
    assert "c.py" not in merged                                                   # the branch already has exactly that


def test_random_non_overlapping_edits_always_keep_both_sides():
    rng = random.Random(7)
    for _ in range(300):
        n = rng.randint(6, 40)
        base = "".join(f"row {i}\n" for i in range(n))
        cut = rng.randint(2, n - 2)
        a = rng.randint(0, cut - 2)
        b = rng.randint(cut + 1, n - 1)
        ours = _edit(base, a + 1, f"agent {a}")
        theirs = _edit(base, b + 1, f"owner {b}")
        out = merge3.merge(base, ours, theirs)
        assert out is not None and f"agent {a}\n" in out and f"owner {b}\n" in out and out.count("\n") == n
