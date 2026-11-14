"""Live incident board for the Agent Daemon portal.

One place that knows how to show an incident:
  * a step tracker (Detected > Diagnosed > Fix PR > Checks > Merged) built from the real incident state,
  * a clear headline status ("Fixed · auto-merged", "Checks failed · needs review", ...),
  * the report as a dropdown, split into readable sections,
  * a fragment the browser re-fetches every few seconds, so nobody has to refresh.

Everything that reaches the page is escaped here. The browser script is served from the same origin
(the portal's Content-Security-Policy blocks inline scripts).
"""
from __future__ import annotations

import html

import media_input
import re
from datetime import datetime, timedelta, timezone

LIVE_JS_VERSION = "3"

_TONES = {"green", "amber", "red", "blue", "muted"}
_DIAGNOSING = {"diagnosing", "queued", "processing"}


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _fmt_ist(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def _ago(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "never"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:19]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - moment).total_seconds())
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _safe_pr_url(url) -> str:
    url = str(url or "").strip()
    return url if url.startswith("https://github.com/") else ""


def stage_for(incident: dict, mode: str) -> dict:
    """Work out the headline, colour and step list from what is really stored for the incident.

    Incidents worked on by architecture v3 carry a live `stage` (downloading, reproducing, thinking, testing_fix, pushing,
    merging, ...). Those use live_status, which also names the mode that is working. Older incidents fall back to the status."""
    if incident.get("stage"):
        import live_status
        v = live_status.incident_view(incident, mode)
        headline = v["headline"]
        if v["mode_name"] and v["stage"] in ("thinking", "testing_fix", "pushing", "waiting_user"):
            headline = f"{headline} · {v['mode_name']} mode" if v["mode_name"] not in headline else headline
        return {"headline": headline, "tone": v["tone"] if v["tone"] in _TONES else "muted", "steps": v["steps"],
                "active": v["active"], "detail": v["detail"]}
    status = str(incident.get("status") or "")
    ci = str(incident.get("ci_status") or "unknown")
    pr_url = _safe_pr_url(incident.get("pr_url"))
    auto = mode == "auto"
    final = "Auto-merge" if auto else "Your review"
    steps = [("Detected", "done")]
    active = False

    if status in _DIAGNOSING:
        steps.append(("Diagnosing", "active"))
        if mode != "report":
            steps += [("Fix PR", "todo"), ("Checks", "todo"), (final, "todo")]
        headline, tone, active = "Diagnosing…", "amber", True
    elif status == "diagnosed":
        steps.append(("Diagnosed", "done"))
        if mode == "report":
            headline, tone = "Diagnosed · report ready", "green"
        else:
            steps += [("Fix PR", "active"), ("Checks", "todo"), (final, "todo")]
            headline, tone, active = "Diagnosed · preparing a fix…", "amber", True
    elif status == "pr_opened":
        steps += [("Diagnosed", "done"), ("Fix PR opened", "done")]
        if ci == "failed":
            steps += [("Checks failed", "fail"), (final, "todo")]
            headline, tone = "Checks failed · needs review", "red"
        elif ci == "success":
            steps += [("Checks passed", "done"), (final, "active" if auto else "todo")]
            if auto:
                headline, tone, active = "Checks passed · merging…", "blue", True
            else:
                headline, tone = "Checks passed · ready for you to merge", "blue"
        else:
            steps += [("Checks running", "active"), (final, "todo")]
            headline, tone, active = "Fix PR opened · checks running", "blue", True
    elif status == "resolved":
        if pr_url:
            steps += [("Diagnosed", "done"), ("Fix PR opened", "done"), ("Checks passed", "done"), ("Merged", "done")]
            headline = "Fixed · auto-merged" if auto else "Fixed · merged"
        else:
            steps += [("Diagnosed", "done"), ("Resolved", "done")]
            headline = "Resolved"
        tone = "green"
    elif status == "awaiting_choice":
        steps += [("Diagnosing", "active"), ("Your decision", "active"), ("Fix PR", "todo")]
        headline, tone, active = "Waiting for your decision · open Fix usage", "amber", True
    elif status == "needs_human":
        steps += [("Diagnosed", "done" if (incident.get("report") or incident.get("root_cause")) else "fail"),
                  ("No fix PR created", "fail")]
        headline, tone = "Needs human review", "red"
    else:
        headline, tone = (status.replace("_", " ").title() or "Unknown"), "muted"
    return {"headline": headline, "tone": tone if tone in _TONES else "muted", "steps": steps, "active": active}


