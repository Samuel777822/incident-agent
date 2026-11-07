"""Animated SVG flow diagrams for the architecture pages (no libraries, no external assets).

  general_diagram()          every process and how it connects: connect -> public-repo check -> install monitor ->
                             heartbeat -> error detection -> sandbox -> diagnosis -> model adapters -> fix -> tests -> PR,
                             plus the push guard and the first scan. Shown to everyone (/how-it-works) and to admins.
  model_diagram(cfg)         the model-adapter layer: router -> guard -> adapters -> providers -> normalizer, the automatic
                             fallback policy and what the router weighs. Admins only (/admin/architecture).

Each diagram is drawn twice: a wide layout for desktops/tablets and a tall one for phones (CSS picks one). Arrows show the
direction of data with an animated flowing dash, nodes glow, every node is a button that explains itself, and
prefers-reduced-motion switches the animation off.
"""
from __future__ import annotations

import html

E = lambda v: html.escape(str(v if v is not None else ""), quote=True)

C = {"violet": "#b06cff", "crimson": "#ff5a6a", "cyan": "#4fd1ff", "green": "#62e6a4", "amber": "#ffc857", "magenta": "#ff4fd8",
     "red": "#ff6b6b", "muted": "#b9aecb"}

CSS = """
.dg{position:relative;margin:14px 0 6px;border-radius:18px;padding:10px;background:radial-gradient(120% 90% at 0% 0%,#2a0f2a 0,transparent 55%),
  radial-gradient(120% 90% at 100% 0%,#1b1040 0,transparent 55%),#0a0612;border:1px solid #3a2338;box-shadow:inset 0 0 60px #9a4dff14}
.dg svg{display:block;width:100%;height:auto;font-family:"Instrument Sans",Inter,ui-sans-serif,system-ui,sans-serif}
.dg .dg-mobile{display:none}
@media(max-width:760px){.dg .dg-desk{display:none}.dg .dg-mobile{display:block}.dg{padding:6px}}
.dg .edge{fill:none;stroke-width:2.4;stroke-linecap:round;stroke-dasharray:7 9;animation:dg-flow 1.1s linear infinite}
.dg .edge.slow{animation-duration:2.2s}.dg .edge.solid{stroke-dasharray:none;animation:none;opacity:.35}
.dg .edge.dashed{stroke-dasharray:4 7}
.dg .halo{fill:none;stroke-width:7;opacity:.16;stroke-linecap:round}
@keyframes dg-flow{to{stroke-dashoffset:-32}}
.dg .dn{cursor:pointer;outline:none}
.dg .dn rect.box{transition:filter .2s,stroke-width .2s}
.dg .dn:hover rect.box,.dg .dn:focus-visible rect.box,.dg .dn.sel rect.box{stroke-width:3.2;filter:brightness(1.35) drop-shadow(0 0 9px rgba(255,255,255,.35))}
.dg .dn .pulse{animation:dg-pulse 3.2s ease-in-out infinite;transform-box:fill-box;transform-origin:center}
@keyframes dg-pulse{0%,100%{opacity:.25}50%{opacity:.8}}
.dg text{fill:#f2edf7}.dg .t{font-weight:700;font-size:15px}.dg .s{font-size:11.5px;fill:#c9bedb}.dg .lbl{font-size:11px;font-weight:600;
  paint-order:stroke;stroke:#0a0612;stroke-width:4px;stroke-linejoin:round}
.dg .lane{font-size:12px;letter-spacing:.14em;text-transform:uppercase;fill:#a99dbb;font-weight:700}
.dg .chk{font-size:12px;fill:#e9e4ee}.dg .ico{font-size:20px}
.dg-detail{background:linear-gradient(145deg,#1a0f26,#0f0817);border:1px solid #5b2a5a;border-radius:14px;padding:14px 16px;margin:10px 0 18px;min-height:64px}
.dg-detail h3{margin:0 0 4px;font-family:var(--serif)}.dg-detail p{margin:0;color:#d3c9e0}
.dg-legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin:6px 2px 0;font-size:13px;color:#cdbfe0}
.dg-legend i{display:inline-block;width:26px;height:0;border-top:3px solid;vertical-align:middle;margin-right:6px}
.dg-legend i.d{border-top-style:dashed}
@media(prefers-reduced-motion:reduce){.dg .edge{animation:none}.dg .dn .pulse{animation:none}}
"""

