"""HTML for the usage page (customers) and the budget page (admins). Pure functions: no I/O, everything escaped.

Plain words only (plan 8): modes are Low effort / Normal / High / Extra, never model names, and costs are never
shown to customers as rupees-per-try. Admins see rupees.
"""
from __future__ import annotations

import html

from . import config as fx_config

E = lambda v: html.escape(str(v if v is not None else ""), quote=True)

MODE_HELP = {
    "auto": ("Auto", "The agent picks the cheapest mode that works and escalates when it must. It asks you at the plan's warning points, "
                     "and continues with the cheapest sensible option if you do not answer in 30 minutes."),
    "ask": ("Ask me", "The agent pauses and asks you at every warning point, and waits as long as it takes."),
    "economy": ("Economy", "The agent stays in Low effort and Normal and never uses High or Extra. Hard bugs go to human review."),
}
STATUS_TEXT = {
    "open": "Working on it", "awaiting_choice": "Waiting for your decision", "pr_opened": "Fix proposed",
    "needs_human": "Needs a human", "failed": "Stopped", "resolved": "Already fixed (no tries used)",
}


def _bar(used: int, total: int) -> str:
    pct = 0 if total <= 0 else min(100, round(100 * used / total))
    tone = "#8ce4c0" if pct < 60 else ("#f0cf8a" if pct < 90 else "#ff8a7a")
    return (f"<div style='height:8px;border-radius:6px;background:#ffffff14;overflow:hidden;margin:8px 0'>"
            f"<div style='width:{pct}%;height:100%;background:{tone}'></div></div>")


def _tier_card(q: dict) -> str:
    label = E(q["label"])
    if q.get("daily"):
        return (f"<article class='card'><h3>{label}</h3><p class='muted'>Free, with a fair-use limit. Quality is basic.</p>"
                f"{_bar(q['used'], q['total'])}<p>{E(q['used'])} of {E(q['total'])} used today</p></article>")
    pack = f"<p class='muted'>Plus {E(q['pack_left'])} extra tries you bought.</p>" if q.get("pack_total") else ""
    paused = "<span class='pill amber'>Busy right now</span>" if q.get("paused") else ""
    blurb = {"haiku": "Everyday fixes. This is where most bugs get solved.",
             "sonnet": "Deeper analysis for bugs that Normal could not solve.",
             "opus": "Maximum effort for the hardest bugs. Used rarely."}[q["tier"]]
    return (f"<article class='card'><div class='row'><h3>{label}</h3>{paused}</div><p class='muted'>{blurb}</p>"
            f"{_bar(q['used'], q['total'])}<p>{E(q['used'])} of {E(q['total'])} tries used this month · "
            f"<strong>{E(q['left'])} left</strong></p>{pack}</article>")


def _choice_card(c: dict, csrf: str) -> str:
    def btn(value, text, primary=False):
        return (f"<form method='post' action='/usage/choice' style='display:inline'>"
                f"<input type='hidden' name='csrf' value='{E(csrf)}'><input type='hidden' name='choice_id' value='{E(c['id'])}'>"
                f"<input type='hidden' name='choice' value='{E(value)}'>"
                f"<button class='button{' primary' if primary else ''}' type='submit'>{E(text)}</button></form> ")
    mode = fx_config.USER_MODE_NAMES.get(c["tier"], c["tier"])
    return (f"<article class='card'><div class='eyebrow'>Your decision</div><h3>{E(mode)} mode</h3><p>{E(c['message'])}</p>"
            f"<p>{btn('auto', 'Let the agent choose', True)}{btn('lower', 'Use a lower mode')}"
            f"{btn('higher', 'Use a higher mode')}{btn('review', 'Send to human review')}</p></article>")


