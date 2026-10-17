import sys
from pathlib import Path

from config import get_repo_config
from db import get_fix_count, save_fix, update_incident_status
from patcher import apply_patch, generate_patch
from pr import commit_fix, create_fix_branch, open_and_maybe_merge_pr, run_git
from tester import run_tests


def attempt_autofix(incident, diagnosis, repo_folder, repo_cfg, files_text):
    incident_id = incident["id"]
    service = repo_cfg.get("service") or incident.get("service", "unknown")
    mode = repo_cfg.get("mode", "report").lower()
    base_branch = repo_cfg.get("branch", "main")
    test_cmd = repo_cfg.get("test_command", "pytest")
    repo_url = repo_cfg.get("url", "")

    print(f"\n===== AUTO-FIX WORKFLOW (Mode: '{mode}') =====")

    # 1. Check customer mode dial
    if mode == "report":
        print("[Auto-Fix] Customer mode is 'report'. No code change or PR will be attempted.")
        return {"status": "skipped", "reason": "mode_report"}

    # 2. Check retry limit (max 2 attempts per incident)
    attempts = get_fix_count(incident_id)
    if attempts >= 2:
        print(f"[Auto-Fix] Incident #{incident_id} already had {attempts} fix attempts. Escalating to human.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "max_attempts_exceeded"}

    # 3. Check diagnosis safety preconditions
    if diagnosis.get("category") != "code_bug":
        print(f"[Auto-Fix] Category is '{diagnosis.get('category')}' (not code_bug). Skipping automated fix.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "not_code_bug"}

    if diagnosis.get("still_present_in_current_code") != "yes":
        print("[Auto-Fix] Bug is not confirmed present in current code. Skipping.")
        return {"status": "skipped", "reason": "not_present_in_code"}

    if diagnosis.get("confidence") != "high":
        print(f"[Auto-Fix] Confidence is '{diagnosis.get('confidence')}' (requires 'high'). Skipping.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "insufficient_confidence"}

    if not diagnosis.get("safe_to_auto_fix"):
        print("[Auto-Fix] Model marked safe_to_auto_fix as False. Skipping.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "marked_unsafe"}

    # 4. Run tests BEFORE applying patch
    print(f"[Auto-Fix] Running tests before patch: '{test_cmd}'...")
    before_passed, before_out, _ = run_tests(repo_folder, test_cmd)
    print(f"[Auto-Fix] Tests before patch passed: {before_passed}")

    # 5. Generate patch with LLM
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
    except Exception as err:
        print(f"[Auto-Fix] Patch generation failed: {err}")
        save_fix(incident_id, None, None, None, False)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"patch_generation_failed: {err}"}

    # 6. Create fix branch and apply patch
    branch_name = f"fix/incident-{incident_id}"
    try:
        create_fix_branch(repo_folder, incident_id, base_branch=base_branch)
        fixed_content = apply_patch(repo_folder, patch)
        print(f"[Auto-Fix] Patch applied on branch '{branch_name}'.")
    except Exception as err:
        print(f"[Auto-Fix] Failed to create branch or apply patch: {err}")
        save_fix(incident_id, branch_name, patch.get("file_path"), None, False)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"apply_patch_failed: {err}"}

    # 7. Run tests AFTER applying patch
    print(f"[Auto-Fix] Running tests after patch: '{test_cmd}'...")
    after_passed, after_out, _ = run_tests(repo_folder, test_cmd)
    print(f"[Auto-Fix] Tests after patch passed: {after_passed}")

    save_fix(incident_id, branch_name, patch["file_path"], fixed_content, after_passed)

    if not after_passed:
        print(f"[Auto-Fix] Tests failed after patch! Aborting fix on {branch_name}.")
        try:
            run_git(["checkout", base_branch], repo_folder)
        except Exception:
            pass
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "tests_failed_after_patch"}

    # 8. Determine if auto-merge is permitted
    # Safety gate: tests must have failed before and passed after to auto-merge
    allow_auto_merge = False
    if mode == "auto":
        if before_passed:
            print("[Auto-Fix] Notice: Tests passed both BEFORE and AFTER patch.")
            print("           No test covers this bug directly, so downgrading to PR-only for human review.")
            allow_auto_merge = False
        else:
            allow_auto_merge = True

    # 9. Commit, Push and Open PR
    print(f"[Auto-Fix] Committing fix to branch '{branch_name}'...")
    try:
        commit_fix(repo_folder, patch["file_path"], incident_id, patch["explanation"])
    except Exception as err:
        print(f"[Auto-Fix] Git commit failed: {err}")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"commit_failed: {err}"}

    print(f"[Auto-Fix] Opening PR (auto_merge={allow_auto_merge})...")
    pr_url, merged = open_and_maybe_merge_pr(
        repo_folder=repo_folder,
        repo_url=repo_url,
        branch_name=branch_name,
        base_branch=base_branch,
        incident_id=incident_id,
        title=f"fix: incident #{incident_id} ({diagnosis.get('root_cause')[:60]})",
        body=f"## Automated Incident Remediation\n\n- **Incident ID:** #{incident_id}\n- **Root Cause:** {diagnosis.get('root_cause')}\n- **Fix Explanation:** {patch.get('explanation')}\n- **Tests Passed:** {'Yes (before: failed, after: passed)' if not before_passed and after_passed else 'Yes'}\n",
        auto_merge=allow_auto_merge,
    )

    if merged:
        print(f"[Auto-Fix] Success! PR merged into '{base_branch}'. Incident #{incident_id} resolved.")
        update_incident_status(incident_id, "resolved", pr_url=pr_url)
        return {"status": "resolved", "pr_url": pr_url, "branch": branch_name}
    else:
        print(f"[Auto-Fix] PR opened: {pr_url}. Awaiting human review/merge.")
        update_incident_status(incident_id, "pr_opened", pr_url=pr_url)
        return {"status": "pr_opened", "pr_url": pr_url, "branch": branch_name}