SCRIPT = """(function(){document.querySelectorAll('.dg-wrap').forEach(function(w){var d=w.querySelector('.dg-detail');if(!d)return;
var btn=w.querySelector('.dg-play'),narr=w.querySelector('.dg-narr'),timer=null,i=0;
function show(n){w.querySelectorAll('.dn').forEach(function(x){x.classList.toggle('sel',x.getAttribute('data-k')===n.getAttribute('data-k'));});
var t=document.createElement('h3');t.textContent=n.getAttribute('data-title');var p=document.createElement('p');p.textContent=n.getAttribute('data-text');d.innerHTML='';d.appendChild(t);d.appendChild(p);}
w.querySelectorAll('.dn').forEach(function(n){n.addEventListener('click',function(){stop();show(n);});n.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();stop();show(n);}});});
function visible(){var svgs=[].slice.call(w.querySelectorAll('.dg-desk,.dg-mobile')).filter(function(x){return x.offsetParent!==null;});var root=svgs[0]||w;
var order=(w.getAttribute('data-order')||'').split(',');return order.map(function(k){return root.querySelector('.dn[data-k="'+k+'"]');}).filter(Boolean);}
function stop(){if(timer){clearInterval(timer);timer=null;}if(btn)btn.textContent='▶ Play the flow';}
function step(){var nodes=visible();if(i>=nodes.length){stop();if(narr)narr.textContent='Done: the fixed version is on GitHub.';return;}
var n=nodes[i];show(n);if(narr)narr.textContent='Step '+(i+1)+' of '+nodes.length+': '+n.getAttribute('data-title');
if(window.innerWidth<760&&n.scrollIntoView)n.scrollIntoView({block:'center',behavior:'smooth'});i++;}
if(btn)btn.addEventListener('click',function(){if(timer){stop();return;}i=0;btn.textContent='■ Stop';step();timer=setInterval(step,1700);});});})();"""


def _defs(prefix: str) -> str:
    markers = "".join(
        f"<marker id='{prefix}-a-{name}' viewBox='0 0 10 10' refX='8.5' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path d='M0,0 L10,5 L0,10 z' fill='{col}'/></marker>" for name, col in C.items())
    grads = "".join(f"<linearGradient id='{prefix}-g-{name}' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='{col}' stop-opacity='.18'/>"
                    f"<stop offset='1' stop-color='#0d0716' stop-opacity='.92'/></linearGradient>" for name, col in C.items())
    # ids carry the diagram prefix: a hidden (display:none) desktop SVG must never own the defs the phone SVG uses
    return (f"<defs><filter id='{prefix}-glow' x='-30%' y='-30%' width='160%' height='160%'><feGaussianBlur stdDeviation='4' result='b'/>"
            "<feMerge><feMergeNode in='b'/><feMergeNode in='SourceGraphic'/></feMerge></filter>"
            f"{markers}{grads}</defs>")


