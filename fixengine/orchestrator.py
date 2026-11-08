"""The fix loop (plan section 4 and 7): intake -> triage -> baseline -> [router -> guard -> model -> validate]* -> PR or review.

Everything here is resumable: state is rebuilt from the ledger (fx_attempts) on every pass, so a worker restart,
a warning that waits for the user, or a provider outage never loses progress or double-counts a try.
"""
from __future__ import annotations

import logging
import os
import re
import json
import shutil
import tempfile
import time
from pathlib import Path

import portal_db

from . import adapters as fx_adapters
from . import admin_tools, fingerprint, journeys, notify, prompts, repo_context, review, router, sandbox, store, triage, validator
from . import config as fx_config
from . import git_ops
from .guard import Guard

log = logging.getLogger("fixengine")
PAID = fx_config.PAID_TIERS
AGENT_MARK = "[agent-daemon]"   # in every fix title, so a later push of the agent's own fix is recognised (no fix loops)
OUTAGE_MINUTES = 10
MAX_GITHUB_ROUNDS = int(os.getenv("FIX_GITHUB_ROUNDS", "3") or 3)        # red GitHub runs before a human is asked
GITHUB_WAIT_SECONDS = int(os.getenv("FIX_GITHUB_WAIT_SECONDS", "1200") or 1200)
GITHUB_NO_CHECKS_GRACE = int(os.getenv("FIX_GITHUB_NO_CHECKS_GRACE", "150") or 150)


def direct_push_enabled() -> bool:
    return os.getenv("AGENT_DIRECT_PUSH", "1").strip().lower() not in ("0", "false", "no", "off")