# ----------------------------------------------------------------------------- report formatting

_OUTCOME_RE = re.compile(r"(?:\\n|\n|\s)*(Fix pull request opened:|No fix PR was created:)")
_SECTION_RE = re.compile(r"(?m)^\s*\d\.\s+([A-Z][A-Z ,'’/&-]{2,40}):[ \t]*")


def parse_report(report: str) -> dict:
    """Split the six-section report (plus the outcome line the system appends) into blocks."""
    text = str(report or "").replace("\r\n", "\n").replace("\\n", "\n").strip()
    outcome = ""
    found = _OUTCOME_RE.search(text)
    if found:
        outcome = text[found.start(1):].strip()
        text = text[:found.start()].strip()
    parts = _SECTION_RE.split(text)
    sections = []
    if len(parts) >= 3:
        # parts = [preamble, title1, body1, title2, body2, ...]
        for i in range(1, len(parts) - 1, 2):
            sections.append((parts[i].strip().title(), parts[i + 1].strip()))
    elif text:
        sections.append(("Report", text))
    return {"sections": sections, "outcome": outcome}


def _render_report(incident: dict, stage: dict) -> str:
    parsed = parse_report(incident.get("report"))
    iid = _e(incident.get("id"))
    fixed = stage["tone"] == "green" and incident.get("status") == "resolved"
    blocks = []
    for title, body in parsed["sections"]:
        if title.lower() == "what the agent did":
            continue  # the step tracker above shows what really happened
        if not body:
            continue
        block = f"<div class='rp-sec'><h4>{_e(title)}</h4><p>{_e(body)}</p></div>"
        if title.lower() == "what you need to do" and fixed:
            block = (f"<details class='rp-sub' data-id='{iid}:manual'><summary>Manual steps (not needed, the fix is merged)</summary>"
                     f"<p>{_e(body)}</p></details>")
        blocks.append(block)
    if parsed["outcome"]:
        blocks.append(f"<div class='rp-sec'><h4>Agent outcome</h4><p>{_e(parsed['outcome'])}</p></div>")
    if not blocks:
        blocks.append("<div class='rp-sec'><p class='muted'>The report is not ready yet. This page updates by itself.</p></div>")
    return "".join(blocks)


# ----------------------------------------------------------------------------- rendering

def _render_steps(steps) -> str:
    items = "".join(f"<li class='{_e(state)}'><span class='dot'></span>{_e(label)}</li>" for label, state in steps)
    return f"<ol class='steps'>{items}</ol>"


def _case_title(inc: dict) -> str:
    """A name a person recognises: the error itself, or 'Your report' for something the owner typed."""
    signature = " ".join(str(inc.get("signature") or "").split())
    if not signature or signature == "unknown":
        return "Incident"
    if signature.startswith("user_report:"):
        return "Your report"
    return signature if len(signature) <= 90 else signature[:88] + "…"


