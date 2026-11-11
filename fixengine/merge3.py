"""Three-way merge of text files, line by line (what `git merge-file` does, in pure Python).

Why: the engineer reads the owner's code, works for minutes (or waits hours for an answer), and then its fix is written to GitHub.
If the owner pushed changes to the same files meanwhile, writing the engineer's whole file would silently throw their work away.
merge(base, ours, theirs) keeps BOTH sides' changes, and refuses (returns None) when both changed the same lines: then nothing is
written and the engineer redoes its fix on the owner's latest code.

    base   = the file as the engineer first read it
    ours   = the engineer's version
    theirs = the file on the branch right now (may include the owner's newer edits)
"""
from __future__ import annotations

from difflib import SequenceMatcher


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    """Changes from base to other as (start, end, replacement) on base's lines."""
    sm = SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _clash(a: tuple, b: tuple) -> bool:
    """Do two changes touch the same lines? Changes next to each other are fine: their order is clear."""
    (a1, a2, ra), (b1, b2, rb) = a, b
    if (a1, a2, ra) == (b1, b2, rb):
        return False                                   # both made the very same change
    if a1 == a2 and b1 == b2:
        return a1 == b1                                # two different insertions at the same place: order unknown
    if a1 == a2:
        return b1 < a1 < b2                            # an insertion inside lines the other side changed
    if b1 == b2:
        return a1 < b1 < a2
    return max(a1, b1) < min(a2, b2)                   # the changed ranges overlap


def merge(base: str | None, ours: str | None, theirs: str | None) -> str | None:
    """The merged text, or None when both sides changed the same lines (a conflict). None for a file means 'does not exist'."""
    if ours == theirs:
        return ours
    if theirs == base:
        return ours                                    # nobody else touched it
    if ours == base:
        return theirs                                  # we did not change it after all
    if base is None or ours is None or theirs is None:
        return None                                    # created or deleted on both sides differently
    b, o, t = (x.splitlines(keepends=True) for x in (base, ours, theirs))
    ho, ht = _hunks(b, o), _hunks(b, t)
    for x in ho:
        for y in ht:
            if _clash(x, y):
                return None
    merged_hunks = sorted({(h[0], h[1], tuple(h[2])) for h in ho + ht}, key=lambda h: (h[0], h[1] != h[0], h[1]))
    out: list[str] = []
    pos = 0
    for start, end, repl in merged_hunks:
        if start < pos:                                # a duplicate of a change already applied
            continue
        out.extend(b[pos:start])
        out.extend(repl)
        pos = end
    out.extend(b[pos:])
    return "".join(out)


def merge_files(base_files: dict, ours_files: dict, theirs_files: dict) -> tuple[dict, list[str]]:
    """Merge every file the engineer changed. Returns (files to write, paths that conflict)."""
    merged, conflicts = {}, []
    for path, ours in ours_files.items():
        result = merge(base_files.get(path), ours, theirs_files.get(path))
        if result is None:
            conflicts.append(path)
        elif result != theirs_files.get(path):
            merged[path] = result
    return merged, conflicts
