"""HTML for the usage page (customers) and the budget page (admins). Pure functions: no I/O, everything escaped.

Plain words only (plan 8): modes are Low effort / Normal / High / Extra, never model names, and costs are never
shown to customers as rupees-per-try. Admins see rupees.
"""
from __future__ import annotations

import html
import json

from . import config as fx_config

import plans

E = lambda v: html.escape(str(v if v is not None else ""), quote=True)

MODE_HELP = {
    "auto": ("Auto", "The Normal engineer works every case first. Only if it cannot finish does High take over; Extra only after "
                     "asking you. If you do not answer a question in 30 minutes, the agent continues with the cheaper option."),
    "ask": ("Ask me", "The agent pauses and asks you at every warning point, and waits as long as it takes."),
    "economy": ("Economy", "Only the Normal engineer works on your cases; High and Extra are never used. What Normal cannot finish goes to human review."),
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


def usage_page(view: dict, csrf: str, msg: str = "") -> str:
    msg_html = f"<div class='pill green' style='white-space:normal'>{E(msg)}</div>" if msg else ""
    cards = "".join(_tier_card(q) for q in view["panel"] if q.get("tier") != "groq")   # the free model no longer fixes
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
            f"<h1>Your tries this month</h1>{msg_html}"
            f"<p class='muted'>{E(plans.TRY_DEFINITION)} Tries reset on the 1st and buy attempts, not a guaranteed fix.</p>"
            f"{choices}<div class='grid'>{cards}</div>"
            f"<details class='card' style='margin-top:14px'><summary><b>How the agent uses your tries</b></summary>"
            f"<p class='muted'>{E(plans.MODE_SUMMARY)}</p><p class='muted'>{E(plans.WHY_STRONGER)}</p>"
            f"<p class='muted'>{E(plans.FAILED_FIX)}</p><p class='muted'>{E(plans.HUMAN_NEEDED)}</p>"
            f"<p><a href='/how-it-works#router'>See how the agent chooses an AI →</a></p></details>"
            f"<h2>How should the agent behave?</h2><form method='post' action='/usage/mode'><input type='hidden' name='csrf' value='{E(csrf)}'>"
            f"{radios}<button class='button primary' type='submit'>Save</button></form>"
            f"<h2>Need more tries?</h2><p class='muted'>Buy a pack for ₹100 (added to this month), or ask and we will review it.</p>"
            f"<p class='actions'><a class='button primary' href='/billing/pay?plan=pack_high'>Buy 5 High tries · ₹100</a>"
            f"<a class='button primary' href='/billing/pay?plan=pack_extra'>Buy 3 Extra tries · ₹100</a>"
            f"{more('high', 'Ask for more High tries')}{more('extra', 'Ask for more Extra tries')}</p>"
            f"<h2>Recent bugs</h2>{table}</section>")


ADMIN_CSS = """<style>
.fx-admin .money{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:14px;margin:14px 0}
.fx-admin .money article{background:linear-gradient(145deg,#170d22,#0f0817);border:1px solid var(--line);border-radius:14px;padding:16px}
.fx-admin .money .big{font-size:28px;font-weight:700;margin:4px 0}.fx-admin .money p{margin:4px 0;font-size:13.5px}
.fx-admin .meter{position:relative;height:14px;border-radius:8px;background:#ffffff12;overflow:visible;margin:22px 0 30px}
.fx-admin .meter>i{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,#1f8a63,#e3bd74,#d1121f)}
.fx-admin .meter .tick{position:absolute;top:-6px;height:26px;border-left:2px dashed #ffffff55}
.fx-admin .meter .tick span{position:absolute;top:28px;left:-14px;font-size:11px;color:var(--muted);white-space:nowrap}
.fx-admin tr.now td{background:#2a1645}.fx-admin .why{font-size:13px;color:#cfc5dc}
.fx-admin .hold{background:linear-gradient(145deg,#170d22,#0f0817);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}
.fx-admin .hold dl{display:grid;grid-template-columns:minmax(150px,max-content) 1fr;gap:6px 14px;margin:10px 0}.fx-admin .hold dt{color:var(--muted)}
.fx-admin .hold dd{margin:0}.fx-admin details.tech{margin-top:10px}.fx-admin details.tech pre{white-space:pre-wrap;font-size:12px;background:#0a0610;border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto}
.fx-admin .explain{background:#120a1bcc;border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0;font-size:14px;color:#d8cde6}
.fx-admin .explain b{color:#fff}.fx-admin code{overflow-wrap:anywhere}
@media(max-width:640px){.fx-admin .hold dl{grid-template-columns:1fr}.fx-admin .money .big{font-size:24px}}
</style>"""

