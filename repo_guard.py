"""Public-repository safety gate.

Anything Agent Daemon commits into a customer's repository (monitor files with the project's connection details, fixes,
merges) is only written while GitHub says the repository is PRIVATE. Every code path that writes to a repository calls
ensure_private() first. When a repository is (or becomes) public:
  * nothing is committed,
  * the project goes to the "waiting for private repo" state (visible on the dashboard and the project page),
  * the owner is emailed (at most once a day) with simple step-by-step instructions,
  * work that needs a commit is parked and continues by itself once the repository is private again.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import portal_db
from monitoring_installer import GitHubInstallError, PublicRepoError, is_private, validate_repository_access

LOG = logging.getLogger("repo_guard")
NOTIFY_EVERY_HOURS = 24


def _token(project: dict) -> str:
    from portal_remediation import _token as decrypt
    return decrypt(str(project.get("github_token_ciphertext") or ""))


def repo_info(project: dict, token: str | None = None) -> dict:
    """GitHub's repository record (raises GitHubInstallError when GitHub cannot be asked)."""
    token = token if token is not None else _token(project)
    return validate_repository_access(owner=str(project.get("repo_owner", "")), repo=str(project.get("repo_name", "")), token=token)


def ensure_private(project: dict, token: str | None = None, *, action: str = "commit") -> dict:
    """For DIRECT writes (a push to the owner's branch, a test branch, an undo, monitor files with a key): return GitHub's repo
    record when the repository is private. A public repository is switched to pull-request mode (switch_to_public_pr) and
    PublicRepoError is raised, so the caller opens a pull request instead. A GitHub/API failure raises GitHubInstallError."""
    info = repo_info(project, token)
    project_id = str(project.get("id") or project.get("project_id") or "")
    if is_private(info):
        if project_id and project.get("gate_state") == portal_db.GATE_PUBLIC:
            restore_after_private(project_id)                  # private again: Auto mode (if it was on) comes back
            portal_db.set_gate_state(project_id, portal_db.GATE_ACTIVE)
        elif project_id and project.get("gate_state") == portal_db.GATE_WAITING:
            portal_db.set_gate_state(project_id, portal_db.GATE_ACTIVE)
        elif project_id:
            portal_db.set_gate_state(project_id, project.get("gate_state") or portal_db.GATE_ACTIVE)
        return info
    if project_id:
        switch_to_public_pr(project, action=action)
    raise PublicRepoError("The repository is public, so Agent Daemon did not push to it; fixes come as pull requests instead.")


def allow_pull_request(project: dict, token: str | None = None, *, action: str = "fix pull request") -> dict:
    """Pull requests are fine on a public repository (the owner merges them). A public repository is switched to pull-request
    mode on the way, so the owner is told; nothing is raised."""
    info = repo_info(project, token)
    project_id = str(project.get("id") or project.get("project_id") or "")
    if project_id and not is_private(info):
        switch_to_public_pr(project, action=action)
    return info


PUBLIC_REASON = ("Your repository is public, so Agent Daemon works in Pull request mode: every fix comes as a pull request that you "
                 "merge, and nothing is pushed straight to your branch. Anyone can see and copy a public repository, so automatic pushes "
                 "and the live error monitor (its connection key would be visible to everyone) are switched off. Push checks keep "
                 "working. Make the repository private to switch Auto mode and the live monitor back on.")


def switch_to_public_pr(project: dict, *, action: str = "commit") -> None:
    """Public repository: pull requests only. Auto becomes Pull request (remembered, restored when it is private again), the live
    monitor is switched off, cases that waited for "make it private" continue as pull requests, and the owner is told why once a day."""
    project_id = str(project.get("id") or project.get("project_id") or "")
    fresh = portal_db.get_project_any(project_id) or project
    from fixengine import store as fx_store
    mode, watch = fresh.get("mode") or "pr", fresh.get("watch_mode") or "both"
    if mode == "auto" or watch in ("both", "runtime"):
        if not fx_store.get_flag(f"public_prev:{project_id}"):
            fx_store.set_flag(f"public_prev:{project_id}", f"{mode}|{watch}")
        portal_db.set_project_mode_and_watch(project_id, mode="pr" if mode == "auto" else None,
                                             watch_mode="push" if watch in ("both", "runtime") else None)
    try:
        portal_db.unpark_gate_incidents(project_id)
    except Exception:
        LOG.debug("no parked cases for %s", project_id)
    last = str(fresh.get("gate_notified_at") or "")
    due = True
    if last:
        try:
            stamp = datetime.fromisoformat(last)
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            due = datetime.now(timezone.utc) - stamp > timedelta(hours=NOTIFY_EVERY_HOURS)
        except ValueError:
            due = True
    was = fresh.get("gate_state")
    portal_db.set_gate_state(project_id, portal_db.GATE_PUBLIC, notified=due)
    portal_db.audit(project_id, "repo_public_pr_mode", {"action": action, "was": was})
    if due:
        _notify_public_pr(fresh)


def restore_after_private(project_id: str) -> None:
    """The repository is private again: put back the mode and watch setting the owner had before."""
    from fixengine import store as fx_store
    prev = fx_store.get_flag(f"public_prev:{project_id}", "")
    if prev:
        mode, _, watch = prev.partition("|")
        portal_db.set_project_mode_and_watch(project_id, mode=mode or None, watch_mode=watch or None)
        fx_store.set_flag(f"public_prev:{project_id}", "")


