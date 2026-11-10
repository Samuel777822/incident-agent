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
        if live:
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
            f"<div class='inc-top'><strong>Incident {_e(iid[:8])}</strong>"
            f"<span class='pill tone-{_e(stage['tone'])}'>{_e(stage['headline'])}</span></div>"
            f"<div class='inc-sub muted'>{_e(cause) + '<br>' if cause else ''}{' · '.join(meta)}</div>"
            f"{_render_steps(stage['steps'])}"
            f"{decide}"
            f"<span class='hint'>Show report</span></summary>"
            f"<div class='inc-body'>{_render_report(inc, stage)}<div class='inc-actions'>{''.join(buttons)}</div></div>"
            f"</details></article>")
    return "".join(cards)


_STYLE = """<style>
.board-head{display:flex;justify-content:flex-end;margin:-6px 0 10px}
.live{font-size:12px;color:#8ce4c0}.live[data-state='off']{color:#ffdc91}
.inc{background:linear-gradient(145deg,#171027,#0e0a18);border:1px solid var(--line);border-radius:20px;margin:0 0 16px;overflow:hidden;box-shadow:0 12px 40px #0004}
.inc[data-active='1']{border-color:#3b5a99;box-shadow:0 12px 40px #1b3a7a40}
.inc>details>summary{list-style:none;cursor:pointer;padding:18px 20px;display:block}
.inc>details>summary::-webkit-details-marker{display:none}
.inc-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.inc-sub{margin:6px 0 12px;font-size:13px}
.pill.tone-green{color:#8ce4c0;background:#14392f}.pill.tone-amber{color:#ffdc91;background:#3a301b}
.pill.tone-red{color:#ffb3b3;background:#3d1c24}.pill.tone-blue{color:#d6c8ff;background:#2a1d4a}.pill.tone-muted{color:#b8c9df;background:#1b2d43}
@keyframes pulse{50%{opacity:.35}}
.hint{display:inline-block;margin-top:12px;font-size:12px;color:var(--blue)}
.inc>details[open] .hint{display:none}
.inc-body{border-top:1px solid var(--line);padding:6px 20px 18px}
.rp-sec h4{margin:16px 0 4px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--green)}
.rp-sec p,.rp-sub p{margin:0;white-space:pre-wrap;color:#d7e2f5}
.rp-sub{margin-top:14px}.rp-sub summary{cursor:pointer;color:var(--muted);font-size:13px}
.inc-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.inc-decide{margin:12px 0 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
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
