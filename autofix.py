from db import get_fix_count, save_fix, update_incident_status
from patcher import apply_patch, generate_patch
from pr import commit_fix, create_fix_branch, open_and_maybe_merge_pr, run_git
from tester import run_tests

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
    base_branch = repo_cfg.get("branch", "main")
    test_cmd = repo_cfg.get("test_command", "pytest")
    repo_url = repo_cfg.get("url", "")

    print(f"\n===== AUTO-FIX WORKFLOW (Mode: '{mode}') =====")

    # 1. Customer mode dial
    if mode == "report":
        print("[Auto-Fix] Customer mode is 'report'. No code change or PR will be attempted.")
        return {"status": "skipped", "reason": "mode_report"}

    # 2. Retry limit
    attempts = get_fix_count(incident_id)
    if attempts >= MAX_ATTEMPTS:
        print(f"[Auto-Fix] Incident #{incident_id} already had {attempts} fix attempts. Escalating to a human.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "max_attempts_exceeded"}

    # 3. Safety preconditions (all must hold)
    if diagnosis.get("category") != "code_bug":
        print(f"[Auto-Fix] Category is '{diagnosis.get('category')}', not code_bug. Skipping automated fix.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "not_code_bug"}

    if diagnosis.get("still_present_in_current_code") != "yes":
        print("[Auto-Fix] The bug is not confirmed present in the current code. Skipping.")
        return {"status": "skipped", "reason": "not_present_in_code"}

    if diagnosis.get("confidence") != "high":
        print(f"[Auto-Fix] Confidence is '{diagnosis.get('confidence')}' (needs 'high'). Skipping.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "insufficient_confidence"}

    if not diagnosis.get("safe_to_auto_fix"):
        print("[Auto-Fix] safe_to_auto_fix is False. Skipping.")
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "marked_unsafe"}

    # 4. Tests BEFORE the patch
    print(f"[Auto-Fix] Running tests before the patch: '{test_cmd}'...")
    before_passed, _before_out, _ = run_tests(repo_folder, test_cmd)
    print(f"[Auto-Fix] Tests before the patch passed: {before_passed}")

    # 5. Generate the patch
    print("[Auto-Fix] Generating a targeted find-and-replace patch...")
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

    # 6. Branch and apply
    branch_name = f"fix/incident-{incident_id}"
    try:
        create_fix_branch(repo_folder, incident_id, base_branch=base_branch)
        fixed_content = apply_patch(repo_folder, patch)
        print(f"[Auto-Fix] Patch applied on branch '{branch_name}'.")
    except Exception as err:
        print(f"[Auto-Fix] Failed to create the branch or apply the patch: {err}")
        save_fix(incident_id, branch_name, patch.get("file_path"), None, False)
        _cleanup_workspace(repo_folder, base_branch)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"apply_patch_failed: {err}"}

    # 7. Tests AFTER the patch
    print(f"[Auto-Fix] Running tests after the patch: '{test_cmd}'...")
    after_passed, _after_out, _ = run_tests(repo_folder, test_cmd)
    print(f"[Auto-Fix] Tests after the patch passed: {after_passed}")
    save_fix(incident_id, branch_name, patch["file_path"], fixed_content, after_passed)

    if not after_passed:
        print("[Auto-Fix] Tests still fail after the patch. Not opening a PR.")
        _cleanup_workspace(repo_folder, base_branch)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": "tests_failed_after_patch"}

    # 8. Auto-merge gate: tests failed BEFORE and pass AFTER
    allow_auto_merge = mode == "auto" and (not before_passed)
    if mode == "auto" and before_passed:
        print("[Auto-Fix] Tests passed both before and after: no test covers this bug.")
        print("           Downgrading to PR-only for human review.")

    # 9. Commit, push, open the PR
    try:
        commit_fix(repo_folder, patch["file_path"], incident_id, patch.get("explanation", ""))
    except Exception as err:
        print(f"[Auto-Fix] Git commit failed: {err}")
        _cleanup_workspace(repo_folder, base_branch)
        update_incident_status(incident_id, "needs_human")
        return {"status": "needs_human", "reason": f"commit_failed: {err}"}

    tests_line = (
        "Tests failed before the patch and pass after it."
        if not before_passed
        else "Tests passed before and after the patch (no test covers this bug directly)."
    )
    body = (
        "## Automated incident remediation\n\n"
        f"- **Incident:** #{incident_id}\n"
        f"- **Root cause:** {diagnosis.get('root_cause')}\n"
        f"- **Fix:** {patch.get('explanation')}\n"
        f"- **Tests:** {tests_line}\n"
    )

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
