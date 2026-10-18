import json
import sys
from typing import Any

from render import Retry, TaskContext, Workflows

from autofix import attempt_autofix
from config import get_repo_config
from db import get_connection, get_incident, get_incident_events, save_diagnosis
from diagnose import diagnose_incident
from repo_sync import get_local_repo
from run_diagnosis import gather_evidence
from sync_and_tail import sync_and_tail

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

app = Workflows()


def _service_name(value: Any = "shop-api") -> str:
    if isinstance(value, dict):
        value = value.get("service")
    return str(value).strip() if value else "shop-api"


def _pick_incident_id(value: Any = 0) -> int:
    if isinstance(value, dict):
        value = value.get("incident_id") or value.get("id")
    try:
        if value and int(value) > 0:
            return int(value)
    except (TypeError, ValueError):
        pass
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM incidents WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _load_incident_row(incident_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def run_ingest(service: str) -> dict:
    sync_and_tail(service)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, signature, status, occurrences FROM incidents "
            "WHERE resolved_at IS NULL ORDER BY id"
        ).fetchall()
        pending = [dict(r) for r in rows]
    finally:
        conn.close()
    print(f"[pipeline] ingest done for {service}: {len(pending)} unresolved incident(s)")
    return {"status": "success", "service": service, "pending_incidents": pending}


def run_diagnose(incident_id: int) -> dict:
    inc = get_incident(incident_id)
    if not inc:
        return {"status": "error", "message": f"Incident #{incident_id} not found."}
    events = get_incident_events(inc["id"])
    if not events:
        return {"status": "error", "message": f"Incident #{incident_id} has no log events."}

    first = events[0]
    service = first["service"]
    folder = get_local_repo(service)
    evidence_text, _files, _skipped = gather_evidence(folder, first["traceback"])

    print(f"[pipeline] diagnosing incident #{incident_id} ({first['message']})")
    result = diagnose_incident(first["message"], first["traceback"], evidence_text)
    save_diagnosis(inc["id"], result)

    print("-" * 60)
    print(f"category: {result['category']} | confidence: {result['confidence']}")
    print(f"root cause: {result['root_cause']}")
    print(f"safe to auto-fix: {result['safe_to_auto_fix']}")
    print("-" * 60)
    print(result["report"])

    return {
        "status": "success",
        "incident_id": inc["id"],
        "service": service,
        "category": result["category"],
        "confidence": result["confidence"],
        "root_cause": result["root_cause"],
        "safe_to_auto_fix": result["safe_to_auto_fix"],
    }


def run_remediate(incident_id: int) -> dict:
    inc = get_incident(incident_id)
    if not inc:
        return {"status": "error", "message": f"Incident #{incident_id} not found."}
    events = get_incident_events(inc["id"])
    if not events:
        return {"status": "error", "message": f"Incident #{incident_id} has no log events."}

    row = _load_incident_row(incident_id)
    if not row.get("root_cause"):
        run_diagnose(incident_id)
        row = _load_incident_row(incident_id)
    if not row.get("root_cause"):
        return {"status": "error", "message": "Could not diagnose the incident first."}

    first = events[0]
    service = first["service"]
    repo_cfg = get_repo_config(service)
    folder = get_local_repo(service)
    evidence_text, _files, _skipped = gather_evidence(folder, first["traceback"])

    try:
        details = json.loads(row.get("explanation") or "{}")
    except json.JSONDecodeError:
        details = {}
    diagnosis = {
        "category": row.get("category"),
        "confidence": row.get("confidence"),
        "root_cause": row.get("root_cause"),
        "recommended_fix": details.get("recommended_fix", ""),
        "still_present_in_current_code": details.get("still_present_in_current_code", "unknown"),
        "safe_to_auto_fix": details.get("safe_to_auto_fix", False),
    }

    fix = attempt_autofix(
        incident={**inc, "message": first["message"], "traceback": first["traceback"], "service": service},
        diagnosis=diagnosis,
        repo_folder=folder,
        repo_cfg=repo_cfg,
        files_text=evidence_text,
    )
    fix_status = fix.get("status")
    summaries = {
        "resolved": "fix merged into the base branch",
        "pr_opened": f"pull request opened: {fix.get('pr_url')}",
        "needs_human": f"needs a human ({fix.get('reason')})",
        "skipped": f"no change made ({fix.get('reason')})",
    }
    summary = summaries.get(fix_status, f"unknown result: {fix}")
    print(f"[pipeline] incident #{incident_id}: {summary}")
    return {
        "status": "success" if fix_status in ("resolved", "pr_opened") else "needs_attention",
        "incident_id": incident_id,
        "service": service,
        "fix_status": fix_status,
        "pr_url": fix.get("pr_url"),
        "reason": fix.get("reason"),
        "summary": summary,
    }


def run_full_pipeline(service: str) -> dict:
    ingest = run_ingest(service)
    unresolved = ingest["pending_incidents"]
    if not unresolved:
        return {"status": "all_quiet", "service": service, "processed": 0}

    waiting = [i for i in unresolved if i["status"] == "diagnosing"]
    if not waiting:
        return {
            "status": "no_new_incidents",
            "service": service,
            "processed": 0,
            "unresolved_count": len(unresolved),
        }

    incident_id = waiting[0]["id"]
    diagnosis = run_diagnose(incident_id)
    if diagnosis.get("status") != "success":
        return {"status": "error", "service": service, "detail": diagnosis}

    fix = None
    if get_repo_config(service).get("mode") in ("pr", "auto"):
        fix = run_remediate(incident_id)

    return {
        "status": "success",
        "service": service,
        "processed": 1,
        "incident_id": incident_id,
        "category": diagnosis.get("category"),
        "root_cause": diagnosis.get("root_cause"),
        "remediation": fix.get("summary") if fix else "report only",
    }


@app.task(name="ingest_logs")
def ingest_logs_task(ctx: TaskContext, service: str = "shop-api") -> dict:
    return run_ingest(_service_name(service))


@app.task(
    name="diagnose_incident",
    retry=Retry(max_retries=2, wait_duration_ms=60000, backoff_scaling=1.0),
)
def diagnose_incident_task(ctx: TaskContext, incident_id: int = 0) -> dict:
    resolved = _pick_incident_id(incident_id)
    if resolved == 0:
        return {"status": "error", "message": "No unresolved incident to diagnose."}
    return run_diagnose(resolved)


@app.task(name="remediate_incident")
def remediate_incident_task(ctx: TaskContext, incident_id: int = 0) -> dict:
    resolved = _pick_incident_id(incident_id)
    if resolved == 0:
        return {"status": "error", "message": "No unresolved incident to remediate."}
    return run_remediate(resolved)


@app.task(name="full_pipeline")
def full_pipeline_task(ctx: TaskContext, service: str = "shop-api") -> dict:
    return run_full_pipeline(_service_name(service))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--run" in args:
        i = args.index("--run")
        svc = args[i + 1] if len(args) > i + 1 else "shop-api"
        print(json.dumps(run_full_pipeline(svc), indent=2, default=str))
    else:
        app.start()