ADMIN_KIND_TEXT = {
    "auto_grant": "Extra tries granted automatically", "hold": "Request held for admin review", "hold_approved": "Request approved",
    "hold_denied": "Request denied", "pause": "Mode paused", "resume": "Mode resumed", "pack_sold": "Try pack credited",
    "budget_level": "Budget threshold reached", "spike_breaker": "Spike breaker paused paid modes",
}


def _rs(v) -> str:
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return "₹0.00"


def _protection_rows(d: dict) -> str:
    pr, cfg = d["protection"], d["cfg"]
    lv = d["level"]
    caps = cfg["caps"]
    rows = [
        (1, f"{int(pr['fractions'][0] * 100)}% of the limit", _rs(pr["levels"][0]),
         "Both admins get an email. Nothing changes for customers.", "None",
         "An early warning while there is still plenty of room.", "No. Keep an eye on the forecast."),
        (2, f"{int(pr['fractions'][1] * 100)}% of the limit", _rs(pr["levels"][1]),
         "Automatic approval of 'ask for more tries' requests stops: every request now waits for you. Bought packs keep working.",
         "None paused", "Free extras are the first thing to cut when money is getting tight.",
         "Yes, when requests appear under 'Requests waiting for you'."),
        (3, f"{int(pr['fractions'][2] * 100)}% of the limit", _rs(pr["levels"][2]),
         "Extra is paused for plan tries. Customers who bought an Extra pack can still use it.", "Extra",
         "Extra is the most expensive mode per attempt, so it is paused first.", "Optional: top up credits and raise the limit."),
        (4, f"{int(pr['fractions'][3] * 100)}% of the limit", _rs(pr["levels"][3]),
         "High is paused too (pack tries still work). Normal and Low effort continue, so bugs are still worked on.", "High, Extra",
         "Keeps the month inside the limit while the cheap modes keep serving customers.", "Yes, if you want High/Extra back this month."),
        (5, f"Reserve floor ({int(pr['reserve_fraction'] * 100)}% of credits)", _rs(pr["reserve_floor"]),
         "Every paid mode stops, including bought packs. Only Low effort (free) runs. Customers see a 'busy' message.",
         "Normal, High, Extra", "Protects the last part of the prepaid credits so the provider account never runs dry mid-fix.",
         "Yes: top up provider credits, then update FIXENGINE_CREDITS_INR / FIXENGINE_BUDGET_INR."),
    ]
    out = []
    for level, name, trigger, does, modes, why, admin in rows:
        cls = " class='now'" if lv == level else ""
        out.append(f"<tr{cls}><td><b>{E(name)}</b><br><small class='muted'>at {E(trigger)}</small></td><td>{E(does)}</td>"
                   f"<td>{E(modes)}</td><td class='why'>{E(why)}</td><td>{E(admin)}</td></tr>")
    spike_state = ("<b>tripped</b>: paid modes are paused until you resume them" if pr["spike_paused"] else "armed")
    out.append(f"<tr{' class=now' if pr['spike_paused'] else ''}><td><b>Spike breaker</b><br><small class='muted'>last hour &gt; "
               f"{E(pr['spike_multiple'])}× the normal hourly rate and ≥ {E(_rs(pr['spike_min']))}</small></td>"
               f"<td>Pauses Normal, High and Extra and emails you. Now {spike_state}. Last hour {E(_rs(pr['last_hour']))} vs normal "
               f"{E(_rs(pr['normal_per_hour']))}/hour.</td><td>Normal, High, Extra</td>"
               "<td class='why'>Catches runaway loops or abuse within an hour, long before the monthly levels would.</td>"
               "<td>Yes: find the cause, then press Resume for each mode below.</td></tr>")
    out.append(f"<tr><td><b>Per-customer and per-bug limits</b><br><small class='muted'>always on</small></td>"
               f"<td>A customer's AI spend stops at {E(_rs(caps['user_month_ceiling_inr']))} a month; one bug stops at "
               f"{E(_rs(caps['per_bug_cost_inr']))} or {E(caps['per_bug_max_tries'])} tries; at most {E(caps['tries_per_hour_per_user'])} tries an hour; "
               f"a {E(caps['cooldown_minutes'])}-minute pause after {E(caps['cooldown_after_failures'])} failed bugs in a row.</td>"
               "<td>Paid modes for that customer or bug</td><td class='why'>One customer or one hard bug can never eat the whole budget.</td>"
               "<td>No. The bug goes to human review with a report.</td></tr>")
    return "".join(out)


