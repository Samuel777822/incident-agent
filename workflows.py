import sys
from pathlib import Path
from render import TaskContext, Workflows

from config import get_repo_config
from db import get_connection, get_incident, get_incident_events, save_diagnosis
from evidence import collect_repository
from git_evidence import get_git_evidence
from diagnose import diagnose_incident
from autofix import attempt_autofix
from repo_sync import get_local_repo
from sync_and_tail import sync_and_tail
from run_diagnosis import build_evidence_text

app = Workflows()


@app.task(name="ingest-logs")
def ingest_logs_task(ctx: TaskContext, service: str = "shop-api") -> dict:
    """Task 1: Pulls the latest repository commit and ingests new log events into the database."""
    print(f"[Render Workflow] Running ingest_logs_task for '{service}'...")
    sync_and_tail(service)
    
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, signature, status, occurrences FROM incidents WHERE status = 'diagnosing'"
        ).fetchall()
        pending = [dict(r) for r in rows]
    finally:
        conn.close()
        
    return {"service": service, "pending_incidents": pending}


@app.task(name="diagnose-incident")
def diagnose_incident_task(ctx: TaskContext, incident_id: int) -> dict:
    """Task 2: Performs AI root-cause analysis, token-safe evidence gathering, and writes the 6-section report."""
    print(f"[Render Workflow] Running diagnose_incident_task for incident #{incident_id}...")
    inc = get_incident(incident_id)
    if not inc:
        return {"status": "error", "message": f"Incident #{incident_id} not found"}
        
    events = get_incident_events(inc["id"])
    if not events:
        return {"status": "error", "message": f"Incident #{incident_id} has no events"}
        
    first = events[0]
    service = first["service"]
    folder = get_local_repo(service)
    files = collect_repository(folder)
    evidence_text, skipped = build_evidence_text(files, get_git_evidence(folder), first["traceback"])
    
    result = diagnose_incident(first["message"], first["traceback"], evidence_text)
    save_diagnosis(inc["id"], result)
    
    return {
        "incident_id": incident_id,
        "service": service,
        "category": result["category"],
        "confidence": result["confidence"],
        "root_cause": result["root_cause"],
        "still_present_in_current_code": result["still_present_in_current_code"],
        "safe_to_auto_fix": result["safe_to_auto_fix"],
        "report": result["report"],
    }


@app.task(name="remediate-incident")
def remediate_incident_task(ctx: TaskContext, incident_id: int) -> dict:
    """Task 3: Executes the test gate, targeted find-and-replace patching, branch creation, and PR/auto-merge."""
    print(f"[Render Workflow] Running remediate_incident_task for incident #{incident_id}...")
    inc = get_incident(incident_id)
    if not inc:
        return {"status": "error", "message": f"Incident #{incident_id} not found"}
        
    events = get_incident_events(inc["id"])
    first = events[0]
    service = first["service"]
    repo_cfg = get_repo_config(service)
    
    folder = get_local_repo(service)
    files = collect_repository(folder)
    evidence_text, _ = build_evidence_text(files, get_git_evidence(folder), first["traceback"])
    
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        row_dict = dict(row)
    finally:
        conn.close()
        
    fix_res = attempt_autofix(
        incident={**inc, "message": first["message"], "traceback": first["traceback"], "service": service},
        diagnosis={
            "category": row_dict.get("category"),
            "confidence": row_dict.get("confidence"),
            "root_cause": row_dict.get("root_cause"),
            "still_present_in_current_code": "yes",
            "safe_to_auto_fix": True,
        },
        repo_folder=folder,
        repo_cfg=repo_cfg,
        files_text=evidence_text,
    )
    return {"incident_id": incident_id, "result": fix_res}


@app.task(name="full-pipeline")
def full_pipeline_workflow(ctx: TaskContext, service: str = "shop-api") -> dict:
    """End-to-end Render Workflow: Ingest -> Diagnose -> Remediate"""
    print(f"[Render Workflow] Orchestrating end-to-end incident pipeline for '{service}'...")
    ingest_res = ingest_logs_task.func(ctx, service=service)
    pending = ingest_res.get("pending_incidents", [])
    
    pipeline_results = []
    for item in pending:
        inc_id = item["id"]
        diag_res = diagnose_incident_task.func(ctx, incident_id=inc_id)
        repo_cfg = get_repo_config(service)
        fix_res = None
        if repo_cfg.get("mode") in ("pr", "auto"):
            fix_res = remediate_incident_task.func(ctx, incident_id=inc_id)
        pipeline_results.append({
            "incident_id": inc_id,
            "diagnosis": diag_res,
            "remediation": fix_res
        })
        
    return {"service": service, "processed": len(pipeline_results), "results": pipeline_results}


if __name__ == "__main__":
    if "--run" in sys.argv:
        svc = sys.argv[sys.argv.index("--run") + 1] if len(sys.argv) > sys.argv.index("--run") + 1 else "shop-api"
        full_pipeline_workflow.func(None, service=svc)
    else:
        print("[Render Workflows] Starting task worker server...")
        app.start()