def question_box_html(inc: dict, project_id: str, csrf: str) -> str:
    """The agent asked the owner something: show the question with a box to answer it, right on the case card.
    It sits outside the <summary>, so typing a space never folds the card, and the live refresh leaves it alone while you type."""
    live = str(inc.get("live_result") or "")
    if not csrf or not live.startswith("QUESTION: "):
        return ""
    iid = str(inc.get("id") or "")
    return (f"<div class='inc-question' id='answer-{_e(iid)}'><div class='q-head'><span class='q-badge'>The agent is asking you</span>"
            "<small class='muted'>It waits for your answer and spends nothing meanwhile.</small></div>"
            f"<p class='q-text'>{_e(live[10:].strip())}</p>"
            f"<form method='post' action='/projects/{_e(project_id)}/incidents/{_e(iid)}/reply' data-media>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'><input type='hidden' name='next' value='/projects/{_e(project_id)}#case-{_e(iid)}'>"
            "<label class='sr-only' for='answer-text-" + _e(iid) + "'>Your answer</label>"
            f"<textarea id='answer-text-{_e(iid)}' name='text' rows='3' maxlength='1000' required placeholder='Type your answer here'></textarea>"
            + media_input.inputs_html() +
            "<div class='q-actions'><button class='button primary' type='submit'>Send answer</button>"
            "<small class='muted'>The agent continues right away with your answer.</small></div></form></div>")


def diagnosis_box_html(inc: dict, project_id: str, csrf: str) -> str:
    """v6 diagnose first: what the engineer found, the fix it proposes and what it will use of the bars, with the owner's buttons.
    Reads the flags the engine writes (diagnosis:, guide_offer:, founder_offer:). Nothing shows when there is no diagnosis waiting.
    founder_offer is set only in the worst case (a very big job that failed after everything was tried): a link to the custom-job form."""
    if not csrf:
        return ""
    import json
    from fixengine import store as fx_store
    iid = str(inc.get("id") or "")
    try:
        raw = fx_store.get_flag(f"diagnosis:{iid}", "")
        founder_offer = fx_store.get_flag(f"founder_offer:{iid}", "") == "1"
        guide_offer = fx_store.get_flag(f"guide_offer:{iid}", "")
    except Exception:          # the case card must always render, even if the engine's tables are not reachable
        return ""
    if not raw and not founder_offer and not guide_offer:
        return ""
    try:
        d = json.loads(raw) if raw else {}
    except ValueError:
        d = {}
    if str(inc.get("stage") or "awaiting_approval") != "awaiting_approval":
        d = {}                     # the owner already answered (or the case moved on): no "Yes, fix it" on a finished case
    if not d and not guide_offer and not founder_offer:
        return ""
    base = f"/projects/{_e(project_id)}/incidents/{_e(iid)}"
    hidden = (f"<input type='hidden' name='csrf' value='{_e(csrf)}'>"
              f"<input type='hidden' name='next' value='/projects/{_e(project_id)}#case-{_e(iid)}'>")
    parts = ["<div class='inc-diagnosis' id='diagnosis-" + _e(iid) + "'>" + ("<div class='q-head'><span class='q-badge'>Diagnosis</span>"
             "<small class='muted'>Nothing is changed until you say yes.</small></div>" if d or guide_offer else "")]
    if d:
        where = ", ".join(str(w) for w in (d.get("where") or [])[:6])
        sure = {"high": "The engineer is sure.", "medium": "The engineer is fairly sure.", "low": "The engineer is not sure yet."}.get(
            str(d.get("confidence")), "")
        use = f"This fix will use about {int(d.get('est_engineer_pct') or 0)}% of your Engineer bar"
        if d.get("est_lead_pct"):
            use += f" and about {int(d.get('est_lead_pct'))}% of your Lead engineer bar (a review before it goes live)"
        parts.append(f"<p><b>What broke:</b> {_e(d.get('what_broke', ''))}</p><p><b>Why:</b> {_e(d.get('why', ''))}</p>"
                     + (f"<p><b>Where:</b> <code>{_e(where)}</code></p>" if where else "")
                     + f"<p><b>The fix:</b> {_e(d.get('proposed_fix', ''))}</p><p class='muted'>{_e(sure)}</p>")
        parts.append(f"<form method='post' action='{base}/approve' class='diag-yes'>{hidden}"
                     "<label><input type='radio' name='style' value='proper' checked> <b>Proper fix</b> · with a test that proves it</label>"
                     "<label><input type='radio' name='style' value='quick'> <b>Quick fix</b> · faster, no new test</label>"
                     f"<button class='button primary' type='submit'>Yes, fix it</button><small class='muted'>{_e(use)}.</small></form>")
        parts.append(f"<details class='diag-no'><summary>That's not it</summary>"
                     f"<form method='post' action='{base}/reply' data-media>{hidden}<input type='hidden' name='rejects_diagnosis' value='1'>"
                     "<p class='muted'>Tell the agent what you see or what you think is wrong. Add a screenshot or just speak. "
                     "It looks again with your words.</p>"
                     "<textarea name='text' rows='3' maxlength='1000' placeholder='What is really happening?'></textarea>"
                     + media_input.inputs_html() + "<button class='button' type='submit'>Look again</button></form></details>")
    if guide_offer:
        try:
            pct = int(json.loads(guide_offer).get("est_lead_pct") or 0)
        except ValueError:
            pct = 0
        parts.append(f"<form method='post' action='{base}/guide'>{hidden}<p>The engineer tried twice and could not finish. The Lead "
                     f"engineer can look at both tries and tell it exactly what to change.</p><button class='button primary' type='submit'>"
                     f"Let the Lead engineer guide it</button><small class='muted'>About {pct}% of your Lead engineer bar.</small></form>")
    if founder_offer:
        # Only the worst case (a very big job that failed after everything was tried): a link to the paid custom-job form.
        parts.append(f"<p class='muted'>This one is too big for an automatic fix. If you want, the founders can take it on as a paid "
                     f"custom job: <a href='/build-request?kind=fix&amp;case={_e(iid)}'>send them the details</a>.</p>")
    return "".join(parts) + "</div>"