def _node(prefix, key, x, y, w, h, color, icon, title, sub="", detail="", checks=(), dashed=False, title_size=15) -> str:
    col = C[color]
    lines = []
    ty = y + 30
    room = w - 54                                           # text starts after the icon; keep a right margin
    title_size = round(min(title_size, room / max(1, len(title) * 0.54)), 1)
    lines.append(f"<text class='ico' x='{x + 14}' y='{ty + 2}'>{E(icon)}</text>")
    lines.append(f"<text class='t' x='{x + 44}' y='{ty}' style='font-size:{title_size}px'>{E(title)}</text>")
    if sub:
        for i, part in enumerate(sub.split("\n")):
            size = round(min(11.5, room / max(1, len(part) * 0.56)), 1)
            lines.append(f"<text class='s' x='{x + 44}' y='{ty + 19 + i * 15}' style='font-size:{size}px'>{E(part)}</text>")
    for i, item in enumerate(checks):
        cy = y + 76 + i * 23
        lines.append(f"<circle cx='{x + 24}' cy='{cy - 4}' r='8' fill='{C['green']}' opacity='.9'/>"
                     f"<path d='M{x + 20},{cy - 4} l3,3 l6,-7' stroke='#0a0612' stroke-width='2.2' fill='none'/>"
                     f"<text class='chk' x='{x + 40}' y='{cy}'>{E(item)}</text>")
    dash = " stroke-dasharray='7 6'" if dashed else ""
    return (f"<g class='dn' tabindex='0' role='button' data-k='{E(key)}' data-title='{E(title)}' data-text='{E(detail or sub)}' "
            f"aria-label='{E(title)}: {E(detail or sub)}'>"
            f"<rect class='pulse' x='{x - 3}' y='{y - 3}' width='{w + 6}' height='{h + 6}' rx='17' fill='none' stroke='{col}' stroke-width='1' filter='url(#{prefix}-glow)'/>"
            f"<rect class='box' x='{x}' y='{y}' width='{w}' height='{h}' rx='14' fill='url(#{prefix}-g-{color})' stroke='{col}' stroke-width='2'{dash} filter='url(#{prefix}-glow)'/>"
            + "".join(lines) + "</g>")


def _edge(prefix, d, color, label="", lx=0, ly=0, style="", anchor="middle") -> str:
    col = C[color]
    lab = (f"<text class='lbl' x='{lx}' y='{ly}' text-anchor='{anchor}' fill='{col}'>{E(label)}</text>" if label else "")
    return (f"<path class='halo' d='{d}' stroke='{col}'/>"
            f"<path class='edge {style}' d='{d}' stroke='{col}' marker-end='url(#{prefix}-a-{color})'/>{lab}")


def _svg(prefix, vb, body, title) -> str:
    return (f"<svg viewBox='{vb}' role='img' aria-label='{E(title)}' xmlns='http://www.w3.org/2000/svg'>"
            f"<title>{E(title)}</title>{_defs(prefix)}{body}</svg>")


