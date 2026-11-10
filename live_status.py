"""What the agent is doing right now, in plain words (architecture v3 dashboard).

One place turns the stored state of a push check or an incident into:
  * a headline ("High mode is writing a fix", "Testing the fix in the sandbox", "Pushing the fix to GitHub"),
  * a step tracker (Caught → Reproduce → Write fix → Test fix → Push to GitHub → Merge / Your review),
  * the mode that is working (Low effort / Normal / High / Extra, never model names) and how many tries of it are left.
Pure functions: everything that reaches HTML is escaped here.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

MODE_NAMES = {"groq": "Low effort", "haiku": "Normal", "sonnet": "High", "opus": "Extra"}

# stage -> (headline template, tone, step index that is active, is the agent busy)
INCIDENT_STAGES = {
    "queued": ("Caught · waiting in line", "amber", 1, True),
    "downloading": ("Downloading your code from GitHub", "blue", 1, True),
    "reproducing": ("Reproducing the bug in the sandbox", "blue", 1, True),
    "diagnosing": ("Diagnosing the error", "blue", 1, True),
    "investigating": ("Looking at your live site and code", "blue", 1, True),
    "thinking": ("{mode} mode is writing a fix", "blue", 2, True),
    "testing_fix": ("Testing the fix in the sandbox", "blue", 3, True),
    "waiting_user": ("Waiting for your decision", "amber", 2, True),
    "waiting_retry": ("Paused for a moment, retrying by itself", "amber", None, True),
    "pushing": ("Pushing the fix to GitHub", "blue", 4, True),
    "pr_open": ("Fix pushed · pull request ready for your review", "green", 5, False),
    "merging": ("Fix proven · merging into your branch", "blue", 5, True),
    "merged": ("Fixed · the fixed version is on GitHub", "green", 6, False),
    "github_testing": ("GitHub is testing the fix", "blue", 4, True),
    "github_failed": ("GitHub test failed · sending the error back to the AI", "amber", 2, True),
    "pushed": ("Fixed · pushed to your branch", "green", 6, False),
    "verifying": ("Pushed · check again in 30 seconds, the agent is checking your live site", "blue", 5, True),
    "verified": ("Verified on your live site", "green", 6, False),
    "merged_case": ("Part of another case (same cause)", "muted", None, False),
    "needs_human": ("Needs human review", "red", None, False),
    "resolved": ("Resolved", "green", 6, False),
}
PUSH_STAGES = {
    "queued": ("Waiting in line", "amber", True),
    "downloading": ("Downloading this commit", "blue", True),
    "detecting": ("Finding the projects in your repo", "blue", True),
    "testing": ("Testing in the sandbox", "blue", True),
    "waiting_retry": ("Paused, retrying by itself", "amber", True),
    "waiting_sandbox": ("Waiting for the sandbox", "amber", True),
    "passed": ("Passed", "green", False),
    "failed": ("Broken · agent is fixing it", "red", False),
    "skipped": ("Nothing to test", "muted", False),
    "error": ("Could not check", "red", False),
}


def customer_reason(reason: str, action: str = "") -> str:
    """Translate a router decision (written for admins) into one plain sentence for the customer's dashboard."""
    r = (reason or "").lower()
    if r.startswith("free first"):
        return "Starting with a free attempt"
    if "floor" in r or "third haiku" in r:
        return "Normal gets at least two attempts before a stronger AI is considered"
    if "drop back" in r or "after the drop-back" in r:
        return "Using the stronger AI's findings so the Normal mode can finish the fix"
    if "you chose" in r:
        return "You chose this mode"
    if "lowest expected cost" in r:
        if action in ("sonnet", "opus"):
            return "Moving to a stronger AI: the cheaper modes are unlikely to fix this bug"
        return "The most economical option likely to fix this bug"
    return "Chosen by the agent"