def still_broken_html(inc: dict, project_id: str, csrf: str) -> str:
    """On a case the agent says it fixed: "Still broken?" with a screenshot and voice. The same case reopens with the agent's
    memory of what it tried; the second time, a stronger model takes over."""
    if not csrf or str(inc.get("status") or "") not in ("resolved", "pr_opened") or str(inc.get("live_result") or "").startswith("QUESTION: "):
        return ""
    iid = str(inc.get("id") or "")
    return (f"<details class='inc-broken'><summary>Still broken? Show the agent</summary>"
            f"<form method='post' action='/projects/{_e(project_id)}/incidents/{_e(iid)}/reply' data-media>"
            f"<input type='hidden' name='csrf' value='{_e(csrf)}'><input type='hidden' name='still_broken' value='1'>"
            f"<input type='hidden' name='next' value='/projects/{_e(project_id)}#case-{_e(iid)}'>"
            "<p class='muted'>Add a screenshot of what you see and say what is still wrong. The agent reopens this case, looks at your "
            "screenshot and at what it already tried, and does not repeat it.</p>"
            "<textarea name='text' rows='3' maxlength='1000' placeholder='What do you still see? (optional with a screenshot)'></textarea>"
            + media_input.inputs_html() +
            "<button class='button primary' type='submit'>Send to the agent</button></form></details>")