def enabled() -> bool:
    return os.getenv("FIXENGINE_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _stage(incident_id: str, stage: str, detail: str = "", tier: str = "") -> None:
    """Tell the dashboard what the agent is doing right now. Never lets a display problem break a fix."""
    try:
        portal_db.set_incident_stage(incident_id, stage, detail, tier)
    except Exception:
        log.debug("could not record stage %s", stage)


def _failed_test_names(output: str) -> list[str]:
    import re
    return re.findall(r"^FAILED\s+(\S+)", output or "", re.M)[:20]


class Engine:
    def __init__(self, cfg: dict | None = None, *, adapters=None, runner=None, repo_provider=None, commits_provider=None,
                 pr_opener=None, guard: Guard | None = None, gh=None):
        self.cfg = cfg or fx_config.load()
        self.adapters = adapters or fx_adapters.build_adapters(self.cfg)
        self.runner = runner or sandbox.make_runner(self.cfg)
        self.repo_provider = repo_provider or (lambda project: git_ops.repo_snapshot(project, self.cfg))
        self.commits_provider = commits_provider or git_ops.recent_commits_text
        self.pr_opener = pr_opener or git_ops.open_pr
        self.guard = guard or Guard(self.cfg)
        self.gh = gh or git_ops          # the GitHub calls of the proof loop (tests pass a fake)

    # ---- entry points ---------------------------------------------------------------------------------------------
    def handle_incident(self, claimed: dict) -> str:
        incident_id, project_id = claimed["incident_id"], claimed["project_id"]
        project = store.get_project_row(project_id)
        if not project:
            portal_db.fail_diagnosis(incident_id, project_id, "Project no longer exists")
            return "failed"
        user_id = project["user_id"]
        event = claimed.get("first_event") or {}
        existing = store.get_bug_by_incident(incident_id)
        if not existing and not self.guard.intake_allowed(user_id):
            store.park_incident(incident_id, project_id, waiting_for_choice=False, delay_seconds=900)
            return "deferred"
        _stage(incident_id, "downloading", f"{project.get('repo_owner', '')}/{project.get('repo_name', '')} · {project.get('branch', '')}")
        try:
            with self.repo_provider(project) as root:
                return self._work(claimed, project, event, Path(root))
        except Exception as exc:
            safe = str(exc)[:200] if isinstance(exc, (RuntimeError, ValueError)) else exc.__class__.__name__
            log.warning("Fix engine deferred incident %s (%s)", incident_id, safe)
            portal_db.fail_diagnosis(incident_id, project_id, safe)
            return "failed"

    # ---- the loop ----------------------------------------------------------------------------------------------------
    def _work(self, claimed: dict, project: dict, event: dict, root: Path) -> str:
        incident_id, project_id, user_id = claimed["incident_id"], claimed["project_id"], project["user_id"]
        message, traceback_text = str(event.get("message", "")), str(event.get("traceback", ""))
        scan = repo_context.scan_repo(root, max_files=int(self.cfg["sandbox"]["max_repo_files"]))
        files = scan["files"]
        profile = sandbox.detect_profiles(root, files)
        self._prepare_journeys(root, files, profile, claimed)
        from_push = claimed.get("source") == "push"
        bug = store.get_bug_by_incident(incident_id)
        if bug is None:
            fp = fingerprint.fingerprint(message, traceback_text)
            frames = fingerprint.app_frames(traceback_text)
            tri = triage.classify(error_type=fp["error_type"], message=message, traceback=traceback_text,
                                  frame_count=len(frames), files_in_trace=len(fp["files"]),
                                  repo_tokens=repo_context.repo_tokens(files), has_tests=profile.has_tests,
                                  prior_failures=store.count_prior_failures(project_id, fp["hash"]),
                                  kind=str(_evidence_of(claimed).get("kind", "")))
            bug = store.create_bug(project_id=project_id, user_id=user_id, incident_id=incident_id, fingerprint_json=fp,
                                   bug_class=tri["bug_class"], category=tri["category"])
        if bug["baseline_failing"] is None:
            labels = ", ".join(row["label"] for row in sandbox.stack_summary(profile))
            _stage(incident_id, "reproducing", labels)
            base = sandbox.run_profile(self.runner, root, profile)
            if base.system_fault:
                return self._fault_wait(claimed, bug, f"sandbox unavailable: {base.error}", 600)
            baseline = 0 if base.passed else (base.failing if base.failing is not None else -1)
            store.update_bug(bug["id"], baseline_failing=baseline, baseline_output=base.output[:4000])
            bug = store.get_bug(bug["id"])
            if from_push and base.passed:
                # The branch head already passes (the customer pushed a fix, or a newer commit replaced the broken one).
                store.update_bug(bug["id"], status="resolved", closed_at=store.now(), stop_reason="already fixed by a newer push")
                portal_db.resolve_incident(incident_id, project_id, "already fixed by a newer push: no tries used")
                return "resolved"
        store.recover_pending(bug["id"])
        commits = self.commits_provider(project) if self.commits_provider else ""
        repo_tok = repo_context.repo_tokens(files)
        blocked: set[str] = set()
        for _ in range(int(self.cfg["caps"]["per_bug_max_tries"]) + 4):
            bug = store.get_bug(bug["id"])
            attempts = [a for a in store.list_attempts(bug["id"]) if a["result"] != "pending"]
            if bug["user_pinned_tier"] == "__review__":
                return self._finish_review(claimed, project, bug, attempts, event, "you chose human review")
            inp = self._router_input(user_id, bug, attempts, blocked, repo_tok)
            decision = router.decide(inp, self.cfg, router.ProbTable(self.cfg, store.success_stats()))
            store.log_decision(bug["id"], inp.__dict__, decision.options, decision.action, decision.reason)
            if decision.action == "stop":
                return self._finish_review(claimed, project, bug, attempts, event, decision.reason)
            tier = decision.action
            gate = self.guard.check(user_id, tier)
            if not gate.ok:
                if gate.code in ("rate", "cooldown"):
                    return self._fault_wait(claimed, bug, gate.message, 900)
                blocked.add(tier)
                continue
            pause = self._maybe_warn(claimed, project, bug, tier)
            if pause:
                return pause
            import live_status
            _stage(incident_id, "thinking", live_status.customer_reason(decision.reason, decision.action), tier)
            result = self._attempt(claimed, project, bug, tier, gate.pack_try, files, root, profile, message,
                                   traceback_text, commits, attempts)
            self.guard.check_alerts()
            if result[0] == "dry_run":
                log.info("Dry run for bug %s: %s", bug["id"], result[1])
                return "dry_run"
            if result[0] == "pass":
                result[1]["from_push"] = from_push
                if self._direct_push(project, claimed):
                    return self._start_github_proof(claimed, project, bug, result[1])
                return self._open_pr(claimed, project, bug, result[1])
            if result[0] == "fault":
                return self._fault_wait(claimed, bug, result[1], 300)
        bug = store.get_bug(bug["id"])
        return self._finish_review(claimed, project, bug, store.list_attempts(bug["id"]), event, "loop limit reached")

    def _prepare_journeys(self, root: Path, files: dict, profile, claimed: dict) -> None:
        """Static sites: write the browser journeys next to the code (scratch copy only) so the sandbox can prove a UI fix."""
        try:
            if os.getenv("FIX_JOURNEYS_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
                return
            parts = getattr(profile, "parts", None) or [profile]
            if any(getattr(p, "language", "") == "static" for p in parts):
                journeys.prepare(root, files, evidence=_evidence_of(claimed))
        except Exception:
            log.debug("could not prepare browser journeys")

    def _router_input(self, user_id, bug, attempts, blocked, repo_tok) -> router.RouterInput:
        counted = [a for a in attempts if a["result"] != "system_fault"]
        n = lambda t: sum(1 for a in counted if a["tier"] == t)
        last = counted[-1] if counted else None
        left, total = self.guard.quota_left_tuple(user_id)
        left = list(left)
        for i, tier in enumerate(PAID):
            if tier in blocked or not self.adapters[tier].configured():
                left[i] = 0
        since_strong = 0
        for a in reversed(counted):
            if a["tier"] in router.STRONG:
                break
            if a["tier"] == "haiku":
                since_strong += 1
        streak = 0
        for a in reversed(counted):
            if a["tier"] == "haiku" and a["result"] == "unusable":
                streak += 1
            else:
                break
        cur_info = prompts.info_hash(last["error_summary"] if last else "start", (bug["strong_diagnosis"] or "")[:200])
        pinned = bug["user_pinned_tier"] if bug["user_pinned_tier"] in PAID else ""
        return router.RouterInput(
            bug_class=bug["bug_class"], mode=store.get_mode(user_id), free_tries=n("groq"), haiku_tries=n("haiku"),
            sonnet_tries=n("sonnet"), opus_tries=n("opus"), last_tier=last["tier"] if last else "",
            strong_diag=bool(bug["strong_diagnosis"]), last_progress=bool(last and last["progress"]),
            haiku_since_strong=since_strong if bug["strong_diagnosis"] else 0, unusable_streak_haiku=streak,
            spent_inr=float(bug["spent_inr"] or 0), total_tries=len(counted), quota_left=tuple(left), quota_total=total,
            groq_available=self.guard.groq_available(user_id) and self.adapters["groq"].configured() and "groq" not in blocked,
            seen=frozenset((a["tier"], a["info_hash"]) for a in counted), cur_info=cur_info, pinned=pinned, repo_tokens=repo_tok)

    # ---- warnings -------------------------------------------------------------------------------------------------------------
    def _maybe_warn(self, claimed, project, bug, tier) -> str | None:
        if tier == "groq" or store.get_flag(f"bypass:{bug['id']}:{tier}") == "1":
            return None
        user_id = project["user_id"]
        warn, used, total = self.guard.needs_warning(user_id, tier)
        if not warn:
            return None
        mode = store.get_mode(user_id)
        text = notify.user_warning(user_id, tier, used, total)
        if mode == "economy":
            self.guard.mark_warned(user_id, tier)      # economy never escalates, so this is informational only
            return None
        wait = None if mode == "ask" else int(self.cfg["ask_timeout_minutes"])
        store.create_choice(bug["id"], user_id, tier, text, wait)
        self.guard.mark_warned(user_id, tier)
        store.update_bug(bug["id"], status="awaiting_choice")
        store.park_incident(claimed["incident_id"], claimed["project_id"], waiting_for_choice=True)
        _stage(claimed["incident_id"], "waiting_user", text[:250], tier)
        return "awaiting_choice"

    def resume_expired_choices(self) -> int:
        """Auto mode: no answer in time -> continue with the cheapest sensible option (plan 8.3)."""
        count = 0
        for choice in store.expired_choices():
            if store.resolve_choice(choice["id"], "auto_timeout"):
                bug = store.get_bug(choice["bug_id"])
                if bug:
                    cheaper = {"opus": "sonnet", "sonnet": "haiku", "haiku": ""}.get(choice["tier"], "")
                    store.set_flag(f"bypass:{bug['id']}:{choice['tier']}", "1")
                    if cheaper:
                        store.set_flag(f"bypass:{bug['id']}:{cheaper}", "1")
                        store.update_bug(bug["id"], user_pinned_tier=cheaper)
                    store.update_bug(bug["id"], status="open")
                    store.unpark_incident(bug["incident_id"], bug["project_id"])
                    count += 1
        return count

    # ---- one try -----------------------------------------------------------------------------------------------------------------------
    def _attempt(self, claimed, project, bug, tier, pack_try, files, root, profile, message, traceback_text, commits, attempts):
        user_id = project["user_id"]
        adapter = self.adapters[tier]
        if getattr(adapter, "dry_run", False):
            # A dry run stops exactly where the model call would happen: no ledger row, no quota, no cost, no network.
            return ("dry_run", f"would call {tier} via {adapter.describe()}; no model call was made")
        model = adapter.model      # the model id this provider route really uses (OpenRouter ids differ from the direct ones)
        counted = [a for a in attempts if a["result"] != "system_fault"]
        last = counted[-1] if counted else None
        cur_info = prompts.info_hash(last["error_summary"] if last else "start", (bug["strong_diagnosis"] or "")[:200])
        attempt_id = store.add_attempt(bug=bug, tier=tier, model=model, used_strong_diag=bool(bug["strong_diagnosis"]),
                                       info_hash=cur_info, pack_try=pack_try)
        budget = int(self.cfg["tokens"]["groq_prompt_tokens"] if tier == "groq" else self.cfg["tokens"]["max_prompt_tokens"])
        chosen, tests = repo_context.select(files, traceback_text, budget)
        history = [{"tier": a["tier"], "result": a["result"], "error_summary": a["error_summary"]} for a in counted]
        blocks = prompts.build_blocks(
            message=message, traceback=traceback_text, files=chosen, context_files=tests, commits=commits,
            history=history, strong_diagnosis=bug["strong_diagnosis"], has_tests=profile.has_tests,
            sandbox_output=(last["error_summary"] if last and last["result"] == "fail" else ""),
            baseline_output=bug["baseline_output"] if not counted else "",
            previous_patch=(last["patch_json"] if last and last["result"] == "fail" else ""),
            evidence={**_evidence_of(claimed), **(store.gh_state(bug["id"]).get("evidence") or {})})
        try:
            res = adapter.call(prompts.SYSTEM_PROMPT, blocks, 2500 if tier == "groq" else 4000)
            _stage(claimed["incident_id"], "testing_fix", "applying the patch, then install → build → tests → start-up", tier)
        except fx_adapters.AdapterError as exc:
            # The ledger keeps WHO failed, with WHICH model, with what HTTP status, why, and whether retrying can help. Redacted.
            store.finish_attempt(attempt_id, result="system_fault", model=exc.model or model, error_summary=exc.summary())
            self._note_provider_fault(tier, exc, adapter)
            return ("fault", f"{tier} model call failed: {exc.summary()}")
        model = res.model or model          # a provider can fall back to a smaller model: record the one that really answered
        cost = fx_config.estimate_cost_inr(self.cfg, tier, res.tokens_in, res.tokens_out, res.cache_read)
        store.finish_attempt(attempt_id, tokens_in=res.tokens_in, tokens_out=res.tokens_out, cache_read=res.cache_read, cost_inr=cost,
                             model=model)
        store.update_bug(bug["id"], spent_inr=float(bug["spent_inr"] or 0) + cost, tries=int(bug["tries"] or 0) + 1)
        if bug["user_pinned_tier"] == tier:
            store.update_bug(bug["id"], user_pinned_tier="")
        bug = store.get_bug(bug["id"])
        # 1. parse the answer
        try:
            parsed = prompts.parse_response(res.text)
        except prompts.Unusable as exc:
            diag = str(exc)
            if tier in router.STRONG and diag.startswith("cannot determine:"):
                store.update_bug(bug["id"], strong_diagnosis=diag[17:].strip()[:1500])
            store.finish_attempt(attempt_id, result="unusable", error_summary=diag[:300], diagnosis=diag[:500] if "cannot determine" in diag else "")
            return ("fail", diag)
        # 2. policy and application (nothing touches a repo before this passes)
        try:
            validator.check_edits(parsed["edits"], files, self.cfg)
            new_files, diff = validator.apply_edits(parsed["edits"], files)
        except validator.PolicyError as exc:
            store.finish_attempt(attempt_id, result="unusable", error_summary=f"patch rejected: {exc}"[:300],
                                 diagnosis=parsed["diagnosis"][:500], patch_json=prompts_json(parsed["edits"]))
            if tier in router.STRONG:
                store.update_bug(bug["id"], strong_diagnosis=parsed["diagnosis"][:1500])
            return ("fail", str(exc))
        # 3. the sandbox decides
        work = Path(tempfile.mkdtemp(prefix="fx-patched-"))
        try:
            patched = work / "repo"
            shutil.copytree(root, patched, ignore=shutil.ignore_patterns(".git"))
            validator.write_files(patched, new_files)
            sres = sandbox.run_profile(self.runner, patched, profile)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if sres.system_fault:
            store.finish_attempt(attempt_id, result="system_fault", error_summary=f"origin=sandbox kind=sandbox_fault retryable=yes | {sres.error}"[:300],
                                 diagnosis=parsed["diagnosis"][:500])
            return ("fault", f"sandbox unavailable: {sres.error}")
        prev_failing = last["failing_after"] if last and last["failing_after"] is not None else bug["baseline_failing"]
        level = validator.verification_level(baseline_failing=bug["baseline_failing"], baseline_had_tests=profile.has_tests, result=sres,
                                             check_failed_before=claimed.get("source") == "push")
        patch_json = prompts_json(parsed["edits"])
        if sres.passed and level != "failed":
            store.finish_attempt(attempt_id, result="pass", diagnosis=parsed["diagnosis"][:500], patch_json=patch_json,
                                 failing_before=prev_failing, failing_after=sres.failing if sres.failing is not None else 0, progress=1,
                                 error_summary="")
            return ("pass", {"new_files": new_files, "diff": diff, "diagnosis": parsed["diagnosis"], "level": level,
                             "tier": tier, "model": model, "attempt_id": attempt_id})
        after_fp = fingerprint.fingerprint(sres.output[:400], sres.output)
        before_fp = _fp_of(bug, last)
        progressed = fingerprint.made_progress(before_fp, after_fp, prev_failing if (prev_failing or 0) >= 0 else None, sres.failing)
        store.finish_attempt(attempt_id, result="fail", error_summary=sres.output[-600:], diagnosis=parsed["diagnosis"][:500],
                             patch_json=patch_json, failing_before=prev_failing, failing_after=sres.failing,
                             progress=1 if progressed else 0)
        if tier in router.STRONG:
            store.update_bug(bug["id"], strong_diagnosis=parsed["diagnosis"][:1500])
        return ("fail", sres.output[-200:])

    def _note_provider_fault(self, tier, exc, adapter=None) -> None:
        provider = getattr(exc, "provider", "") or getattr(adapter, "provider", "") or ("groq" if tier == "groq" else "anthropic")
        if exc.kind in ("auth", "not_configured", "config"):
            # Persistent problems (bad key, no credit, unknown model, a provider rule that blocks the model): retrying changes nothing.
            store.set_flag(f"pause_{tier}", "1")
            store.log_admin_action("auto_pause", detail={"tier": tier, "why": exc.kind, "provider": provider,
                                                        "model": getattr(exc, "model", ""), "http": getattr(exc, "status", None)})
            notify._to_admins(f"Auto-fix: {tier} paused ({exc.kind})", f"{exc.summary() if hasattr(exc, 'summary') else exc}. "
                              "Fix the key or the model setting, then resume it in /admin.")
        elif exc.kind in ("outage", "timeout", "rate_limit"):
            key = f"outage_{provider}_streak"
            streak = int(store.get_flag(key, "0") or 0) + 1
            store.set_flag(key, str(streak))
            if streak >= 3:
                from datetime import datetime, timedelta, timezone
                until = (datetime.now(timezone.utc) + timedelta(minutes=OUTAGE_MINUTES)).isoformat(timespec="microseconds")
                store.set_flag(f"outage_{provider}_until", until)
                store.set_flag(key, "0")
                store.log_admin_action("provider_outage", detail={"provider": provider, "until": until})

    # ---- outcomes --------------------------------------------------------------------------------------------------------------------------
    def _fault_wait(self, claimed, bug, reason, delay) -> str:
        _stage(claimed["incident_id"], "waiting_retry", f"{reason[:180]} · retrying in about {max(1, delay // 60)} min")
        store.update_bug(bug["id"], status="open")
        store.park_incident(claimed["incident_id"], claimed["project_id"], waiting_for_choice=False, delay_seconds=delay)
        log.info("Bug %s waiting %ss: %s", bug["id"], delay, reason)
        return "waiting"


    # ---- v3: sandbox proof -> GitHub proof -> direct push (no pull request) ---------------------------------------------------
    def _direct_push(self, project, claimed) -> bool:
        mode = project.get("mode") or claimed.get("mode")
        return mode == "auto" and direct_push_enabled()

    def _start_github_proof(self, claimed, project, bug, win: dict) -> str:
        incident_id = claimed["incident_id"]
        state = store.gh_state(bug["id"])
        round_no = int(state.get("round", 0)) + 1
        short = " ".join(str(win["diagnosis"]).split())[:60].rstrip(" .")
        title = f"fix: {short or 'incident ' + incident_id[:8]} {AGENT_MARK}"
        _stage(incident_id, "pushing", f"sending the fix to a test branch on GitHub (round {round_no} of {MAX_GITHUB_ROUNDS})", win["tier"])
        try:
            pushed = self.gh.push_fix_branch(project, bug_id=bug["id"], new_files=win["new_files"], title=title)
        except Exception as exc:
            from monitoring_installer import PublicRepoError
            if isinstance(exc, PublicRepoError):
                store.update_bug(bug["id"], status="open")
                portal_db.park_incident_for_gate(incident_id, claimed["project_id"])
                return "waiting_private"
            return self._fault_wait(claimed, bug, f"could not push the test branch ({exc.__class__.__name__})", 300)
        state.update({"round": round_no, "branch": pushed["branch"], "head_sha": pushed["head_sha"], "base_sha": pushed["base_sha"],
                      "pushed_at": time.time(), "attempt_id": win["attempt_id"], "tier": win["tier"], "model": win["model"],
                      "level": win["level"], "diagnosis": str(win["diagnosis"])[:1500], "diff": str(win["diff"])[:40000],
                      "title": title, "files": sorted(win["new_files"])[:20]})
        if win.get("verified_text"):
            state["verified_text"] = str(win["verified_text"])[:600]
        if win.get("evidence"):
            state["evidence"] = win["evidence"]
        store.save_gh_state(bug["id"], state)
        result = {"category": "code_bug", "confidence": "high" if win["level"] in validator.PROVEN_LEVELS else "medium",
                  "root_cause": win["diagnosis"], "report": f"Fixed by the {win['tier']} model. {validator.VERIFY_TEXT.get(win['level'], '')}"}
        portal_db.complete_diagnosis(incident_id, claimed["project_id"], result)
        store.update_bug(bug["id"], status="github_testing")
        _stage(incident_id, "github_testing", f"GitHub is running your tests on the fix (round {round_no} of {MAX_GITHUB_ROUNDS})", win["tier"])
        return "github_testing"

    def start_proof_for_files(self, claimed, project, *, new_files, diff, diagnosis, level, verified_text="", evidence=None) -> str:
        """A ready-made fix (the deterministic retired-model fix) enters the same sandbox-then-GitHub proof loop as an AI fix."""
        bug = store.get_bug_by_incident(claimed["incident_id"])
        if bug is None:
            bug = store.create_bug(project_id=claimed["project_id"], user_id=project["user_id"], incident_id=claimed["incident_id"],
                                   fingerprint_json={"hash": "model-fix", "error_type": "retired_model", "files": []},
                                   bug_class="easy", category="retired_model")
        win = {"new_files": new_files, "diff": diff, "diagnosis": diagnosis, "level": level, "tier": "free", "model": "",
               "attempt_id": "", "verified_text": verified_text, "evidence": evidence or {}}
        return self._start_github_proof(claimed, project, bug, win)

    def process_proofs(self) -> int:
        """Called by the worker every few seconds: look at every fix that is waiting for GitHub's tests."""
        count = 0
        for bug in store.bugs_by_status("github_testing"):
            try:
                self._check_proof(bug)
            except Exception as exc:
                log.warning("proof check for bug %s deferred (%s)", bug["id"], exc.__class__.__name__)
            count += 1
        return count

    def _check_proof(self, bug) -> None:
        link = store.incident_for_bug(bug["id"])
        state = store.gh_state(bug["id"])
        if not link or not state.get("head_sha"):
            return
        project = store.get_project_row(link["project_id"])
        if not project:
            return
        claimed = {"incident_id": link["incident_id"], "project_id": link["project_id"]}
        age = time.time() - float(state.get("pushed_at", 0) or 0)
        status = self.gh.checks_state(project, state["head_sha"])
        if status == "pending":
            if age > GITHUB_WAIT_SECONDS:
                self._needs_review(claimed, project, bug, state, "GitHub did not finish the tests in time.")
            return
        if status == "no_checks":
            if age < GITHUB_NO_CHECKS_GRACE:
                return
            if state.get("level") in validator.PROVEN_LEVELS:
                state["no_github_tests"] = True
                store.save_gh_state(bug["id"], state)
                self._push_to_branch(claimed, project, bug, state)
            else:
                self._needs_review(claimed, project, bug, state, "No GitHub test ran and the sandbox could not prove the fix by itself.")
            return
        if status == "success":
            self._push_to_branch(claimed, project, bug, state)
            return
        if status == "failed":
            self._github_red(claimed, project, bug, state)

    def _github_red(self, claimed, project, bug, state) -> None:
        round_no = int(state.get("round", 1))
        try:
            text = self.gh.failed_check_log(project, state["head_sha"])
        except Exception:
            text = "GitHub reported a failed check but its log could not be read."
        summary = f"GitHub tests failed after your patch (round {round_no} of {MAX_GITHUB_ROUNDS}).\n{text}"
        if state.get("attempt_id"):
            try:
                store.finish_attempt(state["attempt_id"], result="fail", error_summary=summary[:6000], progress=0)
            except Exception:
                log.debug("could not mark the attempt failed")
        state["last_log"] = text[:6000]
        store.save_gh_state(bug["id"], state)
        if round_no >= MAX_GITHUB_ROUNDS:
            self._needs_review(claimed, project, bug, state, f"GitHub tests still failed after {round_no} tries.")
            return
        _stage(claimed["incident_id"], "github_failed",
               f"GitHub test failed (round {round_no} of {MAX_GITHUB_ROUNDS}) · sending what failed back to the AI model", state.get("tier", ""))
        store.update_bug(bug["id"], status="open")
        store.unpark_incident(claimed["incident_id"], claimed["project_id"])

    def _push_to_branch(self, claimed, project, bug, state) -> None:
        incident_id = claimed["incident_id"]
        _stage(incident_id, "pushing", "GitHub tests passed · pushing the fix to your branch", state.get("tier", ""))
        outcome = self.gh.fast_forward_base(project, state["head_sha"], state["base_sha"])
        level = state.get("level", "")
        verified = state.get("verified_text") or validator.VERIFY_TEXT.get(level, "")
        if state.get("no_github_tests"):
            verified += " No GitHub test ran for this fix (your workflow does not run on branches), so the sandbox was the proof."
        if outcome == "ok":
            self.gh.delete_branch(project, state["branch"])
            store.record_direct_push(incident_id, claimed["project_id"], branch=state["branch"], file_path=", ".join(state.get("files", [])),
                                     diff=state.get("diff", ""), head_sha=state["head_sha"], verification_text=verified)
            _stage(incident_id, "pushed", f"pushed to {project.get('branch', 'your branch')} after the sandbox and GitHub tests passed", state.get("tier", ""))
            store.update_bug(bug["id"], status="resolved", closed_at=store.now(), stop_reason="")
            notify.user_fix_pushed(project["user_id"], project["name"], project.get("branch", "main"), verified)
        elif outcome == "moved":
            moved = int(state.get("moved", 0)) + 1
            state["moved"] = moved
            store.save_gh_state(bug["id"], state)
            if moved >= 2:
                self._needs_review(claimed, project, bug, state, "Your branch kept changing while the fix was being tested.")
                return
            _stage(incident_id, "queued", "Your branch changed while the fix was tested · re-checking on the newest code", state.get("tier", ""))
            store.update_bug(bug["id"], status="open")
            store.unpark_incident(incident_id, claimed["project_id"])
        else:     # protected branch: a pull request is the only way in. It was proven, so it may merge itself.
            self._open_branch_pr(claimed, project, bug, state, review=False,
                                 reason="Your branch is protected, so the proven fix was sent as a pull request.")

    def _needs_review(self, claimed, project, bug, state, reason: str) -> None:
        self._open_branch_pr(claimed, project, bug, state, review=True, reason=reason)

    def _open_branch_pr(self, claimed, project, bug, state, *, review: bool, reason: str) -> None:
        incident_id = claimed["incident_id"]
        last = (state.get("last_log") or "")[:2500]
        body = ("## Agent Daemon fix" + (" (needs human review)" if review else "") + "\n\n"
                f"- Incident: {incident_id}\n- Diagnosis: {state.get('diagnosis', '')[:1200]}\n- {reason}\n\n"
                + (f"### Last GitHub error\n```\n{last}\n```\n\n" if review and last else "")
                + "Nothing was pushed to your main branch.")
        try:
            pr = self.gh.open_pr_for_branch(project, branch=state["branch"], title=state.get("title", "fix " + AGENT_MARK), body=body)
            if not pr.get("url") or not pr.get("number"):
                raise RuntimeError("no pull request link")
        except Exception as exc:
            store.update_bug(bug["id"], status="needs_human", stop_reason=reason[:300], closed_at=store.now())
            _stage(incident_id, "needs_human", (reason + " The pull request could not be opened.")[:250])
            portal_db.mark_remediation_needs_human(incident_id, claimed["project_id"], reason)
            log.warning("could not open the review PR (%s)", exc.__class__.__name__)
            return
        store.record_pr(incident_id, claimed["project_id"], branch=pr["branch"], file_path=", ".join(state.get("files", [])),
                        diff=state.get("diff", ""), pr_url=pr["url"], pr_number=int(pr["number"]),
                        verification_text=reason)
        if review:
            store.block_automerge(incident_id)
            store.update_bug(bug["id"], status="needs_human", stop_reason=reason[:300], pr_url=pr["url"], closed_at=store.now())
            _stage(incident_id, "needs_human", f"Needs human review · {reason} A pull request is ready.", state.get("tier", ""))
            notify.user_needs_review(project["user_id"], project["name"], pr["url"], reason)
        else:
            store.update_bug(bug["id"], status="pr_opened", pr_url=pr["url"], closed_at=store.now())
            _stage(incident_id, "merging", "Your branch is protected · pull request opened, merging when GitHub allows", state.get("tier", ""))

    def _open_pr(self, claimed, project, bug, win: dict) -> str:
        attempts = store.list_attempts(bug["id"])
        spent = sum(float(a["cost_inr"] or 0) for a in attempts)
        level = win["level"]
        body = ("## Agent Daemon fix\n\n"
                f"- Incident: {claimed['incident_id']}\n- Diagnosis: {win['diagnosis'][:1200]}\n"
                f"- Model: {fx_config.USER_MODE_NAMES.get(win['tier'], win['tier'])} ({win['model']}), after {len(attempts)} tries\n\n"
                f"### Verification\n{validator.VERIFY_TEXT.get(level, '')}\n\n"
                "Nothing was pushed to your main branch. Review the diff before merging.")
        short = " ".join(str(win["diagnosis"]).split())[:60].rstrip(" .")
        title = f"fix: {short or 'incident ' + claimed['incident_id'][:8]} {AGENT_MARK}"
        _stage(claimed["incident_id"], "pushing", f"new branch agent-daemon/fix-… and a pull request into {project.get('branch', '')}", win["tier"])
        try:
            pr = self.pr_opener(project, bug_id=bug["id"], incident_id=claimed["incident_id"], new_files=win["new_files"],
                                diff=win["diff"], title=title, body=body)
            if not pr.get("url") or not pr.get("number"):
                raise RuntimeError("GitHub did not return a pull request link")
        except Exception as exc:
            from monitoring_installer import PublicRepoError
            if isinstance(exc, PublicRepoError):
                # The repository is public: keep the proven fix, push nothing, continue once it is private again.
                store.update_bug(bug["id"], status="open")
                portal_db.park_incident_for_gate(claimed["incident_id"], claimed["project_id"])
                return "waiting_private"
            return self._fault_wait(claimed, bug, f"could not open the PR ({exc.__class__.__name__})", 300)
        result = {"category": "code_bug", "confidence": "high" if level in validator.PROVEN_LEVELS else "medium",
                  "root_cause": win["diagnosis"], "report": f"Fixed by the {win['tier']} model. {validator.VERIFY_TEXT.get(level, '')}"}
        portal_db.complete_diagnosis(claimed["incident_id"], claimed["project_id"], result)
        store.record_pr(claimed["incident_id"], claimed["project_id"], branch=pr["branch"], file_path=pr["path"], diff=pr["diff"],
                        pr_url=pr["url"], pr_number=int(pr["number"]), verification_text=validator.VERIFY_TEXT.get(level, ""))
        if level not in validator.PROVEN_LEVELS:
            store.block_automerge(claimed["incident_id"])
        elif pr.get("head_sha"):
            # The sandbox proved the fix: say so on the fix commit, so GitHub (and Auto mode) see a passing check.
            try:
                import push_watch
                push_watch.set_commit_status({**project, "branch": pr["head_sha"], "project_id": claimed["project_id"]},
                                             pr["head_sha"], "success", validator.VERIFY_TEXT.get(level, "")[:139])
            except Exception:
                log.debug("could not set the fix commit status")
        mode = project.get("mode") or claimed.get("mode")
        _stage(claimed["incident_id"], "merging" if (mode == "auto" and level in validator.PROVEN_LEVELS) else "pr_open",
               "waiting for GitHub checks, then merging automatically" if mode == "auto" and level in validator.PROVEN_LEVELS
               else "review and merge the pull request on GitHub", win["tier"])
        store.update_bug(bug["id"], status="pr_opened", pr_url=pr["url"], closed_at=store.now(), stop_reason="")
        notify.user_pr_opened(project["user_id"], project["name"], pr["url"], validator.VERIFY_TEXT.get(level, ""))
        return "pr_opened"

    def _finish_review(self, claimed, project, bug, attempts, event, reason) -> str:
        if not any(self.adapters[t].configured() for t in fx_config.TIERS):
            reason = "No AI model is configured yet (missing API keys). " + reason
        decisions = store.list_decisions(bug["id"])
        report = review.build_report(bug, attempts, decisions, project_name=project["name"], incident=event, stop_reason=reason)
        store.update_bug(bug["id"], status="needs_human", stop_reason=reason[:300], review_report=report, closed_at=store.now())
        _stage(claimed["incident_id"], "needs_human", reason[:250])
        result = {"category": bug["category"] or "unknown", "confidence": "low",
                  "root_cause": (bug["strong_diagnosis"] or "")[:3000], "report": report}
        portal_db.complete_diagnosis(claimed["incident_id"], claimed["project_id"], result)
        portal_db.mark_remediation_needs_human(claimed["incident_id"], claimed["project_id"], reason)
        notify.user_review_ready(project["user_id"], project["name"], claimed["incident_id"], reason)
        user_id = project["user_id"]
        for tier in ("sonnet", "opus"):
            if attempts and self.guard.quota(user_id, tier)["left"] == 0 and "used up" in reason:
                notify.user_exhausted(user_id, tier)
                admin_tools.request_more_tries(user_id, tier, self.guard)
                break
        return "needs_human"


EVIDENCE_PREFIX = "[evidence] "


def infer_kind(message: str) -> str:
    low = (message or "").lower()
    if low.startswith("[user report]"):
        return "user_report"
    if "dead click" in low:
        return "dead_click"
    if "journey" in low and "failed" in low:
        return "journey_failed"
    if "site is not answering" in low or "site down" in low:
        return "site_down"
    if re.search(r"failed with http|failed request|network error|cors", low):
        return "failed_request"
    return ""


def _evidence_of(claimed: dict) -> dict:
    """Browser, probe and owner-report facts. Monitors put one line '[evidence] {json}' at the top of the event's traceback field
    (no schema change needed); older events get a best-effort kind from their message. Shown to the model as untrusted data."""
    event = claimed.get("first_event") or {}
    ev: dict = {}
    for line in str(event.get("traceback") or "").splitlines()[:6]:
        if line.startswith(EVIDENCE_PREFIX):
            try:
                data = json.loads(line[len(EVIDENCE_PREFIX):])
                if isinstance(data, dict):
                    ev = {str(k)[:40]: v for k, v in list(data.items())[:20]}
            except ValueError:
                pass
            break
    if not ev.get("kind"):
        kind = infer_kind(str(event.get("message") or ""))
        if kind:
            ev["kind"] = kind
    return ev


def prompts_json(edits) -> str:
    import json
    return json.dumps(edits)[:20000]


def _fp_of(bug, last) -> dict:
    import json
    try:
        base = json.loads(bug["fingerprint_json"] or "{}")
    except ValueError:
        base = {}
    if last and last.get("error_summary"):
        return fingerprint.fingerprint(last["error_summary"][:400], last["error_summary"])
    return base