def usage_page(view: dict, csrf: str) -> str:
    cards = "".join(_tier_card(q) for q in view["panel"])
    choices = "".join(_choice_card(c, csrf) for c in view["choices"])
    mode = view["mode"]
    radios = "".join(
        f"<label style='display:block;margin:10px 0'><input type='radio' name='mode' value='{k}'{' checked' if k == mode else ''}> "
        f"<strong>{E(v[0])}</strong><br><span class='muted'>{E(v[1])}</span></label>" for k, v in MODE_HELP.items())
    rows = []
    for b in view["bugs"]:
        action = ""
        if b["status"] == "pr_opened" and b["pr_url"]:
            action = f"<a href='{E(b['pr_url'])}' target='_blank' rel='noopener'>Open fix</a>"
        elif b["status"] == "needs_human":
            action = (f"<details><summary>Review report</summary><pre style='white-space:pre-wrap;overflow:auto'>{E(b['review_report'])}</pre></details>"
                      f"<form method='post' action='/usage/retry'><input type='hidden' name='csrf' value='{E(csrf)}'>"
                      f"<input type='hidden' name='bug_id' value='{E(b['id'])}'><button class='button' type='submit'>Try again</button></form>")
        rows.append(f"<tr><td>{E(b['project_name'])}</td><td>{E(STATUS_TEXT.get(b['status'], b['status']))}</td>"
                    f"<td>{E(b['tries'])}</td><td>{action}</td></tr>")
    table = ("<div class='table-wrap'><table class='table'><thead><tr><th>Project</th><th>Status</th><th>Tries</th><th></th></tr></thead>"
             f"<tbody>{''.join(rows)}</tbody></table></div>") if rows else "<div class='empty'>No bugs worked on yet.</div>"

    def more(kind, text):
        return (f"<form method='post' action='/usage/more' style='display:inline'><input type='hidden' name='csrf' value='{E(csrf)}'>"
                f"<input type='hidden' name='kind' value='{kind}'><button class='button' type='submit'>{E(text)}</button></form> ")
    return (f"<section class='section'><p><a href='/dashboard'>← Projects</a></p><div class='eyebrow'>Fix usage</div>"
            f"<h1>Your tries this month</h1><p class='muted'>Resets on the 1st. A try is one attempt by the agent to fix a bug; "
            f"push checks are free and never use a try. Tries buy attempts, not a guaranteed fix. "
            f"<a href='/how-it-works#router'>How the agent picks a mode</a></p>{choices}<div class='grid'>{cards}</div>"
            f"<h2>How should the agent behave?</h2><form method='post' action='/usage/mode'><input type='hidden' name='csrf' value='{E(csrf)}'>"
            f"{radios}<button class='button primary' type='submit'>Save</button></form>"
            f"<h2>Need more tries?</h2><p class='muted'>Buy a pack for ₹100 (added to this month), or ask and we will review it.</p>"
            f"<p class='actions'><a class='button primary' href='/billing/pay?plan=pack_high'>Buy 5 High tries · ₹100</a>"
            f"<a class='button primary' href='/billing/pay?plan=pack_extra'>Buy 3 Extra tries · ₹100</a>"
            f"{more('high', 'Ask for more High tries')}{more('extra', 'Ask for more Extra tries')}</p>"
            f"<h2>Recent bugs</h2>{table}</section>")