# ====================================================================================================== general architecture
G_NODES = {
    "connect": ("violet", "🔗", "Connect project", "repo + token", "You paste your GitHub repository and a token. That is all you do."),
    "gate": ("crimson", "🔒", "Public-repo check", "asks GitHub", "We ask GitHub whether the repository is private. "
             "Public repositories get nothing installed, because anyone could read the monitor's connection details."),
    "private": ("amber", "🧭", "Make it private", "step-by-step screen", "A simple screen shows how to make the repository private "
                "(computer and phone). The button 'I've made it private, install now' asks GitHub again."),
    "install": ("violet", "📦", "Install monitor", "1 PR, merged for you", "We detect every part of the repo (Python, Node.js, "
                "TypeScript, HTML/JS, React, Next.js, mixed repos), add the right monitor to each, and merge the pull request."),
    "monitors": ("cyan", "🛰", "Monitor in your app", "Python, Node, web", "Each monitor catches crashes, unhandled promise "
                 "rejections, console errors and failed API calls (for example a retired AI model), with the full message."),
    "heartbeat": ("cyan", "💓", "Heartbeat · 30 s", "id · status · time", "Every monitor checks in every 30 seconds, so a "
                  "monitor that stops is never silent."),
    "backend": ("cyan", "🛡", "Agent Daemon", "/heartbeat · /ingest", "Records every check-in (shown as 'last check-in at …') and "
                "groups error reports into incidents."),
    "offline": ("red", "🚨", "Monitor offline", "silent for 2 min", "If check-ins stop (or never start) the project shows "
                "'Monitor offline' / 'Never checked in' and the owner gets one email with what to do."),
    "push": ("violet", "⤴", "Push · first scan", "webhook / connect", "Every push to your branch, and one scan of the existing "
             "code right after you connect, even if you never push."),
    "pushguard": ("cyan", "🧪", "Push guard", "build · test · scan", "The commit is installed, built, tested and started "
                  "in a sandbox, and the code is scanned for retired AI models."),
    "detect": ("crimson", "⚡", "Error detected", "incident opened", "A red push check, a scan finding or a live error report "
               "becomes an incident and goes to the fix pipeline."),
    "sandbox": ("violet", "📥", "Sandbox", "download · reproduce", "Your repository is downloaded into a fresh, isolated "
                "container. Your code only ever runs there."),
    "diagnose": ("magenta", "🔍", "Diagnosis", "error + code", "The error report and the relevant files are read to "
                 "find the cause."),
    "router": ("magenta", "🧠", "Model adapters", "router picks the AI", "The router chooses an economical AI mode; adapters "
               "talk to the providers. A retired AI model in YOUR app is fixed without AI at all."),
    "fix": ("green", "🩹", "Fix", "small, safe patch", "At most 3 files and 40 lines; never tests, CI, dependencies or secrets."),
    "tests": ("green", "✅", "Tests", "same check must pass", "Your tests (or build / lint / parse checks) run on the patched code. "
              "Not green? Nothing is pushed and the agent tries again."),
    "pr": ("green", "🚀", "Pull request", "merged when proven", "A branch agent-daemon/fix-… and a pull request. Auto mode merges it "
           "once proven. Visibility is re-checked before every commit we make."),
}

G_EDGES_LEGEND = [("violet", "", "Setup"), ("cyan", "", "Monitoring data"), ("magenta", "", "AI request"),
                  ("green", "", "Fix and proof"), ("amber", "d", "Waiting / retry"), ("red", "d", "Alert")]


def _legend(items) -> str:
    return "<div class='dg-legend'>" + "".join(f"<span><i class='{cls}' style='border-color:{C[c]}'></i>{E(t)}</span>" for c, cls, t in items) + "</div>"