def render_board(project_id: str, incidents: list, mode: str, csrf: str = "") -> str:
    """The HTML that sits inside #incident-board. This exact string is also what the live endpoint returns."""
    if not incidents:
        return "<div class='empty'>No incidents yet. Once monitoring is installed, incidents will appear here.</div>"
    cards = []
    for inc in incidents:
        stage = stage_for(inc, mode)
        iid = str(inc.get("id") or "")
        pr_url = _safe_pr_url(inc.get("pr_url"))
        cause = " ".join(str(inc.get("root_cause") or "").split())
        cause = (cause[:160] + "…") if len(cause) > 160 else cause
        category = str(inc.get("category") or "").replace("_", " ")
        confidence = str(inc.get("confidence") or "")
        ist_ts = _fmt_ist(inc.get('last_seen'))
        ago_label = f"last seen {_e(_ago(inc.get('last_seen')))}"
        if ist_ts:
            ago_label = f"<span title='{_e(ist_ts)}'>{ago_label} ({_e(ist_ts)})</span>"
        meta = [("caught on push " + _e(str(inc.get("commit_sha") or "")[:7])) if inc.get("source") == "push"
                else f"{_e(inc.get('occurrences'))} events", ago_label]
        merged = int(inc.get("merged_count") or 0)
        if merged:
            meta.insert(0, f"<span class='pill tone-blue'>{merged} more report{'s' if merged != 1 else ''} merged into this case</span>")
        if stage.get("detail"):
            meta.insert(0, "<b>" + _e(stage["detail"][:200]) + "</b>")
        live = str(inc.get("live_result") or "")
        if live and not live.startswith(("NEEDS YOU", "BUDGET:")):
            meta.insert(0, "<b>" + _e(live.splitlines()[0][:220]) + "</b>")
        if category:
            meta.append(_e(category + (f" · {confidence} confidence" if confidence else "")))
        if inc.get("fx_path"):
            meta.append("tries: " + _e(inc["fx_path"]))
        buttons = []
        decide = choice_buttons_html(inc.get("fx_choice"), csrf, f"/projects/{project_id}#case-{iid}")
        if pr_url:
            buttons.append(f"<a class='button primary' href='{_e(pr_url)}' target='_blank' rel='noopener'>Open fix pull request</a>")
        buttons.append(f"<a class='button' href='/projects/{_e(project_id)}/incidents/{_e(iid)}'>Full details &amp; diff</a>")
        cards.append(
            f"<article class='inc' id='case-{_e(iid)}' data-active='{1 if stage['active'] else 0}'>"
            f"<details data-id='{_e(iid)}'><summary>"
            f"<div class='inc-top'><strong>{_e(_case_title(inc))}<span class='inc-id'>#{_e(iid[:8])}</span></strong>"
            f"<span class='pill tone-{_e(stage['tone'])}'>{_e(stage['headline'])}</span></div>"
            f"<div class='inc-sub muted'>{_e(cause) + '<br>' if cause else ''}{' · '.join(meta)}</div>"
            f"{_render_steps(stage['steps'])}"
            f"{decide}"
            f"{guide_html(inc, project_id, csrf, pr_url)}"
            f"<span class='hint'>Show report</span></summary>"
            f"<div class='inc-body'>{_render_report(inc, stage)}<div class='inc-actions'>{''.join(buttons)}</div></div>"
            f"</details>{diagnosis_box_html(inc, project_id, csrf)}{question_box_html(inc, project_id, csrf)}"
            f"{still_broken_html(inc, project_id, csrf)}</article>")
    return "".join(cards)