def admin_page(d: dict, csrf: str, msg: str = "") -> str:
    b = d["burn"]
    pct = round(100 * b["spend_so_far"] / b["budget"]) if b["budget"] else 0
    tone = "green" if d["level"] == 0 else ("amber" if d["level"] < 3 else "red")
    stats = (f"<div class='stats'><span class='pill {tone}'>{E(d['level_name'])}</span>"
             f"<span class='pill'>Spent Rs {E(b['spend_so_far'])} of B = Rs {E(b['budget'])} ({E(pct)}%)</span>"
             f"<span class='pill'>Projected month end Rs {E(b['projected_month_end'])}</span>"
             f"<span class='pill'>Credits left (est.) Rs {E(d['credits_left_estimate'])}</span></div>")

    def post(action, fields, label, cls=""):
        inner = "".join(f"<input type='hidden' name='{E(k)}' value='{E(v)}'>" for k, v in fields.items())
        return (f"<form method='post' action='/admin/fix' style='display:inline'><input type='hidden' name='csrf' value='{E(csrf)}'>"
                f"<input type='hidden' name='action' value='{E(action)}'>{inner}<button class='button {cls}' type='submit'>{E(label)}</button></form> ")
    pauses = ""
    for tier in fx_config.TIERS:
        name = fx_config.USER_MODE_NAMES[tier]
        paused = tier in d["paused"]
        pauses += (f"<article class='card'><h3>{E(name)}</h3><p>{'<span class=\"pill red\">Paused</span>' if paused else '<span class=\"pill green\">Running</span>'}</p>"
                   f"{post('resume' if paused else 'pause', {'tier': tier}, 'Resume' if paused else 'Pause', '' if paused else 'danger')}</article>")
    tier_rows = "".join(f"<tr><td>{E(r['tier'])}</td><td>{E(r['model'])}</td><td>{E(r['tries'])}</td><td>{E(r['passes'] or 0)}</td>"
                        f"<td>{E(r['tokens_in'])}</td><td>{E(r['tokens_out'])}</td><td>Rs {E(round(r['spend'], 2))}</td></tr>" for r in d["by_tier"])
    tiers = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Mode</th><th>Model</th><th>Tries</th><th>Passes</th><th>Tokens in</th>"
             f"<th>Tokens out</th><th>Spend</th></tr></thead><tbody>{tier_rows}</tbody></table></div>") if tier_rows else "<div class='empty'>No model calls yet this month.</div>"
    user_rows = "".join(f"<tr><td>{E(r.get('email') or r['user_id'])}</td><td>{E(r['tries'])}</td><td>Rs {E(round(r['spend'], 2))}</td></tr>" for r in d["by_user"])
    users = (f"<div class='table-wrap'><table class='table'><thead><tr><th>User</th><th>Tries</th><th>Spend</th></tr></thead><tbody>{user_rows}</tbody></table></div>"
             if user_rows else "<div class='empty'>No users have used the agent yet.</div>")
    hold_rows = ""
    for h in d["holds"]:
        hold_rows += (f"<tr><td>{E(h.get('email') or h['user_id'])}</td><td>{E(fx_config.USER_MODE_NAMES.get(h['tier'], h['tier']))}</td>"
                      f"<td>{E(h['tries_requested'])}</td><td><pre style='white-space:pre-wrap;margin:0'>{E(h['analysis_json'])}</pre></td>"
                      f"<td>{post('approve_hold', {'hold_id': h['id']}, 'Approve', 'primary')}{post('deny_hold', {'hold_id': h['id']}, 'Deny', 'danger')}</td></tr>")
    holds = (f"<div class='table-wrap'><table class='table'><thead><tr><th>User</th><th>Mode</th><th>Tries</th><th>Analysis</th><th></th></tr></thead>"
             f"<tbody>{hold_rows}</tbody></table></div>") if hold_rows else "<div class='empty'>Nothing waiting for review.</div>"
    act_rows = "".join(f"<tr><td>{E(a['created_at'][:19])}</td><td>{E(a['kind'])}</td><td><code>{E(a['detail_json'][:160])}</code></td></tr>" for a in d["actions"])
    actions = (f"<div class='table-wrap'><table class='table'><thead><tr><th>When</th><th>Action</th><th>Detail</th></tr></thead><tbody>{act_rows}</tbody></table></div>"
               if act_rows else "<div class='empty'>No admin actions yet.</div>")
    flash = f"<div class='alert'>{E(msg)}</div>" if msg else ""
    pack_form = (f"<form method='post' action='/admin/fix'><input type='hidden' name='csrf' value='{E(csrf)}'>"
                 f"<input type='hidden' name='action' value='sell_pack'><div class='field'><label>Customer email (after you confirmed their Rs 100 payment)</label>"
                 f"<input name='email' type='email' required maxlength='200'></div><div class='field'><label>Pack</label>"
                 f"<select name='kind'><option value='high'>5 High tries</option><option value='extra'>3 Extra tries</option></select></div>"
                 f"<button class='button primary' type='submit'>Credit pack</button></form>")
    return (f"<section class='section'><p><a href='/admin'>← Admin</a></p><div class='eyebrow'>Auto-fix budget</div><h1>Spend and controls</h1>"
            f"{flash}{stats}<h2>Kill switches</h2><div class='grid'>{pauses}</div><h2>Requests waiting for you</h2>{holds}"
            f"<h2>Credit a Rs 100 pack</h2>{pack_form}<h2>This month by mode</h2>{tiers}<h2>This month by user</h2>{users}<h2>Admin log</h2>{actions}</section>")