def _general_desktop() -> str:
    p, W, H = "gd", 176, 84
    xs = [20, 230, 440, 650, 860, 1070]
    y1, y2, y3 = 72, 336, 600
    pos = {"connect": (xs[0], y1), "gate": (xs[1], y1), "install": (xs[2], y1), "monitors": (xs[3], y1), "heartbeat": (xs[4], y1),
           "backend": (xs[5], y1), "private": (xs[1], 196), "push": (xs[0], y2), "pushguard": (xs[1], y2), "detect": (xs[3], y2),
           "offline": (xs[5], y2), "sandbox": (xs[0], y3), "diagnose": (xs[1], y3), "router": (xs[2], y3), "fix": (xs[3], y3),
           "tests": (xs[4], y3), "pr": (xs[5], y3)}
    body = ["<text class='lane' x='20' y='50'>1 · Connect (once)</text>", "<text class='lane' x='20' y='314'>2 · Watch (always on)</text>",
            "<text class='lane' x='20' y='578'>3 · Fix (when something breaks)</text>"]
    e = []
    r = lambda k: pos[k][0] + W
    cy = lambda k: pos[k][1] + H / 2
    for a, b, col, lab in (("connect", "gate", "violet", ""), ("install", "monitors", "violet", ""),
                           ("monitors", "heartbeat", "cyan", ""), ("heartbeat", "backend", "cyan", ""),
                           ("push", "pushguard", "violet", ""), ("diagnose", "router", "magenta", "AI"),
                           ("router", "fix", "magenta", ""), ("fix", "tests", "green", ""), ("tests", "pr", "green", "")):
        d = f"M{r(a) + 2},{cy(a)} L{pos[b][0] - 4},{cy(b)}"
        e.append(_edge(p, d, col, lab, (r(a) + pos[b][0]) / 2, cy(a) - 8))
    e.append(_edge(p, f"M{r('gate') + 2},{cy('gate')} L{pos['install'][0] - 4},{cy('install')}", "green", "✓ private",
                   (r("gate") + pos["install"][0]) / 2, y1 - 8))
    gx = pos["gate"][0]
    e.append(_edge(p, f"M{gx + 52},{y1 + H + 2} L{gx + 52},{196 - 4}", "amber", "public", gx + 46, 178, "dashed", "end"))
    e.append(_edge(p, f"M{gx + 120},{196 - 2} L{gx + 120},{y1 + H + 4}", "amber", "re-check", gx + 126, 178, "dashed", "start"))
    bx = pos["backend"][0]
    e.append(_edge(p, f"M{bx + 40},{y1 + H + 2} L{bx + 40},{270} L{pos['detect'][0] + 120},{270} L{pos['detect'][0] + 120},{y2 - 4}",
                   "cyan", "error reports", bx - 120, 262))
    e.append(_edge(p, f"M{bx + 140},{y1 + H + 2} L{bx + 140},{y2 - 4}", "red", "missed check-ins", bx + 132, 240, "dashed", "end"))
    e.append(_edge(p, f"M{r('pushguard') + 2},{cy('pushguard')} L{pos['detect'][0] - 4},{cy('detect')}", "crimson",
                   "red check · retired model", (r("pushguard") + pos["detect"][0]) / 2, cy("pushguard") - 9))
    dx = pos["detect"][0]
    e.append(_edge(p, f"M{dx + 60},{y2 + H + 2} L{dx + 60},{530} L{pos['sandbox'][0] + 86},{530} L{pos['sandbox'][0] + 86},{y3 - 4}",
                   "crimson", "incident queue", dx - 60, 522))
    e.append(_edge(p, f"M{r('sandbox') + 2},{cy('sandbox')} L{pos['diagnose'][0] - 4},{cy('diagnose')}", "violet", "",
                   0, 0))
    tx, rx = pos["tests"][0], pos["router"][0]
    e.append(_edge(p, f"M{tx + 86},{y3 - 2} L{tx + 86},{566} L{rx + 120},{566} L{rx + 120},{y3 - 4}", "amber",
                   "not green → try again", (tx + rx) / 2 + 100, 560, "dashed"))
    ddx, fx = pos["diagnose"][0], pos["fix"][0]
    e.append(_edge(p, f"M{ddx + 86},{y3 + H + 2} L{ddx + 86},{730} L{fx + 86},{730} L{fx + 86},{y3 + H + 4}", "green",
                   "retired AI model → swap the model id (no AI tries)", (ddx + fx) / 2 + 86, 748, "dashed"))
    px = pos["pr"][0]
    body.append(f"<text class='s' x='{px + W}' y='{y3 + H + 22}' text-anchor='end'>🔒 “private?” re-checked before every commit</text>")
    body.append(f"<text class='s' x='{pos['monitors'][0] + 86}' y='{y1 + H + 22}' text-anchor='middle'>catches crashes · console · failed API calls</text>")
    body += e
    for k, (x, y) in pos.items():
        col, ico, t, s, d = G_NODES[k]
        body.append(_node(p, k, x, y, W, H if k != "private" else 64, col, ico, t, s, d, dashed=k in ("private", "offline")))
    return _svg(p, "0 0 1262 770", "".join(body), "Agent Daemon general architecture")


