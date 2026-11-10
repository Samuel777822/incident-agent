"""Small, friendly UI pieces for v3: the 'how the agent works' flow diagram, the 'tell the agent what's broken' card,
the 'new feature' banner and the CSS that turns every step list into arrow-connected chips."""
from __future__ import annotations

import html

FLOW_NODES = [
    ("1", "Connected", "Your repo is private and linked"),
    ("2", "Watching", "Every push, plus a daily visit to your site"),
    ("3", "Error found", "A request fails, a button is dead"),
    ("4", "AI writes a fix", "Cheapest model first"),
    ("5", "Sandbox test", "Built and clicked in a safe box"),
    ("6", "GitHub test", "Your own tests must pass"),
    ("7", "Pushed", "Straight to your branch"),
    ("8", "Live check", "We open your site again"),
]


def flow_diagram_html() -> str:
    nodes = "".join(
        f"<li class='flow-node'><span class='flow-num'>{n}</span><b>{html.escape(t)}</b><small>{html.escape(d)}</small></li>"
        for n, t, d in FLOW_NODES)
    return ("<section class='flow-card'><div class='row'><h3>How Agent Daemon looks after your site</h3></div>"
            f"<ol class='flow'>{nodes}</ol>"
            "<div class='flow-loop'><span class='loop-arrow'>↩</span> If the <b>sandbox</b> test fails, the exact error goes back to the AI "
            "and, when needed, a stronger AI model takes over. If <b>GitHub's</b> test fails, the agent tries again; after 3 failed GitHub "
            "rounds it opens a pull request for <b>you</b> to review instead of pushing. Problems with the same cause are handled as "
            "<b>one case</b>: one fix, however many reports.</div></section>")


def report_card_html(project_id: str, csrf: str) -> str:
    pid, token = html.escape(project_id), html.escape(csrf)
    return ("<article class='card report-card'><div class='row'><h3>Tell the agent what's broken</h3><span class='pill green'>New</span></div>"
            "<p class='muted'>Something is wrong, or you want a small change? Describe it in your own words, for example "
            "<i>“Isaiah chapter 1 does not load”</i> or <i>“the Send button does nothing”</i>. The agent opens your live site, looks at "
            "your code, finds the cause, fixes it, tests it, pushes it and then checks your site again. If it truly needs something "
            "from you, it asks one clear question.</p>"
            f"<form method='post' action='/projects/{pid}/report' data-once><input type='hidden' name='csrf' value='{token}'>"
            "<textarea name='text' rows='3' maxlength='1500' required placeholder='What is not working, and where?'></textarea>"
            "<div class='field'><label>Page where it happens (optional)</label>"
            "<input name='page' maxlength='300' placeholder='https://your-site.com/isaiah/1 or /isaiah/1'></div>"
            "<button class='button primary' type='submit'>Send to the agent</button></form></article>")


def new_feature_banner_html() -> str:
    return ("<div class='new-banner'><span class='pill green'>New</span> <b>Tell the agent what's broken.</b> "
            "If something on your site is wrong and the agent has not caught it yet, open the project and describe the problem. "
            "The agent will look at your code and fix it.</div>")


def flash_html(code: str) -> str:
    msgs = {"1": ("green", "Sent. The agent is opening your site and reading your code now. Watch the case in “Bugs and fixes” below: "
                           "after a fix is pushed it says “Pushed, check again in 30 seconds to a minute”, then “Verified” once it has "
                           "checked your live site."),
            "dup": ("amber", "Already working on this: you sent the same report a moment ago. It is one case, so nothing is paid twice."),
            "joined": ("green", "Sent. This looks like the same cause as a problem the agent is already fixing, so your report was added "
                                "to that case (one fix, nothing paid twice)."),
            "site": ("green", "Saved. The agent now opens this address to see problems for itself, and audits it in the next minute."),
            "badsite": ("amber", "That address could not be used. Enter the public address of your site, for example https://your-site.com"),
            "short": ("amber", "Please describe the problem in a few more words."),
            "limit": ("amber", "You sent 5 reports in the last hour. Please wait a little; the agent is still working on them.")}
    tone, text = msgs.get(code, ("", ""))
    return f"<div class='pill {tone}'>{html.escape(text)}</div>" if text else ""


