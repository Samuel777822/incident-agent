"""Human review report (plan 4.8): everything the agent learned, so a developer starts from the answer, not from zero."""
from __future__ import annotations

import json

from . import config as fx_config


def build_report(bug: dict, attempts: list[dict], decisions: list[dict], *, project_name: str, incident: dict, stop_reason: str) -> str:
    lines = [f"# Human review needed: {project_name}", "",
             f"**Why the agent stopped:** {stop_reason}", "",
             "## The error", f"- Message: {str(incident.get('message', ''))[:400]}",
             f"- Class (triage): {bug.get('bug_class')} / {bug.get('category') or 'n/a'}"]
    try:
        fp = json.loads(bug.get("fingerprint_json") or "{}")
        lines.append(f"- Where: {fp.get('where', 'unknown')} ({fp.get('error_type', '')})")
        if fp.get("files"):
            lines.append("- Files in the trace: " + ", ".join(fp["files"]))
    except ValueError:
        pass
    if bug.get("baseline_failing") is not None:
        lines.append(f"- Failing tests before any fix: {bug['baseline_failing']}")
    lines += ["", "## What was tried"]
    if not attempts:
        lines.append("- No fix attempt ran.")
    for i, a in enumerate(attempts, 1):
        name = fx_config.USER_MODE_NAMES.get(a["tier"], a["tier"])
        prog = "progress" if a.get("progress") else "no progress"
        lines.append(f"{i}. **{name}** ({a.get('model') or a['tier']}): {a['result']}, {prog}. "
                     f"{(a.get('error_summary') or '')[:260]}")
        if a.get("diagnosis"):
            lines.append(f"   - Diagnosis: {a['diagnosis'][:320]}")
    if bug.get("strong_diagnosis"):
        lines += ["", "## Best diagnosis so far (from a stronger model)", bug["strong_diagnosis"][:1500]]
    lines += ["", "## Suggested next step"]
    last = next((a for a in reversed(attempts) if a.get("diagnosis")), None)
    if bug.get("strong_diagnosis"):
        lines.append("Start from the stronger model's diagnosis above and check it against the files in the trace.")
    elif last:
        lines.append(f"Check the last diagnosis ({last['tier']}): {last['diagnosis'][:300]}")
    else:
        lines.append("Reproduce the error locally from the traceback; the agent could not produce a usable diagnosis.")
    spent = sum(float(a.get("cost_inr") or 0) for a in attempts)
    lines += ["", f"_Cost of this investigation: Rs {spent:.2f} across {len(attempts)} tries. "
                  "A review like this is not charged to your bars._"]
    return "\n".join(lines)[:30000]
