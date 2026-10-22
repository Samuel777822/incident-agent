"""Generate a constrained patch and rely on the customer's GitHub CI to validate it."""
import ast
import difflib
from pathlib import Path

from db import get_fix_count, save_fix, update_fix_ci_result, update_incident_pr, update_incident_status
from patcher import apply_patch, generate_patch
from pr import commit_fix, create_fix_branch, open_and_maybe_merge_pr, run_git
from tester import run_tests  # Kept as a compatibility hook; remediation never invokes it.

MAX_ATTEMPTS = 2


def _cleanup_workspace(repo_folder, base_branch):
    try:
        run_git(["reset", "--hard"], repo_folder)
        run_git(["checkout", base_branch], repo_folder)
    except Exception as err:
        print(f"[Auto-Fix] Workspace cleanup warning: {err}")


def attempt_autofix(incident, diagnosis, repo_folder, repo_cfg, files_text):
    incident_id = incident["id"]
    mode = repo_cfg.get("mode", "report").lower()
    base_branch = repo_cfg.get("branch", "master")
    repo_url = repo_cfg.get("url", "")

    print(f"\n===== AUTO-FIX WORKFLOW (Mode: '{mode}', Service: '{incident.get('service')}') =====")
    print(f"[Auto-Fix] Workspace directory: {repo_folder} | Target branch: {base_branch}")

    # 1. Customer mode check
    if mode == "report":
        print("[Auto-Fix] Mode is 'report'. No code modification or PR will be attempted.")
        return {"status": "skipped", "reason": "mode_report"}

    # 2. Retry limit check
    attempts = get_fix_count(incident_id)
    if attempts >= MAX_ATTEMPTS:
        print(f"[Auto-Fix] Incident #{incident_id} already reached maximum ({MAX_ATTEMPTS}) fix attempts. Escalating to human.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "max_attempts_exceeded"}

    # 3. Safety preconditions
    if diagnosis.get("category") != "code_bug":
        print(f"[Auto-Fix] Category is '{diagnosis.get('category')}', not 'code_bug'. Skipping automated fix.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "not_code_bug"}

    if diagnosis.get("still_present_in_current_code") != "yes":
        print("[Auto-Fix] The bug is not confirmed present in current code. Skipping fix.")
        return {"status": "skipped", "reason": "not_present_in_code"}

    if diagnosis.get("confidence") != "high":
        print(f"[Auto-Fix] Confidence is '{diagnosis.get('confidence')}' (requires 'high'). Skipping automated fix.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "insufficient_confidence"}

    if not diagnosis.get("safe_to_auto_fix"):
        print("[Auto-Fix] Diagnosis marked safe_to_auto_fix as False. Escalating to human.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "marked_unsafe"}

    # 4. Generate a minimal source-only patch. Customer code is never executed here.
    print("[Auto-Fix] Generating targeted find-and-replace patch...")
    try:
        patch = generate_patch(
            repo_folder=repo_folder,
            incident_message=incident.get("message", ""),
            traceback=incident.get("traceback", ""),
            root_cause=diagnosis.get("root_cause", ""),
            recommended_fix=diagnosis.get("recommended_fix", ""),
            files_text=files_text,
        )
        print(f"[Auto-Fix] Patch generated for file: {patch['file_path']}")
        print(f"[Auto-Fix] Explanation: {patch.get('explanation')}")
    except Exception as err:
        print(f"[Auto-Fix] Patch generation failed: {err}")
        save_fix(incident_id, None, None, None, None, "")
        update_fix_ci_result(incident_id, "not_submitted")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"patch_generation_failed: {err}"}

    # 5. Create fix branch, apply the patch, and parse it without executing it.
    branch_name = f"fix/incident-{incident_id}"
    try:
        source_path = Path(repo_folder) / patch["file_path"]
        original_content = source_path.read_text(encoding="utf-8")
        create_fix_branch(repo_folder, incident_id, base_branch=base_branch)
        fixed_content = apply_patch(repo_folder, patch)
        ast.parse(fixed_content, filename=patch["file_path"])
        diff = "".join(difflib.unified_diff(
            original_content.splitlines(keepends=True), fixed_content.splitlines(keepends=True),
            fromfile=f"a/{patch['file_path']}", tofile=f"b/{patch['file_path']}"))
        print(f"[Auto-Fix] Patch applied on branch '{branch_name}'.")
    except Exception as err:
        print(f"[Auto-Fix] Failed to create branch or apply patch: {err}")
        save_fix(incident_id, branch_name, patch.get("file_path"), None, None, "")
        update_fix_ci_result(incident_id, "not_submitted")
        _cleanup_workspace(repo_folder, base_branch)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"apply_patch_failed: {err}"}

    # Save the reviewable diff before publishing the branch/PR.
    save_fix(incident_id, branch_name, patch["file_path"], fixed_content, None, diff)

    allow_auto_merge = mode == "auto"

    # 9. Commit, push, open PR
    try:
        commit_fix(repo_folder, patch["file_path"], incident_id, patch.get("explanation", ""))
    except Exception as err:
        print(f"[Auto-Fix] Git commit failed: {err}")
        _cleanup_workspace(repo_folder, base_branch)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"commit_failed: {err}"}

    body = (
        "## Automated incident remediation\n\n"
        f"- **Incident:** #{incident_id}\n"
        f"- **Root cause:** {diagnosis.get('root_cause')}\n"
        f"- **Fix:** {patch.get('explanation')}\n"
        "- **Validation:** customer GitHub Actions checks are required before auto-merge.\n"
    )

    def record_ci(status, url, number):
        update_incident_pr(incident_id, url, number, status)
        update_fix_ci_result(incident_id, status)

    print(f"[Auto-Fix] Opening PR (auto_merge={allow_auto_merge})...")
    try:
        pr_url, merged = open_and_maybe_merge_pr(
            repo_folder=repo_folder,
            repo_url=repo_url,
            branch_name=branch_name,
            base_branch=base_branch,
            incident_id=incident_id,
            title=f"fix: incident #{incident_id} ({(diagnosis.get('root_cause') or '')[:60]})",
            body=body,
            auto_merge=allow_auto_merge,
            on_ci_update=record_ci,
        )
    except Exception as err:
        print(f"[Auto-Fix] PR step failed: {err}")
        pr_url, merged = None, False

    _cleanup_workspace(repo_folder, base_branch)

    if not pr_url:
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "pr_not_opened"}

    if merged:
        print(f"[Auto-Fix] PR merged into '{base_branch}'. Incident #{incident_id} resolved.")
        update_incident_status(incident_id, "resolved", pr_url=pr_url)
        return {"status": "resolved", "pr_url": pr_url, "branch": branch_name}

    print(f"[Auto-Fix] PR opened: {pr_url}. Waiting for human review and merge.")
    update_incident_status(incident_id, "pr_opened", pr_url=pr_url)
    return {"status": "pr_opened", "pr_url": pr_url, "branch": branch_name}