FLOW_CSS = """
/* ---- v3: arrows, flow diagram, report card ---- */
:is(#incident-board,#agent-live) .steps{display:flex;flex-wrap:wrap;gap:10px 26px;list-style:none;margin:14px 0 0;padding:0;align-items:center}
:is(#incident-board,#agent-live) .steps li{position:relative;display:flex;align-items:center;gap:8px;padding:7px 13px;border-radius:999px;background:#ffffff0a;border:1px solid var(--line);font-size:13px;color:#8a96ad}
:is(#incident-board,#agent-live) .steps li:not(:last-child)::after{content:"\\2192";position:absolute;right:-21px;top:50%;transform:translateY(-52%);color:#6b7893;font-size:16px}
:is(#incident-board,#agent-live) :is(#incident-board,#agent-live) .steps .dot{width:9px;height:9px;border-radius:50%;border:2px solid #56627a;flex:none}
:is(#incident-board,#agent-live) .steps .done{color:#d5efe4;border-color:#2c6b57;background:#55d6a115}.steps .done .dot{background:#55d6a1;border-color:#55d6a1}
:is(#incident-board,#agent-live) .steps .active{color:#ffeab5;border-color:#a47e2e;background:#f0c36b18}.steps .active .dot{background:#f0c36b;border-color:#f0c36b;animation:pulse 1.2s ease-in-out infinite}
:is(#incident-board,#agent-live) .steps .fail{color:#ffc2c2;border-color:#8a3342;background:#ff7a8a14}.steps .fail .dot{background:#ff7a8a;border-color:#ff7a8a}
.flow-card{background:linear-gradient(145deg,#141e33,#101729);border:1px solid var(--line);border-radius:18px;padding:20px 22px;margin:18px 0}
.flow-card h3{margin:0 0 12px}
.flow{list-style:none;display:flex;flex-wrap:wrap;gap:12px 30px;margin:0;padding:0}
.flow-node{position:relative;display:flex;flex-direction:column;gap:2px;min-width:118px;max-width:150px;padding:12px 14px;border-radius:14px;background:#ffffff0a;border:1px solid var(--line)}
.flow-node:not(:last-child)::after{content:"\\2192";position:absolute;right:-24px;top:50%;transform:translateY(-55%);color:var(--green);font-size:20px}
.flow-num{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--green);color:#06120d;font-weight:800;font-size:12px;margin-bottom:4px}
.flow-node small{color:var(--muted);font-size:12px;line-height:1.35}
.flow-loop{margin-top:14px;padding:10px 14px;border-radius:12px;border:1px dashed #a47e2e;background:#f0c36b10;color:#ffe3a0;font-size:13px}
.loop-arrow{font-size:18px;margin-right:6px}
.report-card textarea{width:100%;margin:10px 0;padding:12px 13px;border-radius:10px;border:1px solid #34425e;background:#0b1324;color:var(--text);font:inherit;resize:vertical}
.report-card textarea:focus{border-color:var(--blue);outline:none;box-shadow:0 0 0 3px #75a7ff20}
.new-banner{margin:14px 0;padding:12px 16px;border-radius:14px;border:1px solid #2c6b57;background:linear-gradient(90deg,#55d6a118,#55d6a105);color:#d5efe4}
@media(max-width:640px){.flow{flex-direction:column;gap:22px}.flow-node{max-width:none}.flow-node:not(:last-child)::after{content:"\\2193";right:auto;left:50%;top:auto;bottom:-24px;transform:translateX(-50%)}}
@media(prefers-reduced-motion:reduce){:is(#incident-board,#agent-live) .steps .active .dot{animation:none}}
"""
