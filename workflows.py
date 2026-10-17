import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
from typing import Any
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


def _normalize_service_arg(service: Any = "shop-api") -> str:
    if isinstance(service, dict):
        return str(service.get("service") or "shop-api")
    if isinstance(service, str) and service.strip():
        s = service.strip()
        if s.startswith("{") and "service" in s:
            try:
                import json
                return str(json.loads(s).get("service") or "shop-api")
            except Exception:
                pass
        return s
    return "shop-api"


def _normalize_incident_id(val: Any = 0) -> int:
    if isinstance(val, dict):
        val = val.get("incident_id") or val.get("id")
    if val is not None and val != 0:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM incidents WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            row = conn.execute("SELECT id FROM incidents ORDER BY id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


@app.task(name="ingest-logs")
def ingest_logs_task(ctx: TaskContext, service: str = "shop-api") -> dict:
    """Task 1: Pulls the latest repository commit and ingests new log events into the database."""
    service = _normalize_service_arg(service)
    print("=" * 70)
    print(f" [Render Workflow] RUNNING TASK: ingest-logs (service: {service})")
    print("=" * 70)
    
    sync_and_tail(service)
    
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, signature, status, occurrences FROM incidents WHERE status = 'diagnosing' ORDER BY id ASC"
        ).fetchall()
        pending = [dict(r) for r in rows]
    finally:
        conn.close()
        
    print(f"[Render Workflow] Ingestion complete. Found {len(pending)} pending incident(s).")
    for inc in pending:
        print(f"  - Incident #{inc['id']}: {inc['signature']} (Occurrences: {inc['occurrences']})")
    print("=" * 70)
    
    return {
        "status": "success",
        "service": service,
        "pending_incidents_count": len(pending),
        "pending_incidents": pending,
    }


@app.task(name="diagnose-incident")
def diagnose_incident_task(ctx: TaskContext, incident_id: int = 0) -> dict:
    """Task 2: Performs AI root-cause analysis, token-safe evidence gathering, and writes the 6-section report."""
    resolved_id = _normalize_incident_id(incident_id)
    print("=" * 70)
    print(f" [Render Workflow] RUNNING TASK: diagnose-incident (incident_id: {resolved_id})")
    print("=" * 70)
    
    if resolved_id == 0:
        print("[Render Workflow] No incidents found in DB. Auto-running ingest-logs first...")
        ingest_logs_task.func(ctx, service="shop-api")
        resolved_id = _normalize_incident_id(0)
        
    if resolved_id == 0:
        msg = "No incidents available to diagnose in database."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}

    inc = get_incident(resolved_id)
    if not inc:
        msg = f"Incident #{resolved_id} not found."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}
        
    events = get_incident_events(inc["id"])
    if not events:
        msg = f"Incident #{resolved_id} has no log events."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}
        
    first = events[0]
    service = first["service"]
    folder = get_local_repo(service)
    files = collect_repository(folder)
    evidence_text, skipped = build_evidence_text(files, get_git_evidence(folder), first["traceback"])
    
    print(f"[Render Workflow] Diagnosing Incident #{resolved_id} ({first['message']}) using Groq...")
    result = diagnose_incident(first["message"], first["traceback"], evidence_text)
    save_diagnosis(inc["id"], result)
    
    print("-" * 70)
    print(f"DIAGNOSIS REPORT FOR INCIDENT #{resolved_id}")
    print("-" * 70)
    print(f"Category:     {result['category']}")
    print(f"Confidence:   {result['confidence']}")
    print(f"Root Cause:   {result['root_cause']}")
    print(f"Safe to Fix:  {result['safe_to_auto_fix']}")
    print("-" * 70)
    if result.get("report"):
        print(result["report"])
    print("=" * 70)
    
    return {
        "status": "success",
        "incident_id": resolved_id,
        "service": service,
        "category": result["category"],
        "confidence": result["confidence"],
        "root_cause": result["root_cause"],
        "safe_to_auto_fix": result["safe_to_auto_fix"],
        "summary": f"Incident #{resolved_id} [{result['category']} / {result['confidence']}]: {result['root_cause']}",
    }