def _vertical(prefix: str, steps: list, width: int = 380, title: str = "") -> str:
    """Phone layout: one column, arrows down, side notes (branches) as dashed boxes with a labelled connector.
    When a note sits between two steps, the main arrow runs down the right-hand side, past the note."""
    body, y, prev_bottom, noted = [], 16, None, False
    x, w = 24, width - 48
    for step in steps:
        kind = step[0]
        if kind == "lane":
            y += 8
            body.append(f"<text class='lane' x='{x}' y='{y + 14}'>{E(step[1])}</text>")
            y += 26
            continue
        if kind == "note":
            _k, key, col, ico, t, s, d, lab = step
            body.append(_edge(prefix, f"M{x + 34},{y - 6} L{x + 34},{y + 14}", col, lab, x + 44, y + 9, "dashed", "start"))
            body.append(_node(prefix, key, x + 18, y + 16, w - 74, 58, col, ico, t, s, d, dashed=True, title_size=14))
            y += 88
            noted = True
            continue
        _k, key, col, ico, t, s, d = step
        h = 66
        if prev_bottom is not None:
            lane_x = x + w - 26 if noted else x + w / 2
            body.append(_edge(prefix, f"M{lane_x},{prev_bottom + 2} L{lane_x},{y - 4}", col))
        body.append(_node(prefix, key, x, y, w, h, col, ico, t, s, d))
        prev_bottom, noted = y + h, False
        y += h + 30
    return _svg(prefix, f"0 0 {width} {y}", "".join(body), title)


def _general_mobile() -> str:
    n = lambda k: ("node", k) + G_NODES[k]
    note = lambda k, lab: ("note", k) + G_NODES[k] + (lab,)
    steps = [("lane", "1 · Connect (once)"), n("connect"), n("gate"), note("private", "if public"), n("install"), n("monitors"),
             n("heartbeat"), n("backend"), note("offline", "no check-in"), ("lane", "2 · Watch (always on)"), n("push"), n("pushguard"),
             n("detect"), ("lane", "3 · Fix (when something breaks)"), n("sandbox"), n("diagnose"), n("router"), n("fix"), n("tests"),
             n("pr")]
    return _vertical("gm", steps, title="Agent Daemon general architecture (phone layout)")


G_ORDER = ["connect", "gate", "private", "install", "monitors", "heartbeat", "backend", "offline", "push", "pushguard", "detect",
           "sandbox", "diagnose", "router", "fix", "tests", "pr"]


def general_diagram() -> str:
    return (f"<div class='dg-wrap' data-order='{','.join(G_ORDER)}'><div class='arch-controls'><button class='button primary dg-play' "
            f"type='button'>▶ Play the flow</button><span class='dg-narr arch-narr' aria-live='polite'></span></div><div class='dg'><div class='dg-desk'>{_general_desktop()}</div>"
            f"<div class='dg-mobile'>{_general_mobile()}</div></div>{_legend(G_EDGES_LEGEND)}"
            "<div class='dg-detail' aria-live='polite'><h3>Tap any box</h3><p>Each box explains what happens there. "
            "Arrows show which way the data flows.</p></div></div>")


