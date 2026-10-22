import os
import re
import sys

from autofix import attempt_autofix
from config import get_repo_config
from db import get_incident, get_incident_events, save_diagnosis
from diagnose import diagnose_incident
from evidence import collect_repository
from git_evidence import get_git_evidence
from repo_sync import get_local_repo

# Groq's free tier allows about 8,000 tokens per minute for gpt-oss-120b.
# These caps keep one diagnosis under that. Lower them if you see rate-limit errors.
MAX_FILE_CHARS = 5_000            # budget for all other files together
MAX_TRACEBACK_FILE_CHARS = 4_000  # cap for each file named in the traceback
MANIFESTS = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"}
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')


def _traceback_frames(traceback):
    frames = []
    for path, line in FRAME_RE.findall(traceback or ""):
        if "site-packages" in path:
            continue
        frames.append((os.path.basename(path.replace("\\", "/")), int(line)))
    return frames


def _window(text, line_no, max_chars):
    """Return the whole file, or a window of lines around the failing line."""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    lo = hi = max(0, min(line_no - 1, len(lines) - 1))
    size = len(lines[lo]) + 1
    while True:
        grew = False
        if lo > 0 and size + len(lines[lo - 1]) + 1 <= max_chars:
            lo -= 1
            size += len(lines[lo]) + 1
            grew = True
        if hi < len(lines) - 1 and size + len(lines[hi + 1]) + 1 <= max_chars:
            hi += 1
            size += len(lines[hi]) + 1
            grew = True
        if not grew:
            break
    note = f"# ... file truncated: showing lines {lo + 1}-{hi + 1} of {len(lines)} ...\n"
    return note + "\n".join(lines[lo : hi + 1])


def _priority(path):
    name = path.lower()
    if "test" in name:
        return 1
    if name.split("/")[-1] in MANIFESTS:
        return 2
    return 3


def build_evidence_text(files, git_text, traceback=""):
    # Files named in the traceback always come first and are never dropped.
    failing = {}
    for name, line_no in _traceback_frames(traceback):
        for path in files:
            if path.split("/")[-1] == name and path not in failing:
                failing[path] = line_no

    parts = ["===== CURRENT REPOSITORY FILES (latest commit on the branch) ====="]
    for path, line_no in failing.items():
        shown = _window(files[path], line_no, MAX_TRACEBACK_FILE_CHARS)
        parts.append(f"===== FILE: {path} (named in the traceback) =====\n{shown}\n")

    used, skipped = 0, []
    others = [p for p in files if p not in failing]
    for path in sorted(others, key=lambda p: (_priority(p), len(files[p]))):
        block = f"===== FILE: {path} =====\n{files[path]}\n"
        if used + len(block) > MAX_FILE_CHARS:
            skipped.append(path)
            continue
        parts.append(block)
        used += len(block)
    if skipped:
        parts.append("(Files left out because of the size limit: " + ", ".join(skipped) + ")")
    parts.append("===== GIT HISTORY =====\n" + git_text)
    return "\n".join(parts), skipped


def gather_evidence(folder, traceback):
    files = collect_repository(folder)
    git_text = get_git_evidence(folder, commits=5, per_commit_chars=900)
    text, skipped = build_evidence_text(files, git_text, traceback)
    return text, files, skipped


def run(incident_id=None):
    inc = get_incident(incident_id)
    if not inc:
        print("No incident waiting for a diagnosis.")
        return
    events = get_incident_events(inc["id"])
    if not events:
        print("This incident has no log events.")
        return
    first = events[0]
    service = first["service"]
    print(f"Incident {inc['id']} | service: {service} | seen {inc['occurrences']} times")

    folder = get_local_repo(service)
    evidence_text, files, skipped = gather_evidence(folder, first["traceback"])
    print(f"Files: {len(files)} collected, {len(skipped)} left out | evidence: {len(evidence_text)} characters")

    try:
        result = diagnose_incident(first["message"], first["traceback"], evidence_text)
    except Exception as err:
        print("Diagnosis failed. The incident stays 'diagnosing':", err)
        return

    save_diagnosis(inc["id"], result)
    print("\n===== SAVED =====")
    print("category:", result["category"])
    print("confidence:", result["confidence"])
    print("still present in current code:", result["still_present_in_current_code"])
    print("safe to auto-fix:", result["safe_to_auto_fix"])
    print("root cause:", result["root_cause"])
    print("tokens used:", result.get("tokens_used"))
    print("\n===== REPORT =====\n")
    print(result["report"])

    repo_cfg = get_repo_config(service)
    mode = repo_cfg.get("mode", "report")
    if mode in ("pr", "auto"):
        attempt_autofix(
            incident={**inc, "message": first["message"], "traceback": first["traceback"], "service": service},
            diagnosis=result,
            repo_folder=folder,
            repo_cfg=repo_cfg,
            files_text=evidence_text,
        )
    else:
        print(f"\n[Mode: '{mode}'] Diagnosis complete. Report recorded. (Set 'mode' to 'pr' or 'auto' in repos.json to enable auto-fix)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else None)