def _hold_card(h: dict, d: dict, post) -> str:
    a = h.get("analysis") or {}
    mode = fx_config.USER_MODE_NAMES.get(h["tier"], h["tier"])
    q = h.get("quota") or {}
    tries = int(h.get("tries_requested") or 0)
    worst = round(tries * float(h.get("try_cost") or 0), 2)
    projected = float(a.get("projected_month_end") or d["burn"]["projected_month_end"])
    budget = float(a.get("budget") or d["burn"]["budget"] or 0)
    reasons = []
    frac = float(d["protection"]["auto_grant_fraction"])
    if a.get("projected_fraction") is not None and float(a["projected_fraction"]) >= frac:
        reasons.append(f"the month-end forecast ({_rs(projected)}) is at or above {int(frac * 100)}% of the limit")
    if a.get("others_quota_utilization") is not None and float(a["others_quota_utilization"]) >= 0.5:
        reasons.append(f"other customers have already used {int(float(a['others_quota_utilization']) * 100)}% of their paid tries")
    if int(a.get("budget_level") or 0) >= 2:
        reasons.append("spending had passed the 80% level, where automatic approvals stop")
    if a.get("auto_granted_before_this_month"):
        reasons.append("this customer already got an automatic bonus for this mode this month")
    if a.get("note"):
        reasons.append(str(a["note"]))
    why = "; ".join(reasons) or "the automatic rules could not approve it, so it needs a person"
    usage = f"{q.get('used', '?')} of {q.get('total', '?')} {mode} tries used this month" if q else "unknown"
    import json as _json
    tech = _json.dumps(a, indent=2, sort_keys=True)
    confirm = (f"Approve {tries} extra {mode} tries for {h.get('email') or 'this customer'}? Worst case about {_rs(worst)} more AI spend this month.")
    return (f"<div class='hold'><div class='row'><h3>{E(h.get('email') or h['user_id'])} asks for {E(tries)} more {E(mode)} tries</h3>"
            f"<span class='pill amber'>waiting since {E(str(h.get('created_at', ''))[:16].replace('T', ' '))}</span></div>"
            f"<dl><dt>Monthly usage</dt><dd>{E(usage)}</dd>"
            f"<dt>Customer's AI spend</dt><dd>{E(_rs(a.get('user_month_spend', 0)))} this month (limit {E(_rs(d['cfg']['caps']['user_month_ceiling_inr']))})</dd>"
            f"<dt>Our spend now</dt><dd>{E(_rs(a.get('spend_so_far', d['burn']['spend_so_far'])))} of {E(_rs(budget))}</dd>"
            f"<dt>Forecast for month end</dt><dd>{E(_rs(projected))} ({E(int(round(100 * projected / budget)) if budget else '?')}% of the limit)</dd>"
            f"<dt>Why it was not approved automatically</dt><dd>{E(why)}.</dd>"
            f"<dt>If you approve</dt><dd>The customer gets {E(tries)} extra {E(mode)} tries for this month. Each try typically costs about "
            f"{E(_rs(h.get('try_cost', 0)))}, so the worst case is about {E(_rs(worst))} more spend (forecast becomes about {E(_rs(projected + worst))}). "
            f"The spending protections above still apply to these tries.</dd>"
            f"<dt>If you deny</dt><dd>Nothing is spent. The customer keeps their current tries and can still buy a ₹100 pack.</dd></dl>"
            f"<p class='actions'>{post('approve_hold', {'hold_id': h['id']}, 'Approve', 'primary', confirm)}"
            f"{post('deny_hold', {'hold_id': h['id']}, 'Deny', 'danger', 'Deny this request? The customer is not charged and keeps their current tries.')}</p>"
            f"<details class='tech'><summary>Technical details</summary><p class='muted'>The raw analysis saved when the request was made "
            f"(spend values in ₹; projected_fraction = forecast ÷ limit; budget_level 0–5 matches the protection table).</p>"
            f"<pre>{E(tech)}</pre></details></div>")