# ====================================================================================================== model adapters (admin)
def _model_desktop(cfg: dict) -> str:
    p = "md"
    models = cfg.get("models", {})
    body = []
    body.append(_node(p, "pipeline", 20, 210, 200, 196, "magenta", "⚙", "Fix pipeline", "Engine._attempt()",
                      "Builds the prompt from the error, the relevant files and the short history, then asks ONE model.",
                      ("Analyze the error", "Pick relevant files", "Ask for a patch")))
    body.append(_node(p, "routerm", 268, 210, 214, 196, "violet", "🧭", "Model router", "router.decide()",
                      "Expected-cost dynamic program plus business rules. Pure function; every decision is logged.",
                      ("Cheapest likely mode", "Business rules", "Skip paused tiers", "Escalate on failure", "Log every decision")[:4]))
    body.append(_edge(p, "M222,308 L264,308", "violet", "request", 243, 298))
    # guard bar
    body.append("<g class='dn' tabindex='0' role='button' data-k='guard' data-title='Guard' data-text='Before any money is spent: tries "
                "left this month, pack tries, per-bug and per-user caps, the global budget level, the kill switch, paused tiers, rate "
                "limits and cool-downs.' aria-label='Guard'><rect class='box' x='512' y='70' width='34' height='520' rx='12' "
                f"fill='url(#{p}-g-amber)' stroke='{C['amber']}' stroke-width='2' filter='url(#{p}-glow)'/>"
                "<text class='t' transform='translate(535,330) rotate(-90)' text-anchor='middle' style='font-size:13px'>GUARD · quota · budget · kill switch</text></g>")
    body.append(_edge(p, "M484,308 L508,308", "violet"))
    rows = [("groq", "GroqAdapter", "OpenAI-style chat", "Groq", f"Low effort\n{models.get('groq', '')}"),
            ("haiku", "AnthropicAdapter", "Messages API + cache", "Anthropic", f"Normal\n{models.get('haiku', '')}"),
            ("sonnet", "AnthropicAdapter", "Messages API + cache", "Anthropic", f"High\n{models.get('sonnet', '')}"),
            ("opus", "AnthropicAdapter", "Messages API + cache", "Anthropic", f"Extra\n{models.get('opus', '')}"),
            ("or", "OpenRouterAdapter", "OpenAI-compatible", "OpenRouter", "any mode, one key\nFIXENGINE_PROVIDER")]
    body.append(f"<rect x='570' y='58' width='450' height='548' rx='18' fill='none' stroke='{C['violet']}' stroke-opacity='.45' stroke-width='1.5'/>")
    body.append("<text class='lane' x='586' y='84'>Adapters → providers</text>")
    for i, (tier, adapter, fmt, prov, sub) in enumerate(rows):
        y = 100 + i * 100
        body.append(_edge(p, f"M548,{y + 40} L584,{y + 40}", "violet"))
        body.append(_node(p, f"ad-{tier}", 588, y, 176, 80, "violet", "⇄", adapter, fmt,
                          f"{adapter}: translates our request into the {prov} format ({fmt}). Same call signature for every provider; "
                          "a missing key means the mode is unavailable, never an error.", title_size=13))
        body.append(_edge(p, f"M766,{y + 40} L812,{y + 40}", "violet"))
        body.append(_node(p, f"pv-{tier}", 816, y, 190, 80, "cyan", "☁", prov, sub,
                          f"{prov}: {sub.replace(chr(10), ' · ')}. Model ids come from fixengine/config.py and can be changed with environment variables (FIXENGINE_MODEL_<MODE>).",
                          title_size=14))
        body.append(_edge(p, f"M1008,{y + 40} C1040,{y + 40} 1040,308 1068,308", "green", style="slow"))
    body.append(_node(p, "norm", 1072, 210, 182, 196, "cyan", "≋", "Normalizer", "ModelResult",
                      "Every provider's answer becomes the same ModelResult: text, tokens in/out, cache reads and the model that "
                      "really answered. Costs go to the ledger; secrets are redacted.",
                      ("Same shape", "Tokens + ₹ cost", "Redact secrets", "1 ledger row")))
    # fallback
    body.append(_node(p, "fallback", 300, 640, 250, 70, "amber", "⚠", "Fallback policy", "automatic",
                      "Groq 413/429 → smaller model. Bad key, unknown model or provider rule → that mode pauses and the router "
                      "picks the next best one. 3 outages → provider rests 10 minutes. Nothing is retried blindly."))
    body.append(_edge(p, "M796,606 L796,675 L554,675", "amber", "model error: not found · retired · down", 690, 664, "dashed"))
    body.append(_edge(p, "M300,675 L250,675 L250,420 L330,420 L330,410", "amber", "switch to next best mode", 258, 560, "dashed", "start"))
    # result back to the pipeline
    body.append(_edge(p, "M1163,408 L1163,760 L120,760 L120,410", "green", "", 0, 0))
    body.append(f"<rect x='420' y='742' width='430' height='36' rx='18' fill='#0d1f17' stroke='{C['green']}' stroke-width='2' filter='url(#{p}-glow)'/>"
                "<text class='t' x='635' y='766' text-anchor='middle' style='font-size:14px'>✅ Patch → policy check → sandbox proof → PR</text>")
    # what the router weighs
    factors = [("🎯", "Bug class", "easy · medium · hard"), ("🔢", "Tries left", "monthly quota"), ("💰", "Budget level", "global B"),
               ("📈", "Success odds", "learned from ledger"), ("⏱", "Cost per try", "tokens × price"), ("↺", "Past attempts", "progress?")]
    body.append(f"<rect x='20' y='800' width='1234' height='70' rx='16' fill='#120a1b' stroke='{C['magenta']}' stroke-opacity='.6'/>")
    for i, (ico, t, s) in enumerate(factors):
        x = 40 + i * 205
        body.append(f"<text class='ico' x='{x}' y='842'>{ico}</text><text class='t' x='{x + 30}' y='832' style='font-size:13px'>{E(t)}</text>"
                    f"<text class='s' x='{x + 30}' y='850'>{E(s)}</text>")
    # legend
    body.append(f"<g transform='translate(1060,40)'><rect width='194' height='92' rx='12' fill='#120a1bcc' stroke='#3a2338'/>"
                f"<path d='M14,24 h34' stroke='{C['violet']}' stroke-width='3'/><text class='s' x='58' y='28'>Request (to model)</text>"
                f"<path d='M14,50 h34' stroke='{C['green']}' stroke-width='3'/><text class='s' x='58' y='54'>Response (from model)</text>"
                f"<path d='M14,76 h34' stroke='{C['amber']}' stroke-width='3' stroke-dasharray='5 5'/><text class='s' x='58' y='80'>Fallback (on failure)</text></g>")
    return _svg(p, "0 0 1274 884", "".join(body), "Agent Daemon model adapter architecture")