RESULT_TEXT = {
    "pass": ("Fix passed the tests", "green"),
    "fail": ("Fix did not pass the tests", "red"),
    "unusable": ("No usable fix produced", "amber"),
    "system_fault": ("Technical problem on our side (not counted as a try)", "muted"),
    "pending": ("Running now…", "blue"),
}


def mode_path(tiers) -> str:
    """'Low effort ×3 → Normal ×1 → High ×1' from an ordered list of tiers."""
    runs: list[list] = []
    for t in tiers:
        if runs and runs[-1][0] == t:
            runs[-1][1] += 1
        else:
            runs.append([t, 1])
    return " → ".join(f"{fx_config.USER_MODE_NAMES.get(t, t)} ×{n}" for t, n in runs)


def trail_html(view: dict | None) -> str:
    """Per-incident timeline: which mode tried, what happened, and how the agent moved between modes. Modes, never model names."""
    if not view:
        return ""
    bug, attempts = view["bug"], view["attempts"]
    rows, prev = [], None
    n = 0
    for a in attempts:
        mode = fx_config.USER_MODE_NAMES.get(a["tier"], a["tier"])
        counted = a["result"] not in ("system_fault", "pending")
        if counted:
            n += 1
        label, tone = RESULT_TEXT.get(a["result"], (a["result"], "muted"))
        switch = f"<span class='pill amber'>Switched from {E(prev)} to {E(mode)}</span> " if prev and prev != mode and counted else ""
        tests = ""
        if a.get("failing_before") is not None and a.get("failing_after") is not None:
            tests = f"<br><small class='muted'>Failing tests: {E(a['failing_before'])} before, {E(a['failing_after'])} after this try</small>"
        note = ""
        if a["result"] in ("fail", "unusable") and a.get("diagnosis"):
            note = f"<br><small class='muted'>{E(a['diagnosis'][:220])}</small>"
        rows.append(f"<tr><td>{E(n) if counted else '–'}</td><td>{switch}<strong>{E(mode)}</strong></td>"
                    f"<td><span class='pill {tone}'>{E(label)}</span>{tests}{note}</td></tr>")
        if counted:
            prev = mode
    table = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Try</th><th>Mode</th><th>Result</th></tr></thead>"
             f"<tbody>{''.join(rows)}</tbody></table></div>") if rows else "<div class='empty'>No tries yet.</div>"
    tiers = [a["tier"] for a in attempts if a["result"] not in ("system_fault", "pending")]
    path = f"<p class='muted'>Path so far: <strong>{E(mode_path(tiers))}</strong></p>" if tiers else ""
    status = STATUS_TEXT.get(bug["status"], bug["status"])
    extra = ""
    if bug["status"] == "awaiting_choice":
        extra = "<p><a class='button primary' href='/usage'>Choose what happens next</a></p>"
    elif bug["status"] == "needs_human" and bug.get("review_report"):
        extra = f"<details><summary>Review report</summary><pre style='white-space:pre-wrap;overflow:auto'>{E(bug['review_report'])}</pre></details>"
    return (f"<h2>How the agent worked on this</h2><p class='muted'>Status: <strong>{E(status)}</strong>. "
            f"A try is one attempt to fix the bug. The agent starts with the cheapest mode and moves up only when it has to.</p>"
            f"{path}{table}{extra}")