@app.task(name="remediate-incident")
def remediate_incident_task(ctx: TaskContext, incident_id: int = 0) -> dict:
    """Task 3: Executes the test gate, targeted find-and-replace patching, branch creation, and PR/auto-merge."""
    resolved_id = _normalize_incident_id(incident_id)
    print("=" * 70)
    print(f" [Render Workflow] RUNNING TASK: remediate-incident (incident_id: {resolved_id})")
    print("=" * 70)
    
    if resolved_id == 0:
        print("[Render Workflow] No incident specified. Auto-running ingest & diagnose first...")
        ingest_logs_task.func(ctx, service="shop-api")
        resolved_id = _normalize_incident_id(0)

    if resolved_id == 0:
        msg = "No incidents available to remediate in database."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}

    inc = get_incident(resolved_id)
    if not inc:
        msg = f"Incident #{resolved_id} not found."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}
        
    events = get_incident_events(inc["id"])
    if not events:
        msg = f"Incident #{resolved_id} has no log events."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {"status": "error", "message": msg}
        
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (resolved_id,)).fetchone()
        row_dict = dict(row)
    finally:
        conn.close()

    if not row_dict.get("root_cause"):
        print(f"[Render Workflow] Incident #{resolved_id} not diagnosed yet. Diagnosing first...")
        diagnose_incident_task.func(ctx, incident_id=resolved_id)
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (resolved_id,)).fetchone()
            row_dict = dict(row)
        finally:
            conn.close()

    first = events[0]
    service = first["service"]
    repo_cfg = get_repo_config(service)
    folder = get_local_repo(service)
    files = collect_repository(folder)
    evidence_text, _ = build_evidence_text(files, get_git_evidence(folder), first["traceback"])
    
    print(f"[Render Workflow] Attempting autofix for Incident #{resolved_id}...")
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
    
    print("-" * 70)
    print(f"REMEDIATION RESULT FOR INCIDENT #{resolved_id}")
    print("-" * 70)
    print(f"Success:      {fix_res.get('success')}")
    print(f"Patched File: {fix_res.get('file_patched')}")
    print(f"PR URL:       {fix_res.get('pr_url')}")
    print(f"Auto Merged:  {fix_res.get('auto_merged')}")
    print(f"Reason:       {fix_res.get('reason')}")
    print("=" * 70)
    
    is_success = bool(fix_res.get("success"))
    return {
        "status": "success" if is_success else "remediation_failed",
        "incident_id": resolved_id,
        "service": service,
        "success": is_success,
        "file_patched": fix_res.get("file_patched"),
        "pr_url": fix_res.get("pr_url"),
        "auto_merged": fix_res.get("auto_merged", False),
        "reason": fix_res.get("reason"),
        "summary": f"Incident #{resolved_id}: " + (
            f"Fixed in {fix_res.get('file_patched')} and merged into main"
            if fix_res.get("auto_merged")
            else f"PR opened at {fix_res.get('pr_url')}" if fix_res.get("pr_url") else f"Fix status: {fix_res.get('reason')}"
        ),
    }


@app.task(name="full-pipeline")
def full_pipeline_workflow(ctx: TaskContext, service: str = "shop-api") -> dict:
    """End-to-end Render Workflow: Ingest -> Diagnose -> Remediate"""
    service = _normalize_service_arg(service)
    print("=" * 70)
    print(f" [Render Workflow] STARTING END-TO-END PIPELINE (service: {service})")
    print("=" * 70)
    
    ingest_res = ingest_logs_task.func(ctx, service=service)
    pending = ingest_res.get("pending_incidents", [])
    
    if not pending:
        msg = f"All quiet! No pending incidents found for service '{service}'."
        print(f"[Render Workflow] {msg}")
        print("=" * 70)
        return {
            "status": "all_quiet",
            "service": service,
            "processed": 0,
            "message": msg,
        }

    target = pending[0]
    inc_id = target["id"]
    print(f"\n[Render Workflow] Processing pending Incident #{inc_id} ({target['signature']})...\n")
    
    diag_res = diagnose_incident_task.func(ctx, incident_id=inc_id)
    repo_cfg = get_repo_config(service)
    fix_res = None
    if repo_cfg.get("mode") in ("pr", "auto"):
        fix_res = remediate_incident_task.func(ctx, incident_id=inc_id)
        
    print("\n" + "=" * 70)
    print(f" [Render Workflow] END-TO-END PIPELINE FINISHED FOR INCIDENT #{inc_id}")
    print("=" * 70)
    print(f"Service:     {service}")
    print(f"Incident:    #{inc_id} ({target['signature']})")
    print(f"Category:    {diag_res.get('category')}")
    print(f"Root Cause:  {diag_res.get('root_cause')}")
    if fix_res:
        print(f"Remediation: {fix_res.get('summary')}")
    print("=" * 70 + "\n")
    
    return {
        "status": "success",
        "service": service,
        "processed": 1,
        "incident_id": inc_id,
        "category": diag_res.get("category"),
        "root_cause": diag_res.get("root_cause"),
        "remediation_summary": fix_res.get("summary") if fix_res else "Triage report only",
        "summary": f"Incident #{inc_id} processed: {diag_res.get('root_cause')}",
    }


if __name__ == "__main__":
    if "--run" in sys.argv:
        svc = sys.argv[sys.argv.index("--run") + 1] if len(sys.argv) > sys.argv.index("--run") + 1 else "shop-api"
        full_pipeline_workflow.func(None, service=svc)
    elif "--task" in sys.argv:
        t_name = sys.argv[sys.argv.index("--task") + 1]
        if t_name == "ingest-logs":
            ingest_logs_task.func(None, service="shop-api")
        elif t_name == "diagnose-incident":
            diagnose_incident_task.func(None, incident_id=0)
        elif t_name == "remediate-incident":
            remediate_incident_task.func(None, incident_id=0)
        elif t_name == "full-pipeline":
            full_pipeline_workflow.func(None, service="shop-api")
    else:
        print("[Render Workflows] Starting task worker server...")
        app.start()