def admin_page(d: dict, csrf: str, msg: str = "") -> str:
    b, pr, cfg = d["burn"], d["protection"], d["cfg"]
    budget = float(b["budget"] or 0)
    pct = round(100 * b["spend_so_far"] / budget) if budget else 0
    proj_pct = round(100 * b["projected_month_end"] / budget) if budget else 0
    tone = "green" if d["level"] == 0 else ("amber" if d["level"] < 3 else "red")
    level_text = {0: "All normal: every mode is available.", 1: "Past 50%: admins were emailed, customers unaffected.",
                  2: "Past 80%: extra-try requests now wait for you.", 3: "Past 90%: Extra is paused (packs still work).",
                  4: "At the limit: High and Extra are paused (packs still work).",
                  5: "Reserve floor: only Low effort runs."}.get(d["level"], d["level_name"])

    def post(action, fields, label, cls="", confirm=""):
        inner = "".join(f"<input type='hidden' name='{E(k)}' value='{E(v)}'>" for k, v in fields.items())
        guard_js = f" onsubmit=\"return confirm({E(json.dumps(confirm))})\"" if confirm else ""
        return (f"<form method='post' action='/admin/fix' style='display:inline'{guard_js}><input type='hidden' name='csrf' value='{E(csrf)}'>"
                f"<input type='hidden' name='action' value='{E(action)}'>{inner}<button class='button {cls}' type='submit'>{E(label)}</button></form> ")

    # ---- A. financial overview
    ticks = "".join(f"<span class='tick' style='left:{min(100, int(f * 100))}%'><span>{int(f * 100)}%</span></span>" for f in pr["fractions"])
    overview = (f"<div class='money'>"
                f"<article><div class='eyebrow'>Total AI spending this month</div><div class='big'>{E(_rs(b['spend_so_far']))}</div>"
                f"<p class='muted'>Tracked by us: every model call's input and output tokens × the configured price. It is our own record; "
                f"the provider's invoice is the final word.</p></article>"
                f"<article><div class='eyebrow'>Monthly spending limit (B)</div><div class='big'>{E(_rs(budget))}</div>"
                f"<p class='muted'>Our internal ceiling, set below the prepaid credits ({E(_rs(pr['credits']))}) so there is always a reserve. "
                f"{E(pct)}% used.</p></article>"
                f"<article><div class='eyebrow'>Expected month-end spending</div><div class='big'>{E(_rs(b['projected_month_end']))}</div>"
                f"<p class='muted'>Forecast = spend so far ÷ {E(b['days_elapsed'])} days elapsed × days in the month ({E(proj_pct)}% of the limit). "
                f"A prediction from the pace so far, not a guaranteed amount.</p></article>"
                f"<article><div class='eyebrow'>Estimated credits remaining</div><div class='big'>{E(_rs(d['credits_left_estimate']))}</div>"
                f"<p class='muted'>Credits you told us you bought (FIXENGINE_CREDITS_INR) minus this month's tracked spend. "
                f"<b>Not a live balance</b>: check the provider console (OpenRouter / Anthropic) for the real number.</p></article></div>"
                f"<div class='meter' role='img' aria-label='{E(pct)}% of the monthly limit used'><i style='width:{min(100, pct)}%'></i>{ticks}</div>"
                f"<div class='stats'><span class='pill {tone}'>{E(level_text)}</span></div>")

    # ---- B. protections
    protections = ("<div class='table-wrap'><table class='table'><thead><tr><th>Protection</th><th>What Agent Daemon does</th>"
                   "<th>Modes affected</th><th>Why it exists</th><th>Do you need to act?</th></tr></thead>"
                   f"<tbody>{_protection_rows(d)}</tbody></table></div>"
                   "<p class='muted'>All of this is automatic and checked before every AI call. Each threshold emails both admins once per month. "
                   "The highlighted row is where spending is now. Low effort (free) is never paused by the budget.</p>")

    # ---- F1. mode switches
    pauses = ""
    for tier in fx_config.TIERS:
        name = fx_config.USER_MODE_NAMES[tier]
        paused = tier in d["paused"]
        state = "<span class='pill red'>Paused</span>" if paused else "<span class='pill green'>Running</span>"
        msg_c = (f"Resume {name}? New {name} attempts will be allowed again (all budget protections still apply)." if paused else
                 f"Pause {name} for everyone? New {name} attempts are refused; the agent uses other modes or sends bugs to human review.")
        pauses += (f"<article class='card'><div class='row'><h3>{E(name)}</h3>{state}</div>"
                   f"<p class='muted'>{E(cfg['models'].get(tier, ''))}</p>"
                   f"{post('resume' if paused else 'pause', {'tier': tier}, 'Resume' if paused else 'Pause', '' if paused else 'danger', msg_c)}</article>")

    # ---- C. provider spending
    prices = cfg["prices_usd_per_m"]
    tier_rows = ""
    for r in d["by_tier"]:
        tries, passes = int(r["tries"] or 0), int(r["passes"] or 0)
        rate = f" ({round(100 * passes / tries)}%)" if tries else ""
        pz = prices.get(r["tier"], {})
        tier_rows += (f"<tr><td><b>{E(fx_config.USER_MODE_NAMES.get(r['tier'], r['tier']))}</b></td><td><code>{E(r['model'])}</code>"
                      f"<br><small class='muted'>${E(pz.get('in', '?'))} in / ${E(pz.get('out', '?'))} out per 1M tokens</small></td>"
                      f"<td>{E(tries)}{(' <small class=muted>+' + E(r['faults']) + ' faults</small>') if r.get('faults') else ''}</td>"
                      f"<td>{E(passes)}{E(rate)}</td><td>{int(r['tokens_in'] or 0):,}</td><td>{int(r['tokens_out'] or 0):,}</td>"
                      f"<td>{E(_rs(r['spend']))}</td></tr>")
    tiers = (f"<div class='table-wrap'><table class='table'><thead><tr><th>AI mode</th><th>Provider / model</th><th>Attempts</th>"
             f"<th>Successful fixes</th><th>Input tokens</th><th>Output tokens</th><th>Spending</th></tr></thead><tbody>{tier_rows}</tbody></table></div>"
             if tier_rows else "<div class='empty'>No model calls yet this month.</div>")
    tokens_help = ("<div class='explain'><b>Tokens, in one minute.</b> Models read and write text in <i>tokens</i>, small chunks of "
                   "about 3–4 characters of English or code. Providers bill per million tokens. <b>Input tokens</b> are everything we send in "
                   "one request: the instructions, the relevant source files, the error output and a short history of earlier tries. "
                   "<b>Output tokens</b> are what the model writes back: its diagnosis and the patch. Output costs several times more per token "
                   "than input. One attempt's cost = (input tokens × input price + output tokens × output price) ÷ 1,000,000 × "
                   f"₹{E(cfg['usd_inr'])} per dollar. Faults (provider or sandbox errors) are not counted as attempts and never use a "
                   f"customer's quota. Provider setting: <code>FIXENGINE_PROVIDER={E(d.get('provider', 'auto'))}</code>.</div>")

    # ---- D. user spending
    urows = ""
    emails = {r["user_id"]: r.get("email") for r in d.get("by_user", [])}
    for u in d.get("users", []):
        qs = u["quotas"]
        cells = "".join(f"<td>{E(qs[t]['used'])} / {E(qs[t]['total'])}</td>" for t in fx_config.PAID_TIERS)
        share = round(100 * u["spend"] / u["ceiling"]) if u["ceiling"] else 0
        urows += (f"<tr><td>{E(u.get('email') or emails.get(u['user_id']) or u['user_id'])}</td><td>{E(u['tries'])}</td><td>{E(u['passes'])}</td>"
                  f"{cells}<td>{E(_rs(u['spend']))}<br><small class='muted'>{E(share)}% of the per-customer limit</small></td></tr>")
    users = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Customer</th><th>Attempts</th><th>Successful fixes</th>"
             f"<th>Normal used</th><th>High used</th><th>Extra used</th><th>AI spend they caused</th></tr></thead><tbody>{urows}</tbody></table></div>"
             if urows else "<div class='empty'>No customers have used the agent this month.</div>")

    # ---- E. approvals
    holds = "".join(_hold_card(h, d, post) for h in d["holds"]) or "<div class='empty'>Nothing waiting for review.</div>"

    # ---- F2. history, quotas, log
    hist_rows = "".join(f"<tr><td>{E(h['period'])}</td><td>{E(h['tries'])}</td><td>{E(h['passes'])}</td><td>{E(_rs(h['spend']))}</td></tr>"
                        for h in d.get("history", []))
    history = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Month</th><th>Attempts</th><th>Successful fixes</th>"
               f"<th>Tracked AI spend</th></tr></thead><tbody>{hist_rows}</tbody></table></div>")
    q = cfg["quotas"]
    settings = [("Monthly tries per customer", f"Normal {q['haiku']} · High {q['sonnet']} · Extra {q['opus']} · Low effort {cfg['groq_daily_cap']}/day",
                 "FIXENGINE_CONFIG_JSON → quotas / groq_daily_cap"),
                ("Monthly spending limit B", _rs(budget), "FIXENGINE_BUDGET_INR"),
                ("Prepaid credits", _rs(pr["credits"]), "FIXENGINE_CREDITS_INR"),
                ("Per-bug cap", f"{_rs(cfg['caps']['per_bug_cost_inr'])} or {cfg['caps']['per_bug_max_tries']} tries", "FIXENGINE_PER_BUG_CAP_INR"),
                ("Per-customer monthly AI limit", _rs(cfg["caps"]["user_month_ceiling_inr"]), "FIXENGINE_CONFIG_JSON → caps"),
                ("Automatic approval of extra tries", f"while the forecast is under {int(pr['auto_grant_fraction'] * 100)}% of B; +{pr['auto_grant_high']} High",
                 "FIXENGINE_CONFIG_JSON → budget"),
                ("Dollar rate", f"₹{cfg['usd_inr']} per $1", "FIXENGINE_USD_INR")]
    set_rows = "".join(f"<tr><td>{E(k)}</td><td><b>{E(v)}</b></td><td><code>{E(env)}</code></td></tr>" for k, v, env in settings)
    quotas = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Setting</th><th>Current value</th><th>Change it with (Render → Environment)</th>"
              f"</tr></thead><tbody>{set_rows}</tbody></table></div><p class='muted'>Values come from <code>fixengine/config.py</code> plus these "
              "overrides. Changing them needs a redeploy, which is deliberate: money settings should not be one click away.</p>")
    act_rows = ""
    for a in d["actions"]:
        kind = ADMIN_KIND_TEXT.get(a["kind"], a["kind"])
        act_rows += (f"<tr><td>{E(a['created_at'][:16].replace('T', ' '))}</td><td>{E(kind)}</td>"
                     f"<td><details class='tech'><summary>Technical details</summary><pre>{E(a['detail_json'])}</pre></details></td></tr>")
    actions = (f"<div class='table-wrap'><table class='table'><thead><tr><th>When (UTC)</th><th>What happened</th><th></th></tr></thead><tbody>{act_rows}</tbody></table></div>"
               if act_rows else "<div class='empty'>No admin actions yet.</div>")
    flash = f"<div class='alert'>{E(msg)}</div>" if msg else ""
    pack_form = (f"<form method='post' action='/admin/fix' onsubmit=\"return confirm('Credit this pack? Only do this after you have received the ₹100 payment.')\">"
                 f"<input type='hidden' name='csrf' value='{E(csrf)}'>"
                 f"<input type='hidden' name='action' value='sell_pack'><div class='field'><label>Customer email</label>"
                 f"<input name='email' type='email' required maxlength='200'></div><div class='field'><label>Pack</label>"
                 f"<select name='kind'><option value='high'>5 High tries</option><option value='extra'>3 Extra tries</option></select></div>"
                 f"<button class='button primary' type='submit'>Credit pack</button></form>")
    return (f"{ADMIN_CSS}<section class='section fx-admin'><p><a href='/admin'>← Admin</a> · <a href='/admin/architecture'>How the router decides →</a></p>"
            f"<div class='eyebrow'>Auto-fix money</div><h1>AI spending and controls</h1>{flash}"
            f"<h2>This month at a glance</h2>{overview}"
            f"<h2>Requests waiting for you</h2><p class='muted'>Customers who ran out of tries and pressed 'Ask for more'. The system approves small "
            f"requests by itself when money is comfortable; everything else lands here.</p>{holds}"
            f"<h2>Spending protection</h2>{protections}"
            f"<h2>Mode switches</h2><p class='muted'>Pausing a mode stops new attempts in that mode for every customer. Attempts already "
            f"running finish. Use it during a provider outage, a price change or after the spike breaker trips.</p><div class='grid'>{pauses}</div>"
            f"<h2>Spending by AI mode (this month)</h2>{tokens_help}{tiers}"
            f"<h2>Spending by customer (this month)</h2><p class='muted'>Attempts and spend caused by each customer's bugs. "
            f"Quota columns show plan tries plus any bonus or pack tries.</p>{users}"
            f"<h2>Spending history</h2>{history}"
            f"<h2>Credit a try pack by hand</h2><p class='muted'>Packs paid by UPI are credited automatically when you confirm the payment on "
            f"<a href='/admin'>/admin</a>. Use this only for special cases (a refund, a goodwill gesture, a payment made another way).</p>{pack_form}"
            f"<h2>Quotas and budgets</h2>{quotas}<h2>Admin log</h2>{actions}</section>")


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
            f"A try is one attempt by the AI to fix the bug. The agent starts with the free and economical modes and moves to a stronger AI "
            f"only when it has to.</p>"
            f"{path}{table}{extra}")
