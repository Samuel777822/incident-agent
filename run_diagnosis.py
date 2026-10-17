import sys

from db import get_incident, get_incident_events, save_diagnosis
from repo_sync import get_local_repo
from evidence import collect_repository
from git_evidence import get_git_evidence
from diagnose import diagnose_incident
from config import get_repo_config
from autofix import attempt_autofix

MAX_FILE_CHARS = 5_000   # ~1,250 tokens; strictly preserves headroom for Groq 8k TPM limit


def _priority(path, traceback_files):
    """Lower number = higher priority = included first."""
    name = path.lower()
    if path in traceback_files:
        return 0                          # file mentioned in the traceback
    if "test" in name:
        return 1                          # test files
    if name in ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"):
        return 2                          # dependency manifests
    return 3                              # everything else


def build_evidence_text(files, git_text, traceback=""):
    # Extract filenames mentioned in the traceback so we can prioritise them.
    import re, os
    frame_re = re.compile(r'File "([^"]+)"')
    traceback_files = {
        os.path.basename(p)
        for p in frame_re.findall(traceback or "")
        if "site-packages" not in p
    }

    ordered = sorted(
        files,
        key=lambda p: (_priority(p, traceback_files), len(files[p]))
    )

    parts = ["===== CURRENT REPOSITORY FILES (latest commit on the branch) ====="]
    used, skipped = 0, []
    for path in ordered:
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
    files = collect_repository(folder)
    evidence_text, skipped = build_evidence_text(files, get_git_evidence(folder), first["traceback"])
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
        print(f"\n[Mode: '{mode}'] Diagnosis complete. Report recorded. (Set 'mode': 'pr' or 'auto' in repos.json to enable auto-fix)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else None)