_STYLE = """<style>
.board-head{display:flex;justify-content:flex-end;margin:0 0 12px}
.live{font-size:13px;color:#8ce4c0;font-weight:600}.live[data-state='off']{color:#ffdc91}
.inc{border-radius:20px;margin:0 0 20px;overflow:hidden}
.inc[data-active='1']{box-shadow:0 18px 50px #0008,0 0 0 1px #9a4dff66,0 0 36px #9a4dff26}
.inc>details>summary{list-style:none;cursor:pointer;padding:24px 26px;display:block}
.inc>details>summary::-webkit-details-marker{display:none}
.inc-top{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
.inc-top strong{font-size:17px;line-height:1.4;min-width:0;overflow-wrap:anywhere;color:#fff}
.inc-top .inc-id{font-size:12.5px;font-weight:500;color:#8f84a3;margin-left:8px;font-family:Consolas,Menlo,monospace}
.inc-sub{margin:10px 0 4px;font-size:14px;line-height:1.6}
.inc-sub b{color:#efe7fa;font-weight:600}
@keyframes pulse{50%{opacity:.35}}
.hint{display:inline-flex;align-items:center;gap:6px;margin-top:18px;font-size:13.5px;font-weight:600;color:#ff7d6e}
.hint::after{content:"▾"}
.inc>details[open] .hint{display:none}
.inc-body{border-top:1px solid #ffffff12;padding:8px 26px 26px;background:#00000026}
.rp-sec h4{margin:22px 0 6px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#c9a15a}
.rp-sec p,.rp-sub p{margin:0;white-space:pre-wrap;color:#ded3ec;line-height:1.65;font-size:15px}
.rp-sub{margin-top:18px}.rp-sub summary{cursor:pointer;color:var(--muted);font-size:14px}
.inc-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}
.inc-decide{margin:18px 0 0;padding:16px 18px;border-radius:14px;background:#33270f66;border:1px solid #6b5320;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.inc-decide b{margin-right:6px;color:#f4dfae}
.inc-decide form,.inc-guide form{display:inline-flex;margin:0}
.inc-guide{margin:18px 0 0;display:flex;flex-wrap:wrap;gap:10px 12px;align-items:center}
.inc-guide .guide{flex:1 1 100%;margin:0;padding:18px 20px;border-radius:14px;border:1px solid #6b5320;background:#33270f66;color:#f6e9c8;font-size:15px;line-height:1.65}
.inc-guide .guide ol{margin:10px 0 14px 22px;padding:0}.inc-guide .guide li{margin:8px 0;padding-left:4px}
.inc-question{margin:0 26px 24px;padding:18px 20px;border-radius:14px;border:1px solid #9a4dff88;background:linear-gradient(160deg,#2a1645cc,#140b20e6);box-shadow:0 0 30px #9a4dff26}
.inc-question .q-head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.inc-question .q-badge{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#d9c6ff}
.inc-question .q-text{margin:10px 0 14px;font-size:16px;line-height:1.6;color:#fff;white-space:pre-wrap}
.inc-question textarea{min-height:96px}
.inc-diagnosis{margin:0 26px 24px;padding:18px 20px;border-radius:14px;border:1px solid #e3bd7488;background:linear-gradient(160deg,#2a1e0ccc,#140b20e6);box-shadow:0 0 30px #e3bd7422}
.inc-diagnosis .q-head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.inc-diagnosis .q-badge{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#f0d9a8}
.inc-diagnosis p{margin:8px 0;line-height:1.6}.inc-diagnosis code{overflow-wrap:anywhere}
.inc-diagnosis form{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:12px 0}
.inc-diagnosis .diag-yes label{display:flex;gap:8px;align-items:center;flex-basis:100%}
.inc-diagnosis details.diag-no form{display:block}.inc-diagnosis textarea{min-height:90px;width:100%}
.inc-question .q-actions{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin-top:12px}
.inc-broken{margin:0 26px 22px;border-radius:14px;border:1px solid #ffffff1a;background:#ffffff06}
.inc-broken>summary{padding:12px 16px;cursor:pointer;font-weight:650;color:#ff9c90;list-style:none}
.inc-broken>summary::-webkit-details-marker{display:none}
.inc-broken>form{padding:0 16px 16px}
.inc-broken textarea{min-height:84px}
@media(max-width:640px){.inc-broken{margin:0 18px 18px}}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:640px){.inc-question{margin:0 18px 18px}}
.inc-guide .guide-text{margin:8px 0 14px;white-space:normal}.inc-guide .guide-line{flex:1 1 280px;margin:0;color:var(--muted);font-size:14px;line-height:1.5}
@media(max-width:640px){.inc>details>summary{padding:18px}.inc-body{padding:6px 18px 20px}}
@media(prefers-reduced-motion:reduce){.steps .active .dot{animation:none}}
</style>"""


CHOICE_LABELS = (("auto", "Yes, go ahead", True), ("lower", "Use a cheaper mode", False),
                 ("higher", "Use a stronger mode", False), ("review", "Send to human review", False))


def choice_buttons_html(choice: dict | None, csrf: str, back: str) -> str:
    """The decision the agent is waiting for, answerable right on the case card (it used to be only on the Usage page, so the
    card said "Waiting for your decision" with nothing to click)."""
    if not choice or not csrf:
        return ""
    forms = "".join(
        f"<form method='post' action='/usage/choice' style='display:inline'>"
        f"<input type='hidden' name='csrf' value='{_e(csrf)}'><input type='hidden' name='choice_id' value='{_e(choice.get('id'))}'>"
        f"<input type='hidden' name='choice' value='{value}'><input type='hidden' name='next' value='{_e(back)}'>"
        f"<button class='button{' primary' if primary else ''}' type='submit'>{_e(text)}</button></form> "
        for value, text, primary in CHOICE_LABELS
        if not (value == "higher" and choice.get("tier") == "opus") and not (value == "lower" and choice.get("tier") == "haiku"))
    return f"<div class='inc-decide'><b>Your decision:</b> {forms}</div>"