def _notify_public_pr(project: dict) -> None:
    try:
        import notifications
        email = portal_db.get_user_email(project["user_id"])
        if not email:
            return
        base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
        repo = f"{project.get('repo_owner')}/{project.get('repo_name')}"
        notifications.notify_customer(
            email, f"{repo} is public: fixes now come as pull requests",
            f"{PUBLIC_REASON}\n\nNothing else changes: the agent still tests your pushes and fixes problems, you merge its pull "
            "requests on GitHub.\n\nTo switch Auto mode back on (2 minutes):\n"
            f"1. Open https://github.com/{repo}/settings (sign in if asked).\n"
            "2. Scroll all the way down to the red 'Danger Zone'.\n"
            "3. Click 'Change visibility', then 'Make private'.\n"
            f"4. Come back to {base}/projects/{project.get('id')} and press \"I made it private\".", "repo_public")
    except Exception:
        LOG.exception("Could not email the owner about a public repository")


def flag_public(project: dict, *, action: str = "commit") -> None:
    """Put the project into the waiting state and tell the owner (rate limited)."""
    project_id = str(project.get("id") or project.get("project_id") or "")
    fresh = portal_db.get_project_any(project_id) or project
    was_active = fresh.get("gate_state") != portal_db.GATE_WAITING
    last = str(fresh.get("gate_notified_at") or "")
    due = True
    if last:
        try:
            stamp = datetime.fromisoformat(last)
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            due = datetime.now(timezone.utc) - stamp > timedelta(hours=NOTIFY_EVERY_HOURS)
        except ValueError:
            due = True
    portal_db.set_gate_state(project_id, portal_db.GATE_WAITING, notified=due)
    portal_db.audit(project_id, "repo_public_paused", {"action": action, "was_active": was_active})
    if due:
        _notify(fresh, was_active)


def _notify(project: dict, was_active: bool) -> None:
    try:
        import notifications
        email = portal_db.get_user_email(project["user_id"])
        if not email:
            return
        base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
        repo = f"{project.get('repo_owner')}/{project.get('repo_name')}"
        what = ("Your repository just became public, so Agent Daemon paused everything that writes to it "
                "(monitor updates and fixes) to keep your connection details safe."
                if was_active else
                "Your monitoring agent is ready to be installed into your code, but your repository is public.")
        notifications.notify_customer(
            email, f"Action needed: make {repo} private",
            f"{what}\n\nAnyone on the internet can see a public repository, including the connection details our monitor needs.\n\n"
            "How to make it private (2 minutes):\n"
            f"1. Open https://github.com/{repo}/settings (sign in if asked).\n"
            "2. Scroll all the way down to the red 'Danger Zone'.\n"
            "3. Click 'Change visibility', then choose 'Make private' / 'Change to private'.\n"
            "4. Confirm (GitHub may ask you to type the repository name or your password).\n"
            f"5. Come back to {base}/projects/{project.get('id')} and press \"I've made it private, install now\".\n\n"
            "Nothing was installed or changed in your repository.", "repo_public")
    except Exception:
        LOG.exception("Could not email the owner about a public repository")


def sweep_visibility(limit: int = 20, min_age_seconds: int = 1800) -> int:
    """Worker task: re-check installed projects every ~30 minutes. A repository that became public is paused and its
    project key is rotated (the old key was in the now-public code, so it is revoked)."""
    flagged = 0
    for project in portal_db.projects_for_visibility_check(min_age_seconds)[:limit]:
        try:
            ensure_private(project, action="periodic check")
        except PublicRepoError:
            flagged += 1
            if project.get("gate_state") not in (portal_db.GATE_PUBLIC, portal_db.GATE_WAITING):
                _revoke_exposed_key(project)                 # it just became public: the key in the code is now visible
        except Exception as exc:          # GitHub down, token revoked: try again next round, never crash the worker
            LOG.info("Visibility check skipped for %s: %s", project.get("id"), exc.__class__.__name__)
            portal_db.set_gate_state(project["id"], project.get("gate_state") or "")
    return flagged


def _revoke_exposed_key(project: dict) -> None:
    """The monitor's key was committed while the repo was private; now that the code is public, revoke it."""
    if not (project.get("monitor_installed_at") or project.get("install_pr_url")):
        return
    import hashlib
    import secrets
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
        new_key = "adi_" + secrets.token_urlsafe(32)
        cipher = Fernet(key.encode("ascii")).encrypt(new_key.encode()).decode("ascii") if key else ""
        portal_db.rotate_project_ingest_key(project["id"], project["user_id"], hashlib.sha256(new_key.encode()).hexdigest(), cipher)
        portal_db.audit(project["id"], "ingest_key_revoked_repo_public")
    except Exception:
        LOG.exception("Could not rotate the exposed key of %s", project.get("id"))


__all__ = ["ensure_private", "allow_pull_request", "switch_to_public_pr", "restore_after_private", "flag_public", "repo_info",
           "sweep_visibility", "PublicRepoError", "GitHubInstallError", "PUBLIC_REASON"]