def e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def ago(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def incident_steps(mode: str) -> list[str]:
    if mode == "report":
        return ["Caught", "Diagnose", "Report ready"]
    if mode == "auto":
        return ["Caught", "Reproduce", "Write fix", "Sandbox test", "GitHub test", "Pushed"]
    return ["Caught", "Reproduce", "Write fix", "Test fix", "Push to GitHub", "Your review"]


def incident_view(inc: dict, mode: str, quota: dict | None = None) -> dict:
    """{headline, tone, steps:[(label,state)], active, mode_name, left_text, detail} for one incident."""
    stage = str(inc.get("stage") or "")
    status = str(inc.get("status") or "")
    if not stage:
        stage = {"pr_opened": "pr_open", "needs_human": "needs_human", "resolved": "resolved", "awaiting_choice": "waiting_user",
                 "diagnosed": "resolved" if mode == "report" else "thinking"}.get(status, "diagnosing")
    if status == "resolved" and stage not in ("merged", "resolved", "pushed", "verifying", "verified"):
        stage = "merged" if inc.get("pr_url") else "resolved"
    if status == "needs_human":
        stage = "needs_human"
    headline, tone, active_idx, busy = INCIDENT_STAGES.get(stage, (stage.replace("_", " ").title() or "Working", "muted", 1, True))
    tier = str(inc.get("stage_tier") or "")
    mode_name = MODE_NAMES.get(tier, "")
    headline = headline.replace("{mode}", mode_name or "The AI")
    labels = incident_steps(mode)
    if mode == "report":
        idx = {"merged": 3, "resolved": 3, "needs_human": None}.get(stage, 1)
        if status in ("diagnosed", "resolved"):
            idx, headline, tone, busy = 3, "Diagnosed · report ready", "green", False
    else:
        idx = active_idx
    steps = []
    failed_at = None
    if stage == "needs_human":
        failed_at = _last_reached(inc, labels)
    for i, label in enumerate(labels):
        if failed_at is not None:
            state = "done" if i < failed_at else ("fail" if i == failed_at else "todo")
        elif idx is None:
            state = "done" if i == 0 else "todo"
        elif i < idx:
            state = "done"
        elif i == idx:
            state = "active" if busy else "done"
        else:
            state = "todo"
        if stage == "pr_open" and i == len(labels) - 1 and mode != "auto":
            state = "active"
        steps.append((label, state))
    left = ""
    if quota and tier in quota:
        q = quota[tier]
        left = f"{q['left']} {mode_name} tries left" if tier != "groq" else f"{q['left']} free tries left today"
    return {"stage": stage, "headline": headline, "tone": tone, "steps": steps, "active": busy, "mode_name": mode_name,
            "left_text": left, "detail": str(inc.get("stage_detail") or ""), "when": ago(inc.get("stage_at") or inc.get("last_seen"))}


def _last_reached(inc: dict, labels: list[str]) -> int:
    if inc.get("pr_url"):
        return len(labels) - 1
    if inc.get("root_cause") or inc.get("report"):
        return 2
    return 1


def render_steps(steps) -> str:
    items = "".join(f"<li class='{e(state)}'><span class='dot'></span>{e(label)}</li>" for label, state in steps)
    return f"<ol class='steps'>{items}</ol>"


def push_view(check: dict) -> dict:
    status = str(check.get("status") or "queued")
    stage = str(check.get("stage") or status)
    key = stage if status in ("queued", "running") else status
    headline, tone, busy = PUSH_STAGES.get(key, PUSH_STAGES.get(status, (status.title(), "muted", False)))
    return {"headline": headline, "tone": tone, "active": busy, "detail": str(check.get("stage_detail") or "")}


def stack_chips(stacks_json: str | list) -> str:
    import json
    try:
        stacks = json.loads(stacks_json) if isinstance(stacks_json, str) else (stacks_json or [])
    except ValueError:
        stacks = []
    chips = []
    for s in stacks[:6]:
        ok = s.get("ok")
        cls = "ok" if ok else ("bad" if ok is False else "")
        mark = "✓" if ok else ("✗" if ok is False else "…")
        where = f" at {s.get('phase')}" if ok is False and s.get("phase") else ""
        chips.append(f"<span class='chip {cls}'>{mark} {e(s.get('label'))}{e(where)}</span>")
    return "".join(chips)


def quota_strip(panel: list[dict]) -> str:
    """Four compact meters: Normal / High / Extra this month and Low effort today."""
    order = {"haiku": 0, "sonnet": 1, "opus": 2, "groq": 3}
    cells = []
    for q in sorted(panel, key=lambda r: order.get(r.get("tier"), 9)):
        total = max(1, int(q.get("total") or 0))
        left = max(0, int(q.get("left") if q.get("left") is not None else total - int(q.get("used") or 0)))
        pct = min(100, round(100 * left / total))
        tone = "ok" if pct > 40 else ("warn" if pct > 10 else "bad")
        period = "today" if q.get("daily") else "this month"
        paused = " · paused" if q.get("paused") else ""
        extra = f" (+{q['pack_left']} bought)" if q.get("pack_left") else ""
        cells.append(f"<div class='meter {tone}'><div class='meter-top'><b>{e(q.get('label'))}</b>"
                     f"<span>{left} of {total} left{e(extra)}</span></div><div class='meter-bar'><i style='width:{pct}%'></i></div>"
                     f"<small>{period}{e(paused)}</small></div>")
    return f"<div class='meters'>{''.join(cells)}</div>"


def live_panel(work: dict, modes: dict, quota: dict | None) -> str:
    """The 'Agent right now' block on the dashboard. `modes` maps project_id -> agent mode (report/pr/auto)."""
    rows = []
    open_incidents = [i for i in work["incidents"] if i.get("status") not in ("resolved", "reverted")][:6]
    for inc in open_incidents:
        v = incident_view(inc, inc.get("project_mode") or modes.get(inc.get("project_id"), "pr"), quota)
        source = "push" if inc.get("source") == "push" else "live error"
        sha = f" · commit {e(inc.get('commit_sha', '')[:7])}" if inc.get("commit_sha") else ""
        mode_pill = f"<span class='pill mode'>{e(v['mode_name'])} mode</span>" if v["mode_name"] else ""
        left = f"<span class='pill'>{e(v['left_text'])}</span>" if v["left_text"] else ""
        detail = f"<p class='live-detail'>{e(v['detail'])}</p>" if v["detail"] else ""
        rows.append(f"<article class='live-item' data-active='{1 if v['active'] else 0}'>"
                    f"<div class='live-top'><a href='/projects/{e(inc['project_id'])}/incidents/{e(inc['id'])}'><b>{e(inc.get('project_name'))}</b>"
                    f" · {e(str(inc.get('signature') or '')[:90])}</a>"
                    f"<span class='pill tone-{e(v['tone'])}'>{e(v['headline'])}</span></div>"
                    f"<div class='live-meta'><span class='pill src'>{source}{sha}</span>{mode_pill}{left}<span class='muted'>{e(v['when'])}</span></div>"
                    f"{render_steps(v['steps'])}{detail}</article>")
    checks = []
    for c in work["checks"][:5]:
        v = push_view(c)
        msg = e(str(c.get("commit_message") or "")[:70]) or "<span class='muted'>no message</span>"
        checks.append(f"<tr data-active='{1 if v['active'] else 0}'><td><code>{e(c['sha'][:7])}</code><br><small class='muted'>{e(ago(c.get('created_at')))}</small></td>"
                      f"<td>{e(c.get('project_name'))}<br><small class='muted'>{msg}</small></td>"
                      f"<td><span class='pill tone-{e(v['tone'])}'>{e(v['headline'])}</span><br><small class='muted'>{e(v['detail'][:90])}</small></td>"
                      f"<td>{stack_chips(c.get('stacks_json') or '[]')}</td></tr>")
    if not rows:
        rows.append("<div class='empty'>Nothing broken right now. Push to GitHub and every commit is tested here within minutes.</div>")
    table = ("<div class='table-wrap'><table class='table'><thead><tr><th>Commit</th><th>Project</th><th>Push check</th><th>Stacks</th></tr></thead>"
             f"<tbody>{''.join(checks)}</tbody></table></div>") if checks else "<div class='empty'>No pushes checked yet.</div>"
    return f"<div class='live-list'>{''.join(rows)}</div><h3 class='sub'>Latest pushes</h3>{table}"