def _post_button(action: str, csrf: str, label: str, *, primary: bool = False, danger: bool = False, extra: dict | None = None,
                 confirm: str = "") -> str:
    hidden = "".join(f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'>" for k, v in (extra or {}).items())
    cls = "button" + (" primary" if primary else "") + (" danger" if danger else "")
    onsubmit = f" data-confirm='{_e(confirm)}'" if confirm else ""
    return (f"<form method='post' action='{_e(action)}' style='display:inline'{onsubmit}><input type='hidden' name='csrf' value='{_e(csrf)}'>"
            f"{hidden}<button class='{cls}' type='submit'>{_e(label)}</button></form> ")


def guide_html(inc: dict, project_id: str, csrf: str, pr_url: str) -> str:
    """What the owner should do RIGHT NOW, in beginner words, with the button that does it. Shown on the case card itself."""
    if not csrf:
        return ""
    iid = str(inc.get("id") or "")
    base = f"/projects/{project_id}/incidents/{iid}"
    status = str(inc.get("status") or "")
    stage = str(inc.get("stage") or "")
    live = str(inc.get("live_result") or "")
    parts = []
    if status in ("diagnosing", "queued", "processing", "awaiting_choice"):
        parts.append(_post_button(base + "/pause", csrf, "Pause this case"))
    if status == "paused":
        parts.append("<p class='guide-line'>This case is paused. The agent does nothing (and spends nothing) until you resume it. "
                     "It continues where it stopped: earlier findings and edits are kept.</p>"
                     + _post_button(base + "/resume", csrf, "Resume (continues where it stopped)", primary=True))
    if live.startswith("BUDGET:"):
        parts.append("<div class='guide'><b>Keep going?</b><div class='guide-text'>" + _e(live[7:].strip()) + "</div>"
                     + _post_button(base + "/keepgoing", csrf, "Keep going", primary=True)
                     + _post_button(base + "/reply", csrf, "Send to human review", extra={"text": "Please send this case to human review."})
                     + "</div>")
    elif stage == "needs_you" or live.startswith("NEEDS YOU"):
        body = live.split(chr(10), 1)[1].strip() if chr(10) in live else live
        parts.append("<div class='guide'><b>What you need to do</b><div class='guide-text'>" + _e(body).replace(chr(10), "<br>") + "</div>"
                     + _post_button(base + "/reply", csrf, "I did it, check again", primary=True, extra={"text": "I did the steps. Please check again."})
                     + (_post_button(base + "/escalate", csrf, "Not right? Let a stronger AI look")
                        + "<p class='guide-line'>If you think this IS a problem in your code, the next stronger model reads everything "
                          "again with what was found so far (costs a little more).</p>" if inc.get("fx_can_escalate") else "")
                     + "</div>")
    elif pr_url and status in ("diagnosed", "pr_opened", "needs_human") and stage not in ("verifying", "verified", "reverted"):
        parts.append(
            "<div class='guide'><b>A fix is ready. What to do now (takes about 2 minutes):</b><ol>"
            f"<li>Click <a href='{_e(pr_url)}' target='_blank' rel='noopener'>Open fix pull request</a>. It opens GitHub in a new tab.</li>"
            "<li>Read the short explanation at the top. To see exactly what changed, click the <b>Files changed</b> tab.</li>"
            "<li>Scroll down and click the green <b>Merge pull request</b> button, then <b>Confirm merge</b>. "
            "(If the button is grey and says there are conflicts, do not merge: press <b>Send to human review</b> on this page or reply here.)</li>"
            "<li>Your host (Vercel, Netlify, Render ...) puts the change live by itself in 1 to 3 minutes. You can watch it on your host's "
            "<b>Deployments</b> page.</li>"
            "<li>Come back here and press the button below. The agent opens your live site and tells you if the problem is gone.</li></ol>"
            + _post_button(base + "/merged", csrf, "I merged it, check my site", primary=True) + "</div>")
    if status in ("needs_human", "resolved", "diagnosed") and not live.startswith(("NEEDS YOU", "BUDGET:")):
        parts.append(_post_button(base + "/rerun", csrf, "Run again",
                                  confirm="The agent works on this case again with your original request and everything found so far. Continue?")
                     + "<span class='guide-line'> Same request, no need to type it again; it starts from what was already found.</span>")
    if status == "resolved" and stage in ("pushed", "verified", "verifying", "merged", "resolved") and (inc.get("pr_url") or "pushed" in stage
                                                                                                    or stage in ("verified", "verifying")):
        parts.append(_post_button(base + "/undo", csrf, "Undo this fix", danger=True,
                                  confirm="This puts the changed files back exactly as they were before the fix, with a new commit. Continue?"))
    return f"<div class='inc-guide'>{''.join(parts)}</div>" if parts else ""


def render_board_section(project_id: str, incidents: list, mode: str, csrf: str = "") -> str:
    """The block the project page embeds: styles, live indicator, the board, and the same-origin script."""
    pid = _e(project_id)
    return (f"{_STYLE}<div class='board-head'><span id='live-dot' class='live' data-state='on'>● Live</span></div>"
            f"<div id='incident-board' data-live='/projects/{pid}/incidents/live'>{render_board(project_id, incidents, mode, csrf)}</div>"
            f"<script src='/assets/live.js?v={LIVE_JS_VERSION}' defer></script>")


LIVE_JS = """(function () {
  // Any element with data-live="<url>" re-fetches its HTML every 5 seconds (15 s after a failed fetch).
  var boxes = document.querySelectorAll('[data-live]');
  var dot = document.getElementById('live-dot');
  function setDot(ok) {
    if (!dot) { return; }
    dot.setAttribute('data-state', ok ? 'on' : 'off');
    dot.textContent = ok ? '\\u25CF Live' : '\\u25CF Reconnecting\\u2026';
  }
  function watch(box) {
    var url = box.getAttribute('data-live');
    var last = null, failures = 0, timer = null;
    function openIds() {
      var ids = {}, nodes = box.querySelectorAll('details[data-id][open]');
      for (var i = 0; i < nodes.length; i++) { ids[nodes[i].getAttribute('data-id')] = true; }
      return ids;
    }
    function reopen(ids) {
      var nodes = box.querySelectorAll('details[data-id]');
      for (var i = 0; i < nodes.length; i++) {
        if (ids[nodes[i].getAttribute('data-id')]) { nodes[i].setAttribute('open', ''); }
      }
    }
    function isActive() { return !!box.querySelector('[data-active="1"]'); }
    function typing() {
      var a = document.activeElement;
      if (a && box.contains(a) && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName)) { return true; }
      var fields = box.querySelectorAll('textarea');
      for (var i = 0; i < fields.length; i++) { if (fields[i].value.trim()) { return true; } }
      return false;
    }
    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(tick, failures ? 15000 : 5000);
    }
    function tick() {
      if (document.hidden) { schedule(); return; }
      fetch(url, { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) {
          if (r.status === 401) { window.location.href = '/login'; return null; }
          if (!r.ok) { throw new Error('bad status'); }
          return r.text();
        })
        .then(function (text) {
          if (text === null) { return; }
          failures = 0; setDot(true);
          if (typing()) { return; }                       // never wipe an answer someone is writing
          if (text !== last) {
            var ids = openIds();
            box.innerHTML = text;
            reopen(ids);
            last = text;
          }
        })
        .catch(function () { failures++; setDot(false); })
        .then(schedule);
    }
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { clearTimeout(timer); tick(); }
    });
    schedule();
  }
  for (var i = 0; i < boxes.length; i++) { watch(boxes[i]); }
})();
"""
