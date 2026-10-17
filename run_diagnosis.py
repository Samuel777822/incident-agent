import sys

from db import get_incident, get_incident_events, save_diagnosis
from repo_sync import get_local_repo
from evidence import collect_repository
from git_evidence import get_git_evidence
from diagnose import diagnose_incident

MAX_FILE_CHARS = 40_000


def build_evidence_text(files, git_text):
    parts = ["===== CURRENT REPOSITORY FILES (latest commit on the branch) ====="]
    used, skipped = 0, []
    for path in sorted(files, key=lambda p: len(files[p])):
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
    evidence_text, skipped = build_evidence_text(files, get_git_evidence(folder))
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


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else None)