def _model_mobile(cfg: dict) -> str:
    models = cfg.get("models", {})
    steps = [("lane", "Every model call"),
             ("node", "pipeline", "magenta", "⚙", "Fix pipeline", "Engine._attempt()", "Builds the prompt and asks one model."),
             ("node", "routerm", "violet", "🧭", "Model router", "cheapest likely mode", "Expected-cost DP + business rules; logged."),
             ("node", "guard", "amber", "🛡", "Guard", "quota · budget · kill switch", "Refuses before any money is spent."),
             ("node", "ad", "violet", "⇄", "Adapter", "Groq · Anthropic · OpenRouter", "Translates to the provider's format."),
             ("node", "pv", "cyan", "☁", "Provider", f"{models.get('haiku', '')} …", "The model answers with text only."),
             ("note", "fallback", "amber", "⚠", "Fallback policy", "pause mode → next best", "Errors pause a mode; the router picks the next.", "on error"),
             ("node", "norm", "cyan", "≋", "Normalizer", "ModelResult + ₹ cost", "Same shape for every provider; ledger row."),
             ("node", "proof", "green", "✅", "Policy + sandbox", "proof → PR", "The patch must pass the same sandbox check.")]
    return _vertical("mm", steps, title="Agent Daemon model adapter architecture (phone layout)")


M_ORDER = ["pipeline", "routerm", "guard", "ad-haiku", "ad", "pv-haiku", "pv", "fallback", "norm", "proof"]


def model_diagram(cfg: dict) -> str:
    return (f"<div class='dg-wrap' data-order='{','.join(M_ORDER)}'><div class='arch-controls'><button class='button primary dg-play' "
            f"type='button'>▶ Play the flow</button><span class='dg-narr arch-narr' aria-live='polite'></span></div><div class='dg'><div class='dg-desk'>{_model_desktop(cfg)}</div>"
            f"<div class='dg-mobile'>{_model_mobile(cfg)}</div></div>"
            "<div class='dg-detail' aria-live='polite'><h3>Tap any box</h3><p>Requests go through the router, the guard and one "
            "adapter; answers come back through the normalizer. Yellow dashed lines are the automatic fallback.</p></div></div>")
