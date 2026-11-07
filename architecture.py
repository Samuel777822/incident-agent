"""Interactive architecture pages.

  /how-it-works          everyone: the two flows (push guard, live error watch), the router algorithm in plain words with a small
                         playground, and what each dashboard stage means.
  /admin/architecture    admins only: system components, the model-adapter layer, the exact cost function with the live numbers
                         from fixengine/config.py, and a router simulator that calls the real router (router.decide) on the server.

No external libraries: plain HTML + CSS + a small same-origin script. Everything adapts from phone to desktop.
"""
from __future__ import annotations

import html
import json

import plans

E = lambda v: html.escape(str(v if v is not None else ""), quote=True)

CSS = """
.arch{--a1:#ff5a4a;--a2:#9a4dff;--ok:#6fe0b0;--bad:#ff7a6a;--card:#120a1bcc;--edge:#3a2338}
.arch h1{font-family:var(--display);font-size:clamp(28px,4.4vw,46px);line-height:1.12;margin:10px 0 12px}
.arch .lead{color:#d3c9e0;font-size:18px;max-width:760px}
.arch-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:26px 0 14px}
.arch-tab{padding:9px 16px;border-radius:999px;border:1px solid #ffffff26;background:#ffffff08;color:#e9e4ee;font:inherit;font-weight:600;cursor:pointer}
.arch-tab[aria-selected=true]{background:linear-gradient(120deg,#d1121f,#5b1fa8);border-color:#ff4a3a99;box-shadow:0 6px 22px #d1121f44}
.arch-panel[hidden]{display:none}
.flow{position:relative;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:18px 0}
.flow .node{position:relative;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;background:var(--card);
  border:1px solid var(--edge);border-radius:14px;padding:14px 14px 12px;cursor:pointer;transition:transform .2s,border-color .2s,box-shadow .2s;
  min-height:118px;text-align:left;color:inherit;font:inherit}
.flow .node .tag{margin-top:auto}.flow .node p{margin-bottom:8px}
.bar-note{font-size:12px;margin:-4px 0 6px 106px}
.flow .node:hover,.flow .node:focus-visible{border-color:#9a4dffaa;transform:translateY(-2px);outline:none}
.flow .node .hd{display:flex;align-items:flex-start;gap:8px}
.flow .node .n{display:inline-grid;place-items:center;flex:none;width:24px;height:24px;border-radius:50%;background:#ffffff14;font-size:12px;font-weight:700}
.flow .node b{font-size:15px}.flow .node p{margin:6px 0 0;font-size:13px;color:#b9aecb;line-height:1.45}
.flow .node .tag{display:inline-block;margin-top:8px;font-size:11px;padding:2px 8px;border-radius:999px;background:#ffffff10;color:#cdbfe0}
.flow .node.ok{border-color:#2f6b55}.flow .node.ok .n{background:#14392f;color:var(--ok)}
.flow .node.bad{border-color:#6a2b38}.flow .node.bad .n{background:#3a1820;color:var(--bad)}
.flow .node.lit{border-color:var(--a1);box-shadow:0 0 0 1px var(--a1),0 0 28px #e11d2a55;transform:translateY(-3px)}
.flow .node.sel{border-color:var(--a2);box-shadow:0 0 0 1px var(--a2),0 0 26px #9a4dff55}
.flow .node::after{content:"→";position:absolute;right:-13px;top:50%;transform:translateY(-50%);color:#7d6a92;font-size:16px}
.flow .node.end::after,.flow .node:nth-child(5n)::after{content:""}
.flow .loop{grid-column:1/-1;border:1px dashed #5b2a5a;border-radius:12px;padding:8px 12px;font-size:13px;color:#cdbfe0;text-align:center}
.flow .split{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.arch-detail{background:linear-gradient(145deg,#1a0f26,#0f0817);border:1px solid #5b2a5a;border-radius:16px;padding:18px 20px;margin:8px 0 18px;min-height:96px}
.arch-detail h3{margin:0 0 6px;font-family:var(--serif)}.arch-detail p{margin:0;color:#d3c9e0}
.arch-detail code{background:#ffffff12;padding:1px 6px;border-radius:6px}
.arch-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0}
.arch-narr{color:#ffd0c9;font-size:14px;min-height:20px}
.stack-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.stack-row span{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid #ffffff22}
.algo{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px;align-items:start}.algo>*{min-width:0}
.formula{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#0b0710;border:1px solid var(--edge);border-radius:12px;padding:14px 16px;
  color:#f2edf7;overflow-x:auto;white-space:pre;font-size:13.5px;line-height:1.6}
.play label{display:block;margin:10px 0 4px;font-weight:600;font-size:14px}.play select,.play input{display:block;width:100%;margin-top:6px}
.play input[type=number]{padding:9px 10px;border-radius:10px;border:1px solid var(--edge);background:#0d0714;color:var(--text);font:inherit}
.bars{margin-top:14px}.bar{display:grid;grid-template-columns:96px 1fr 84px;gap:10px;align-items:center;margin:8px 0;font-size:14px}
.bar i{display:block;height:12px;border-radius:6px;background:linear-gradient(90deg,#5b1fa8,#d1121f);transition:width .35s}
.bar.best b{color:var(--ok)}.bar.best i{background:linear-gradient(90deg,#1f8a63,#6fe0b0)}
.algo.stack{grid-template-columns:minmax(0,1fr)}
#pg-bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:10px}#pg-bars>p{grid-column:1/-1}
.calc-row{border:1px solid var(--edge);border-radius:12px;padding:10px 12px;margin:10px 0;background:#0d0714}
.calc-row.best{border-color:#2f6b55;box-shadow:0 0 0 1px #2f6b5555}
.calc-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.calc-nums{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 0}
.play .calc-row{margin:0}
.calc-nums small{display:block;color:#b9aecb;font-size:11.5px;line-height:1.3}.calc-nums b{font-size:16px}
.calc-bar{height:8px;border-radius:6px;background:#ffffff10;margin:4px 0 6px}.calc-bar i{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#5b1fa8,#d1121f);transition:width .35s}
.calc-row.best .calc-bar i{background:linear-gradient(90deg,#1f8a63,#6fe0b0)}
.demo-note{font-size:13px;color:#ffdc91;background:#3a301b55;border:1px solid #5a4a2a;border-radius:10px;padding:8px 10px;margin:8px 0}
.small-note{font-size:12.5px;margin-top:10px}.formula-line{font-family:ui-monospace,Menlo,Consolas,monospace;background:#0b0710;border-radius:8px;padding:8px 10px}
details.more{margin:12px 0;border:1px solid var(--edge);border-radius:12px;padding:8px 12px;background:#120a1b99}
details.more summary{cursor:pointer;font-weight:650;color:#e9e4ee}details.more[open] summary{margin-bottom:8px}
.lesson{background:linear-gradient(145deg,#170d22,#0f0817);border:1px solid var(--edge);border-radius:16px;padding:18px 20px;margin:16px 0}
.lesson h3{margin:0 0 4px;font-family:var(--serif);font-size:22px}.lesson .tagline{color:#ffd0c9;margin:0 0 10px}
.lesson dl{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:8px 16px;margin:10px 0}.lesson dt{color:#cdbfe0;font-weight:650}.lesson dd{margin:0;color:#d8cde6}
.lesson .vars td:first-child{font-family:ui-monospace,Menlo,Consolas,monospace;white-space:nowrap}
.lesson-nav{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}.lesson-nav a{font-size:13px;padding:4px 10px;border-radius:999px;border:1px solid #ffffff22;color:#e9e4ee}
.sim-why{background:#0d0714;border:1px solid var(--edge);border-radius:12px;padding:12px 14px;margin:10px 0}
@media(max-width:640px){.calc-nums{grid-template-columns:1fr 1fr 1fr;gap:6px}.calc-nums b{font-size:14px}.lesson dl{grid-template-columns:1fr}.lesson{padding:14px}}
.stage-legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.stage-legend div{background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:10px 12px;font-size:14px}
.stage-legend b{display:block;margin-bottom:2px}
.arch table.mini{width:100%;min-width:0;border-collapse:collapse;font-size:14px}.arch table.mini td,.arch table.mini th{padding:7px 8px;border-bottom:1px solid var(--edge);text-align:left}
.arch .k{color:#cdbfe0}.arch .v{font-family:ui-monospace,Menlo,Consolas,monospace}
.layers{display:grid;gap:10px}.layer{display:grid;grid-template-columns:170px 1fr;gap:12px;align-items:stretch}
.layer>b{display:flex;align-items:center;justify-content:center;text-align:center;border-radius:12px;background:#ffffff0c;border:1px solid var(--edge);padding:10px;font-size:14px}
.layer .boxes{display:flex;flex-wrap:wrap;gap:8px}
.layer .box{flex:1 1 150px;background:var(--card);border:1px solid var(--edge);border-radius:12px;padding:10px 12px;font-size:13px;cursor:pointer;color:inherit;font:inherit;text-align:left}
.layer .box:hover,.layer .box.sel{border-color:#9a4dffaa}
.layer .box small{display:block;color:#b9aecb;margin-top:3px}
.sim-out{margin-top:12px}
@media(max-width:1000px){.flow{grid-template-columns:repeat(3,minmax(0,1fr))}.algo{grid-template-columns:1fr}
  .flow .node:nth-child(5n)::after{content:"→"}.flow .node:nth-child(3n)::after,.flow .node.end::after{content:""}}
@media(max-width:640px){.flow{grid-template-columns:1fr}.flow-wrap>.arch-detail{display:none}.flow .node::after,.flow .node:nth-child(3n)::after,.flow .node:nth-child(5n)::after{content:"↓";right:auto;left:50%;top:auto;bottom:-15px;transform:translateX(-50%)}
  .flow .node.end::after{content:""}.bar-note{margin-left:0}
  .flow .split{grid-template-columns:1fr}.layer{grid-template-columns:1fr}.bar{grid-template-columns:76px 1fr 70px}.arch .lead{font-size:16px}}
@media(prefers-reduced-motion:reduce){.flow .node,.bar i{transition:none}}
"""

PUSH_FLOW = [
    ("push", "You push to GitHub", "<code>git push</code> to the branch you connected. That is all you do.", "you"),
    ("hook", "GitHub tells us", "A signed webhook arrives within seconds. If the webhook is missing, the worker notices the new commit within a few minutes anyway.", "webhook · poller"),
    ("detect", "Find every project", "We download exactly that commit and find each part: Python, JavaScript/TypeScript, Java, plain HTML/CSS. Mixed repos get one check per part.", "multi-language"),
    ("sandbox", "Test it in the sandbox", "For every part: install → build / type-check → tests → start-up. A fresh container each time, no secrets, no network while tests run.", "free · no AI"),
    ("verdict", "Green or red?", "Green: the commit gets a ✓ on GitHub and you can deploy. Red: the commit gets a ✗ and the agent starts fixing it.", "commit status"),
    ("router", "Choose an AI", "The agent compares the available AI modes and picks an economical one that is likely to fix this bug. It starts with free attempts and moves to a stronger AI only when it needs to.", "economical choice"),
    ("model", "AI writes a small patch", "The model only reads the relevant files and the error, and only returns text. It cannot run anything or touch GitHub.", "text in, text out"),
    ("policy", "Safety rules", "Our code checks the patch: at most 3 files and 40 lines, never tests, CI files, build configs, dependencies or secrets.", "policy gate"),
    ("retest", "Same check, patched code", "The patched repo goes through the exact check that failed. Not green? Nothing is pushed: the agent tries again with what it learned, possibly with a stronger AI.", "proof"),
    ("pushfix", "Push the fix to GitHub", "A new branch <code>agent-daemon/fix-…</code> with a pull request into your branch. Auto mode merges it once proven; otherwise you review it.", "PR · auto-merge"),
]
LIVE_FLOW = [
    ("app", "Your live app crashes", "A real user hits a bug in the deployed app.", "production"),
    ("report", "Error reported", "A tiny monitor in the app (added automatically for Python, Node.js and web pages) sends the error, the stack trace and failed API answers to Agent Daemon. It also checks in every 30 seconds.", "/ingest"),
    ("group", "Grouped into an incident", "Repeats of the same error become one incident with a count, so you are not spammed.", "dedupe"),
    ("repro", "Reproduce in the sandbox", "We download your branch and run the same install → build → tests → start-up check to see what fails today.", "baseline"),
    ("router2", "Choose an AI, fix, re-test", "Exactly the same fix loop as the push guard: economical AI first, safety rules, proof in the sandbox.", "shared engine"),
    ("pushfix2", "Fix pushed back", "Branch + pull request, merged automatically in Auto mode when proven. The next deploy carries the fix.", "PR · auto-merge"),
]
STAGES = [
    ("Caught · waiting in line", "A push broke or a live error came in. The job is in the queue."),
    ("Downloading your code", "The worker is fetching that commit from GitHub."),
    ("Reproducing in the sandbox", "Install → build → tests → start-up on the current code, to see exactly what fails."),
    ("Normal / High / Extra mode is writing a fix", "The AI model of that mode is working on a patch. The pill shows how many tries of it you have left."),
    ("Testing the fix in the sandbox", "The patched code is going through the same check."),
    ("Waiting for your decision", "You reached a warning point. Open Usage to choose: let the agent decide, pick a mode, or send it to human review."),
    ("Pushing the fix to GitHub", "Creating the fix branch and the pull request."),
    ("Fix proven · merging", "Auto mode: the fix commit has a green status; it is being merged into your branch."),
    ("Fixed · the fixed version is on GitHub", "Done. Your branch now has the fix."),
    ("Fix pushed · pull request ready", "Pull request mode: review and merge it on GitHub."),
    ("Needs a human", "The agent stopped (caps, quota, or it could not prove a fix). A report explains what it tried."),
]


def _flow_html(flow, panel_id: str) -> str:
    nodes = []
    for i, (key, title, text, tag) in enumerate(flow, start=1):
        cls = "node"
        if key == "verdict":
            cls += " ok"
        if i == len(flow):
            cls += " end"
        nodes.append(f"<button type='button' class='{cls}' data-key='{E(key)}' data-step='{i}' data-title='{E(title)}' data-text='{E(text)}'>"
                     f"<span class='hd'><span class='n'>{i}</span><b>{E(title)}</b></span><p>{text}</p><span class='tag'>{E(tag)}</span></button>")
    loop = ("<div class='loop'>↺ Not green after the re-test? The agent tries again with the new error (and, after a stronger AI has "
            "looked, with its findings). It never repeats the same attempt with the same information. If the bug is still not fixed when "
            "the limits are reached, it stops and asks for a person, with a report of everything it tried.</div>")
    return f"<div class='flow' id='{E(panel_id)}-flow'>{''.join(nodes)}{loop}</div>"


SCRIPT = r"""(function(){
  var tabs=document.querySelectorAll('.arch-tab');
  tabs.forEach(function(t){t.addEventListener('click',function(){
    tabs.forEach(function(x){x.setAttribute('aria-selected',x===t?'true':'false');});
    document.querySelectorAll('.arch-panel').forEach(function(p){p.hidden=(p.id!==t.getAttribute('aria-controls'));});
  });});
  function wire(panel){
    var nodes=[].slice.call(panel.querySelectorAll('.node'));
    var detail=panel.querySelector('.arch-detail'), narr=panel.querySelector('.arch-narr'), btn=panel.querySelector('.arch-play');
    var timer=null, i=0;
    function show(n){nodes.forEach(function(x){x.classList.toggle('sel',x===n);});
      detail.innerHTML='<h3>'+n.getAttribute('data-step')+'. '+n.getAttribute('data-title')+'</h3><p>'+n.querySelector('p').innerHTML+'</p>';}
    nodes.forEach(function(n){n.addEventListener('click',function(){stop();show(n);});});
    function stop(){clearInterval(timer);timer=null;nodes.forEach(function(x){x.classList.remove('lit');});if(btn){btn.textContent='▶ Play the flow';}}
    function step(){nodes.forEach(function(x){x.classList.remove('lit');});
      if(i>=nodes.length){stop();narr.textContent='Done: the fixed version is on GitHub.';return;}
      var n=nodes[i]; n.classList.add('lit'); show(n); narr.textContent='Step '+(i+1)+' of '+nodes.length+': '+n.getAttribute('data-title');
      if(n.scrollIntoView&&window.innerWidth<640){n.scrollIntoView({block:'center',behavior:'smooth'});} i++;}
    if(btn){btn.addEventListener('click',function(){if(timer){stop();return;}i=0;btn.textContent='■ Stop';step();timer=setInterval(step,1900);});}
    if(nodes.length){show(nodes[0]);}
  }
  document.querySelectorAll('.flow-wrap').forEach(wire);
  // AI-choice calculator: the core comparison only, with the starting estimates. Maths unchanged:
  //   estimated total = attempt cost x usage adjustment + (1 - chance) x cheapest next step (next step: one more try, else the internal value G)
  var data=document.getElementById('arch-data'); if(!data){return;}
  var D=JSON.parse(data.textContent);
  var cls=document.getElementById('pg-class'), used=document.getElementById('pg-used'), usedOut=document.getElementById('pg-used-out'),
      bars=document.getElementById('pg-bars'), why=document.getElementById('pg-why');
  function rs(v){return '₹'+v.toFixed(2);}
  function draw(){
    var c=cls.value, u=+used.value/100; usedOut.textContent=Math.round(u*100)+'%';
    function adj(t){return 1+D.lambda*(t.key==='groq'?0:u);}
    function cost(t){return t.cost*adj(t);}
    function p(t,fails){return D.p[c][t.key]*Math.pow(D.decay,fails);}
    function second(first){var best=D.G;D.tiers.forEach(function(n){var f=(n.key===first.key)?1:0;
      var v=cost(n)+(1-p(n,f))*D.G; if(v<best){best=v;}});return best;}
    var rows=D.tiers.map(function(t){var pp=p(t,0),nx=second(t);return {t:t,name:t.name,ev:cost(t)+(1-pp)*nx,p:pp,raw:t.cost,adj:adj(t),next:nx};});
    var best=rows.reduce(function(a,b){return b.ev<a.ev?b:a;}); var max=Math.max.apply(null,rows.map(function(r){return r.ev;}));
    bars.innerHTML=rows.map(function(r){
      var adjNote=r.t.key==='groq'?'free AI: no usage adjustment':'compared as '+rs(r.raw*r.adj)+' (usage adjustment ×'+r.adj.toFixed(2)+', internal only)';
      return '<div class="calc-row'+(r===best?' best':'')+'"><div class="calc-head"><b>'+r.name+'</b>'+(r===best?'<span class="pill green">lowest estimated total</span>':'')+'</div>'+
        '<div class="calc-nums"><div><small>Cost of this AI attempt</small><b>'+rs(r.raw)+'</b></div>'+
        '<div><small>Chance this attempt fixes it</small><b>'+Math.round(r.p*100)+'%</b></div>'+
        '<div><small>Estimated total cost to resolve the bug</small><b>'+rs(r.ev)+'</b></div></div>'+
        '<div class="calc-bar"><i style="width:'+Math.max(3,100*r.ev/max)+'%"></i></div><small class="muted">'+adjNote+'</small></div>';}).join('');
    var lo=rows[0], fail=1-lo.p;
    if(why){why.innerHTML='<p>Take <b>'+lo.name+'</b>. One attempt costs <b>'+rs(lo.raw)+'</b> because it uses a free AI. '+
      'But for this kind of bug it fixes the problem only about <b>'+Math.round(lo.p*100)+' times in 100</b>. In the other <b>'+Math.round(fail*100)+
      '</b> the bug is still there, so the agent still needs a next step. The cheapest next step from there is estimated at <b>'+rs(lo.next)+'</b>.</p>'+
      '<p class="formula-line">'+rs(cost(lo.t))+' + '+fail.toFixed(2)+' × '+rs(lo.next)+' = <b>'+rs(lo.ev)+'</b> estimated total</p>'+
      '<p>That next-step estimate includes another AI attempt and, in case that also fails, an internal value of <b>₹'+D.G+'</b> that stands for '+
      '“a person has to step in”. The ₹'+D.G+' is only a number the agent uses to compare options. <b>It is never charged to you.</b></p>'+
      '<p>So a reading such as <b>₹0.00</b> for the attempt and <b>₹23.90</b> in total is not a contradiction: the first number is what one attempt costs, '+
      'the second is a forecast of everything it may take to finish the job.</p>';}
  }
  if(cls&&used){cls.addEventListener('change',draw);used.addEventListener('input',draw);draw();}
})();"""


def _playground_data(cfg: dict) -> str:
    from fixengine import config as fx_config
    from fixengine.router import RouterInput, _est_cost
    s = RouterInput(repo_tokens=10000)
    tiers = [{"key": t, "name": fx_config.USER_MODE_NAMES[t], "cost": round(_est_cost(cfg, t, s), 3)} for t in fx_config.TIERS]
    p = {c: {t: fx_config.PLACEHOLDER_P[c][t] for t in fx_config.TIERS} for c in fx_config.PLACEHOLDER_P}
    return json.dumps({"tiers": tiers, "p": p, "lambda": float(cfg["router"]["lambda"]), "G": float(cfg["router"]["give_up_penalty_inr"]),
                       "decay": float(cfg["router"]["repeat_decay"]), "depth": int(cfg["router"]["max_depth"])}).replace("</", "<\\/")


def _algo_section(cfg: dict) -> str:
    q = plans.quotas()
    r = cfg["router"]
    return f"""<section class='section' id='router'><div class='eyebrow'>Choosing an AI</div><h2>How the agent decides which AI to use</h2>
<p class='lead'>Agent Daemon compares the available AI models and chooses an economical option to fix your bug. When a weaker AI cannot
solve it, the agent can move to a stronger one.</p>
<div class='grid'>
<article class='card'><h3>The four modes</h3><p class='muted'><b>Low effort</b> is a free first look. <b>Normal</b> handles most everyday bugs.
<b>High</b> is a stronger AI for bugs Normal could not fix. <b>Extra</b> is the strongest, kept for the hardest bugs. You never need to pick one:
the agent does, unless you want to.</p></article>
<article class='card'><h3>What a try is</h3><p class='muted'>{E(plans.TRY_DEFINITION)} Your plan includes {q['normal']} Normal, {q['high']} High and
{q['extra']} Extra tries a month.</p></article>
<article class='card'><h3>Why it sometimes uses a stronger AI</h3><p class='muted'>{E(plans.WHY_STRONGER)}</p></article>
<article class='card'><h3>When a fix fails</h3><p class='muted'>{E(plans.FAILED_FIX)}</p></article>
<article class='card'><h3>When a person is needed</h3><p class='muted'>{E(plans.HUMAN_NEEDED)}</p></article>
<article class='card'><h3>You stay in control</h3><p class='muted'>On the Usage page you can let the agent decide (Auto), be asked first (Ask me), or never use
High and Extra (Economy). Your dashboard always shows which mode is working and how many tries you have left.</p></article>
</div>

<div class='algo stack' style='margin-top:22px'><div>
<h3>Three different numbers</h3>
<ol class='muted'>
<li><b>Cost of this AI attempt</b>: what the AI provider bills Agent Daemon for one attempt in that mode. Stronger AIs cost more per attempt.</li>
<li><b>Usage adjustment</b>: when much of the month's allowance is used, the agent treats the paid modes as a little more
"expensive" so it saves them for bugs that really need them. It only affects the comparison; nobody is charged for it.</li>
<li><b>Estimated total cost to resolve the bug</b>: a forecast that adds the attempt to what may come after it if that attempt fails
(more attempts, or a person stepping in). The agent picks the mode with the lowest estimated total, not simply the cheapest attempt.</li>
</ol>
<p class='muted'>A cheap attempt that rarely works can end up with a higher estimated total than a more expensive attempt that usually works.
That is why the free mode does not always look best.</p>
<details class='more'><summary>Show the formula</summary>
<div class='formula'>estimated total = attempt cost × usage adjustment
                + (1 − chance it works) × cheapest next step

usage adjustment = 1 + {E(r['lambda'])} × share of the month's allowance used
cheapest next step = one more attempt, or the internal
                     "person steps in" value of ₹{E(r['give_up_penalty_inr'])} if that is lower</div>
<p class='muted'>For the technically curious: the real agent uses an expected-cost <b>dynamic program</b>, the same "cheapest route" idea as
<b>Dijkstra's algorithm</b> but for steps that can succeed or fail, and it looks up to {E(r['max_depth'])} attempts ahead.</p></details>
</div>
<div class='card play'><h3>Try the comparison</h3>
<label for='pg-class'>What kind of bug?</label><select id='pg-class'><option value='easy'>Easy (a typo, a missing import, a setting)</option>
<option value='medium' selected>Medium (wrong logic across a few files)</option><option value='hard'>Hard (timing, state, many files)</option></select>
<label for='pg-used'>How much of the monthly AI allowance has been used? <span id='pg-used-out'>20%</span></label>
<input id='pg-used' type='range' min='0' max='100' value='20'>
<p class='demo-note'>This is a demonstration. It shows how usage can influence the AI selection. It does not display your actual account usage or remaining attempts.</p>
<div id='pg-bars'></div>
<details class='more'><summary>Why are these two costs different?</summary><div id='pg-why'></div></details>
<p class='muted small-note'>The chances shown are <b>starting estimates</b> used for this demonstration, not proven success rates. The agent refines
them with real results as it fixes more bugs. This calculator shows only the core comparison: the real agent also always starts with the free
attempts, gives Normal at least two attempts before a stronger AI, and never goes past your tries or the per-bug limits.</p></div></div></section>
<script type='application/json' id='arch-data'>{_playground_data(cfg)}</script>"""


def user_page_html(cfg: dict | None = None) -> str:
    from fixengine import config as fx_config
    cfg = cfg or fx_config.load()
    legend = "".join(f"<div><b>{E(t)}</b><span class='muted'>{E(d)}</span></div>" for t, d in STAGES)
    import arch_diagrams
    return f"""<style>{CSS}{arch_diagrams.CSS}</style><div class='arch'>
<section class='section'><div class='eyebrow'>How it works</div>
<h1>Push your code. The agent catches what broke, fixes it, and pushes the fix back.</h1>
<p class='lead'>Connect once. Then two ways in, one fix engine: the <b>Push guard</b> tests every push (and scans your code once
right away), and the <b>Live error watch</b> (a small monitor inside your app) reports errors and checks in every 30 seconds.
Tap any box to read what happens there, or press play to follow a bug from connect to fix.</p>
{arch_diagrams.general_diagram()}
<div class='stack-row'><span>Python</span><span>JavaScript</span><span>TypeScript</span><span>React · Next.js · Node</span><span>Java · Maven · Gradle</span><span>HTML · CSS</span><span>mixed repos</span></div>
</section>
{_algo_section(cfg)}
<section class='section'><div class='eyebrow'>Your dashboard</div><h2>What each status means</h2>
<p class='muted'>The dashboard updates by itself every few seconds while the agent is working. It always shows the mode in use and how many tries of it you have left.</p>
<div class='stage-legend'>{legend}</div></section>
<section class='section'><div class='eyebrow'>Safety</div><h2>What the agent can and cannot do</h2><div class='grid'>
<article class='card'><h3>Your code runs only in the sandbox</h3><p class='muted'>Fresh container per run, non-root, read-only system, memory/CPU/time limits, no secrets, and no network while tests run.</p></article>
<article class='card'><h3>Models only write text</h3><p class='muted'>They never get tools, never run commands and never see your keys. Our code applies the patch after the safety rules.</p></article>
<article class='card'><h3>Never straight to your branch</h3><p class='muted'>Every fix is a branch and a pull request. Auto mode merges only what the sandbox proved and GitHub checks passed.</p></article>
<article class='card'><h3>No surprise bills</h3><p class='muted'>Monthly tries per mode, per-bug caps and a global budget with a kill switch. Push checks themselves are free.</p></article>
</div></section>
<section class='card mission-card' style='text-align:center'><h3>Try it on your repo</h3><p class='muted'>Connect a repository and your next push is tested automatically.</p>
<div class='actions' style='justify-content:center'><a class='button primary' href='/login'>Get started</a><a class='button' href='/pricing'>Pricing</a></div></section>
</div><script>{SCRIPT}{arch_diagrams.SCRIPT}</script>"""


# ------------------------------------------------------------------------------------------------------------------ admin
SYSTEM_LAYERS = [
    ("Customers", [("Browser", "Dashboard, usage, billing, chat. Server-rendered pages + same-origin live refresh."),
                   ("GitHub", "Push webhooks in, tarball downloads, commit statuses, fix branches and PRs out."),
                   ("Live app (optional)", "incident_agent_monitor.py posts errors and heartbeats to /ingest.")]),
    ("Render: web", [("web_app.py (gunicorn)", "Routes, auth (Google + admin passwords), CSRF, /webhooks/github/<id>, /ingest, payments UI."),
                     ("push_watch.py", "Webhook signature check, push parsing, commit statuses, poller, run_check()."),
                     ("Worker (portal_worker.py)", "Loop: one push check → one incident → expired choices → poll pushes → auto-merge.")]),
    ("Fix engine", [("orchestrator.Engine", "baseline → [router → guard → adapter → policy → sandbox]* → PR or review. Resumable from the ledger."),
                    ("router.py", "Expected-cost DP + hard rules. Pure function, every decision logged."),
                    ("guard.py", "Quotas, packs, per-user ceiling, budget B, kill-switch levels, spike breaker, rate limits."),
                    ("validator.py", "Patch policy (≤3 files, ≤40 lines, no tests/CI/deps/secrets) and verification level.")]),
    ("Sandbox host (VPS)", [("sandbox_service.py", "Signed /run endpoint (HMAC, 5-minute window). One job at a time."),
                            ("DockerRunner", "Per stack: install (network) → build → test → smoke (no network). Non-root, read-only, caps dropped."),
                            ("Images", "fixengine-sandbox-python / -node (JS, TS, static) / -java.")]),
    ("Data and providers", [("PostgreSQL", "users, projects, push_checks, incidents, fx_attempts (the cost ledger), router decisions, payments."),
                            ("Model providers", "Groq (Low effort), Anthropic Claude Haiku/Sonnet/Opus (Normal/High/Extra), or all through OpenRouter."),
                            ("Brevo", "Email over HTTPS: warnings, push failures, payment and admin alerts.")]),
]
ADAPTER_LAYERS = [
    ("Caller", [("Engine._attempt()", "Builds the prompt blocks (relevant files, error, short history, stronger diagnosis) and asks ONE adapter.")]),
    ("Gate", [("Guard.check(user, tier)", "Quota left? Pack try? Budget level? Tier paused? Rate limit / cooldown? Refuses before any money is spent.")]),
    ("Interface", [("BaseAdapter.call(system, blocks, max_tokens)", "Same signature for every provider. Returns ModelResult(text, tokens_in, tokens_out, cache_read, model)."),
                   ("configured() / describe()", "Missing key = that mode is unavailable, never an error.")]),
    ("Providers", [("GroqAdapter", "Low effort, free tier, OpenAI-style chat API."), ("AnthropicAdapter", "Normal / High / Extra with prompt caching."),
                   ("OpenRouterAdapter", "One key for every tier (FIXENGINE_PROVIDER=auto | openrouter | direct)."),
                   ("DryRunAdapter / FakeAdapter", "Benchmarks and tests: never touch the network.")]),
    ("Hygiene", [("redact()", "Strips keys, bearer tokens and our own secrets from every log, error and report."),
                 ("AdapterError(kind)", "auth | rate_limit | outage | timeout | config | … ; retryable kinds back off, persistent ones auto-pause the tier."),
                 ("Ledger row", "Every call writes one fx_attempts row: tier, model, tokens, ₹ cost, result.")]),
]


def _layers_list(layers) -> str:
    """The code map behind the diagrams, as a plain list (text, not boxes)."""
    rows = []
    for title, boxes in layers:
        items = "".join(f"<li><b>{E(n)}</b>: <span class='muted'>{E(d)}</span></li>" for n, d in boxes)
        rows.append(f"<h4>{E(title)}</h4><ul>{items}</ul>")
    return "".join(rows)


def _layers_html(layers, ident: str) -> str:
    rows = []
    for title, boxes in layers:
        items = "".join(f"<button type='button' class='box' data-title='{E(n)}' data-text='{E(d)}'><b>{E(n)}</b><small>{E(d)}</small></button>" for n, d in boxes)
        rows.append(f"<div class='layer'><b>{E(title)}</b><div class='boxes'>{items}</div></div>")
    return f"<div class='layers' id='{E(ident)}'>{''.join(rows)}</div>"


def admin_page_html(cfg: dict, learned: dict | None = None, csrf: str = "") -> str:
    from fixengine import config as fx_config
    r, caps, b, tok = cfg["router"], cfg["caps"], cfg["budget"], cfg["tokens"]
    prices = "".join(f"<tr><td>{E(fx_config.USER_MODE_NAMES[t])}</td><td class='v'>{E(cfg['models'].get(t, ''))}</td>"
                     f"<td class='v'>${E(cfg['prices_usd_per_m'][t]['in'])} / ${E(cfg['prices_usd_per_m'][t]['out'])}</td>"
                     f"<td class='v'>{E(cfg['quotas'].get(t, '—') if t != 'groq' else str(cfg['groq_daily_cap']) + '/day')}</td></tr>"
                     for t in fx_config.TIERS)
    learned = learned or {}
    prob_rows = ""
    for c, row in fx_config.PLACEHOLDER_P.items():
        cells = ""
        for cell in ("groq", "haiku", "haiku_diag", "sonnet", "opus"):
            ok, n = learned.get((c, cell), (0, 0))
            live = f"<br><small class='muted'>measured {(ok + 1) / (n + 2):.2f} (n={n})</small>" if n else ""
            cells += f"<td class='v'>{row[cell]:.2f}{live}</td>"
        prob_rows += f"<tr><td>{E(c)}</td>{cells}</tr>"
    params = [("λ (quota pressure)", r["lambda"], "How much a nearly used-up mode is made to look more expensive.", "Raise: saves High/Extra more aggressively."),
              ("G (give-up penalty, ₹)", r["give_up_penalty_inr"], "Internal value of stopping; not a charge.", "Raise: tries harder before human review."),
              ("search depth", r["max_depth"], "Attempts the router looks ahead.", "Raise: sees longer strategies, slightly slower."),
              ("free tries first", r["free_tries"], "Low effort attempts before any paid mode.", "Raise: cheaper, but slower to a fix."),
              ("Normal floor", r["haiku_floor"], "Normal attempts before High/Extra are allowed.", "Raise: protects High quota, delays hard fixes."),
              ("drop-back tries", r["drop_back_tries"], "Normal attempts using a stronger model's diagnosis.", "Raise: more cheap finishes after High."),
              ("repeat decay", r["repeat_decay"], "Probability multiplier per earlier failure of the same mode.", "Lower: escalates sooner."),
              ("min samples before learned p", r["min_samples_for_learned"], "Real results needed before measured p replaces the estimate.", "Lower: adapts faster, noisier."),
              ("per-bug cap ₹ / tries", f"{caps['per_bug_cost_inr']} / {caps['per_bug_max_tries']}", "Hard stop for one bug.", "Raise: more spend on hard bugs."),
              ("user ceiling ₹/month", caps["user_month_ceiling_inr"], "Max AI spend one customer can cause per month.", "Protects margin per customer."),
              ("budget B / credits ₹", f"{b['b_inr']} / {b['credits_inr']}", "Monthly limit and prepaid credits.", "See /admin/fix for the protection levels."),
              ("kill-switch levels (× B)", ", ".join(str(x) for x in b["levels"]), "Fractions of B where protections start.", "See /admin/fix."),
              ("max prompt tokens", tok["max_prompt_tokens"], "Cap on code sent per attempt.", "Keeps Normal under its 100K-token price band."),
              ("USD → INR", cfg["usd_inr"], "Exchange rate for all rupee figures.", "Changes every rupee estimate.")]
    param_rows = "".join(f"<tr><td class='k'>{E(k)}</td><td class='v'>{E(v)}</td><td>{E(m)}</td><td class='muted'>{E(eff)}</td></tr>"
                         for k, v, m, eff in params)
    sim = """<form id='sim' class='card play' onsubmit='return false'><h3 id='l-sim'>Router simulator</h3>
<p class='muted'>Describe a bug's situation and ask the <b>real</b> <code>router.decide()</code> what it would do next. This is a dry run: it does not
use any customer's tries, does not call any AI provider, and saves nothing.</p>
<details class='more'><summary>What the inputs mean</summary><ul class='muted'>
<li><b>Bug class</b>: what triage decided (affects p).</li><li><b>User setting</b>: Auto, Ask me, or Economy (Economy never allows High/Extra).</li>
<li><b>… tries</b>: attempts already made on <i>this bug</i> in each mode. The free-first and Normal-floor rules look at these.</li>
<li><b>… left</b>: the customer's remaining quota this month (drives quota pressure λ and the 'never past quota' rule).</li>
<li><b>Spent on bug</b>: rupees already spent on this bug (per-bug cap).</li><li><b>Stronger diagnosis</b>: High/Extra already explained the bug (Normal uses the 'Normal + diag' p).</li>
<li><b>Last try progressed</b>: fewer failing tests last time (allows a third Normal try).</li></ul></details>
<div class='grid' style='margin:0;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))'>
<label>Bug class<select name='bug_class'><option>easy</option><option selected>medium</option><option>hard</option></select></label>
<label>User setting<select name='mode'><option>auto</option><option>ask</option><option>economy</option></select></label>
<label>Low effort tries<input name='free_tries' type='number' min='0' max='5' value='3'></label>
<label>Normal tries<input name='haiku_tries' type='number' min='0' max='10' value='2'></label>
<label>High tries<input name='sonnet_tries' type='number' min='0' max='6' value='0'></label>
<label>Extra tries<input name='opus_tries' type='number' min='0' max='3' value='0'></label>
<label>Normal left<input name='left_haiku' type='number' min='0' max='60' value='25'></label>
<label>High left<input name='left_sonnet' type='number' min='0' max='12' value='5'></label>
<label>Extra left<input name='left_opus' type='number' min='0' max='6' value='3'></label>
<label>Spent on bug ₹<input name='spent' type='number' min='0' max='100' step='0.5' value='0.5'></label>
<label>Stronger diagnosis?<select name='strong_diag'><option value='0'>no</option><option value='1'>yes</option></select></label>
<label>Last try progressed?<select name='progress'><option value='0'>no</option><option value='1'>yes</option></select></label></div>
<p><button class='button primary' type='button' id='sim-run'>Ask the router</button></p><div class='sim-out' id='sim-out'></div></form>
<script>(function(){var f=document.getElementById('sim'),out=document.getElementById('sim-out');
document.getElementById('sim-run').addEventListener('click',function(){var q=new URLSearchParams(new FormData(f)).toString();
out.textContent='Thinking…';fetch('/admin/architecture?simulate=1&'+q,{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(d){
if(d.error){out.textContent=d.error;return;}
function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
var opts=(d.options||[]).slice().sort(function(a,b){return a.expected_cost-b.expected_cost;});
var rows=opts.map(function(o){return '<tr'+(o.action===d.action?' style="background:#14392f"':'')+'><td>'+esc(o.name)+'</td><td>'+(o.p===null||o.p===undefined||o.action==='stop'?'—':Math.round(o.p*100)+'%')+'</td><td>₹'+(o.try_cost===undefined?'—':o.try_cost)+'</td><td><b>₹'+o.expected_cost+'</b></td></tr>';}).join('');
var why;
if(d.forced){why='<p><b>Decided by a business rule</b>, not by the cost maths: '+esc(d.reason)+'. When a rule forces the action the optimizer is not consulted.</p>';}
else{var nb=opts.filter(function(o){return o.action!==d.action;})[0];
why='<p><b>Decided by the cost optimizer.</b> It compared '+opts.length+' options (including stopping, valued at G) and picked the lowest estimated total: <b>'+esc(d.action_name)+'</b> at ₹'+(opts[0]?opts[0].expected_cost:'?')+
(nb?', versus ₹'+nb.expected_cost+' for '+esc(nb.name):'')+'. '+(d.action==='stop'?'Every attempt was expected to cost more than handing the bug to a person.':'')+'</p>';}
out.innerHTML='<div class="sim-why"><p style="font-size:18px;margin:0 0 6px">Next step: <b>'+esc(d.action_name)+'</b> <span class="pill '+(d.forced?'amber':'green')+'">'+(d.forced?'business rule':'optimizer')+'</span></p>'+why+'</div>'+
(rows?'<div class="table-wrap"><table class="table mini"><tr><th>Option</th><th>p (chance)</th><th>ĉ (provider cost of the attempt)</th><th>V (estimated total to resolve)</th></tr>'+rows+'</table></div>':'')+
'<p class="muted">No tries were used and no AI provider was called.</p>';
}).catch(function(){out.textContent='Could not reach the simulator.';});});})();</script>"""
    import arch_diagrams
    return f"""<style>{CSS}{arch_diagrams.CSS}</style><div class='arch'>
<section class='section'><p><a href='/admin'>← Admin</a></p><div class='eyebrow'>Admin · architecture</div>
<h1>How Agent Daemon works inside</h1>
<p class='lead'>The system, the model-adapter layer, and a step-by-step course on how the router chooses an AI. Every number comes live from
<code>fixengine/config.py</code> (plus <code>FIXENGINE_CONFIG_JSON</code> overrides) and the cost ledger.</p>
<div class='arch-tabs' role='tablist'>
<button class='arch-tab' role='tab' aria-selected='true' aria-controls='a-system'>General architecture</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='a-adapters'>Model adapters</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='a-cost'>How the router decides (learn)</button></div>
<div class='arch-panel' id='a-system' role='tabpanel'>
<p class='muted'>Every process and how it connects. The same diagram customers see on /how-it-works. Tap a box for details.</p>
{arch_diagrams.general_diagram()}
<details class='more'><summary>Components behind each box (code map)</summary>{_layers_list(SYSTEM_LAYERS)}</details>
<div class='arch-detail' id='sys-detail'><h3>Golden rule</h3><p>Only the router chooses models; every model call passes the quota and budget guard and writes one ledger row. Customer code runs only in the sandbox. Nothing is committed to a public repository.</p></div></div>
<div class='arch-panel' id='a-adapters' role='tabpanel' hidden><p class='muted'>Every model call goes through this layer: router → guard → one adapter → provider → normalizer. Tap a box for details.</p>
{arch_diagrams.model_diagram(cfg)}
<details class='more'><summary>Adapter interface and error handling (code map)</summary>{_layers_list(ADAPTER_LAYERS)}</details>
<h3>Tiers, models, prices and quotas</h3><div class='table-wrap'><table class='table mini'><tr><th>Mode</th><th>Model id</th><th>USD per M tokens (in / out)</th><th>Quota</th></tr>{prices}</table></div></div>
<div class='arch-panel' id='a-cost' role='tabpanel' hidden>
<div class='explain-intro card'><h3>Learn the router in 10 short lessons</h3><p class='muted'>Each lesson gives a plain definition, why Agent Daemon
needs it, the exact formula from <code>fixengine/router.py</code>, what every symbol means, a worked example with today's real settings, and what it
changes in the product. Numbers marked ₹ are internal estimates for decisions; the money actually spent is on <a href='/admin/fix'>/admin/fix</a>.</p></div>
{_admin_lessons(cfg, learned)}
<h3 id='l-params'>Every parameter, in one table</h3><div class='table-wrap'><table class='table mini'><tr><th>Parameter</th><th>Value</th><th>What it means</th><th>If you change it</th></tr>{param_rows}</table></div>
<p class='muted'>Change these with <code>FIXENGINE_CONFIG_JSON</code> (or the env shortcuts listed on /admin/fix). Prices, model ids and quotas are shown here, never changed here.</p>
{sim}</div>
</section></div><script>{SCRIPT}{arch_diagrams.SCRIPT}
(function(){{function wireLayers(id,detailId){{var root=document.getElementById(id),d=document.getElementById(detailId);if(!root||!d)return;
root.querySelectorAll('.box').forEach(function(b){{b.addEventListener('click',function(){{root.querySelectorAll('.box').forEach(function(x){{x.classList.toggle('sel',x===b);}});
d.innerHTML='<h3>'+b.getAttribute('data-title').replace(/</g,'&lt;')+'</h3><p>'+b.getAttribute('data-text').replace(/</g,'&lt;')+'</p>';}});}});}}
wireLayers('sys-layers','sys-detail');wireLayers('ad-layers','ad-detail');}})();</script>"""


def simulate(params: dict, cfg: dict) -> dict:
    """Run the real router on a hand-made state (admin simulator). Inputs are clamped; nothing is stored."""
    from fixengine import config as fx_config, router

    def num(name, lo, hi, default, cast=int):
        try:
            return max(lo, min(hi, cast(params.get(name, default))))
        except (TypeError, ValueError):
            return default
    bug_class = params.get("bug_class") if params.get("bug_class") in ("easy", "medium", "hard") else "medium"
    mode = params.get("mode") if params.get("mode") in ("auto", "ask", "economy") else "auto"
    ft, ht, st, ot = num("free_tries", 0, 5, 3), num("haiku_tries", 0, 10, 2), num("sonnet_tries", 0, 6, 0), num("opus_tries", 0, 3, 0)
    left = (num("left_haiku", 0, 60, 25), num("left_sonnet", 0, 12, 5), num("left_opus", 0, 6, 3))
    strong = params.get("strong_diag") == "1"
    total = ft + ht + st + ot
    last = "opus" if ot else ("sonnet" if st else ("haiku" if ht else ("groq" if ft else "")))
    s = router.RouterInput(bug_class=bug_class, mode=mode, free_tries=ft, haiku_tries=ht, sonnet_tries=st, opus_tries=ot,
                           last_tier=last, strong_diag=strong or bool(st or ot), last_progress=params.get("progress") == "1",
                           spent_inr=num("spent", 0, 100, 0.5, float), total_tries=total, quota_left=left,
                           quota_total=(int(cfg["quotas"]["haiku"]), int(cfg["quotas"]["sonnet"]), int(cfg["quotas"]["opus"])),
                           groq_available=True, cur_info=f"sim-{total}")
    d = router.decide(s, cfg)
    names = {**fx_config.USER_MODE_NAMES, "stop": "Stop → human review"}
    options = [{**o, "name": names.get(o["action"], o["action"])} for o in (d.options or [])]
    return {"action": d.action, "action_name": names.get(d.action, d.action), "reason": d.reason, "forced": d.forced, "options": options}


# ------------------------------------------------------------------------------------------------------------------ admin lessons
def _lesson(anchor, title, tagline, what, why, formula, variables, example, impact, advanced=""):
    var_rows = "".join(f"<tr><td>{v}</td><td>{d}</td></tr>" for v, d in variables)
    var_table = f"<div class='table-wrap'><table class='table mini vars'><tr><th>Symbol</th><th>Meaning</th></tr>{var_rows}</table></div>" if variables else ""
    adv = f"<details class='more'><summary>Go deeper</summary>{advanced}</details>" if advanced else ""
    form = f"<div class='formula'>{formula}</div>" if formula else ""
    return (f"<article class='lesson' id='{E(anchor)}'><h3>{title}</h3><p class='tagline'>{tagline}</p>"
            f"<dl><dt>What it is</dt><dd>{what}</dd><dt>Why we need it</dt><dd>{why}</dd></dl>"
            f"{form}{var_table}<dl><dt>Worked example</dt><dd>{example}</dd><dt>Effect on Agent Daemon</dt><dd>{impact}</dd></dl>{adv}</article>")


def _rs(v) -> str:
    return f"₹{float(v):,.2f}"


def _memo_counts(s, cfg) -> tuple[int, int, int]:
    """Count value() calls for the router's own search from state s, with and without the cache (uses the router's rules)."""
    from fixengine import router
    probs = router.ProbTable(cfg)
    G = float(cfg["router"]["give_up_penalty_inr"])
    depth0 = int(cfg["router"]["max_depth"])
    calls = {"naive": 0, "memo": 0, "hits": 0}

    def key(st, d):
        return (st.haiku_tries, st.sonnet_tries, st.opus_tries, st.last_tier, st.strong_diag, st.haiku_since_strong,
                st.quota_left, round(st.spent_inr, 2), st.last_progress, st.unusable_streak_haiku, st.mode, d)

    def val(st, d, cache):
        calls["naive" if cache is None else "memo"] += 1
        if d <= 0:
            return G
        if cache is not None:
            k = key(st, d)
            if k in cache:
                calls["hits"] += 1
                return cache[k]
        allowed, forced, _ = router.allowed_actions(st, cfg)
        best = G
        for a in ([forced] if forced else allowed):
            nxt = router._next_state(st, a, cfg, router._est_cost(cfg, a, st))
            best = min(best, router._effective_cost(cfg, a, st) + (1 - router._p(a, st, cfg, probs)) * val(nxt, d - 1, cache))
        if cache is not None:
            cache[key(st, d)] = best
        return best

    allowed, _f, _r = router.allowed_actions(s, cfg)
    cache: dict = {}
    for a in allowed:
        nxt = router._next_state(s, a, cfg, router._est_cost(cfg, a, s))
        val(nxt, depth0 - 1, None)
        val(nxt, depth0 - 1, cache)
    return calls["naive"], calls["memo"], calls["hits"]


def _admin_lessons(cfg: dict, learned: dict) -> str:
    from fixengine import config as fx_config, router
    r, tok, caps = cfg["router"], cfg["tokens"], cfg["caps"]
    lam, G, decay, depth = float(r["lambda"]), float(r["give_up_penalty_inr"]), float(r["repeat_decay"]), int(r["max_depth"])
    qt = (int(cfg["quotas"]["haiku"]), int(cfg["quotas"]["sonnet"]), int(cfg["quotas"]["opus"]))
    probs = router.ProbTable(cfg, learned)
    # The example state used throughout: a medium bug, free tries and the Normal floor done, a few paid tries used this month.
    S = router.RouterInput(bug_class="medium", free_tries=3, haiku_tries=2, total_tries=5, last_tier="haiku",
                           quota_left=(max(0, qt[0] - 5), max(0, qt[1] - 1), qt[2]), quota_total=qt, spent_inr=0.5, cur_info="lesson")
    est = {t: router._est_cost(cfg, t, S) for t in router.PAID}
    eff = {t: router._effective_cost(cfg, t, S) for t in router.PAID}
    pp = {t: router._p(t, S, cfg, probs) for t in router.PAID}
    used = {t: 1 - S.quota_left[i] / max(1, qt[i]) for i, t in enumerate(router.PAID)}
    d = router.decide(S, cfg, probs)
    names = {**fx_config.USER_MODE_NAMES, "stop": "Stop (human review)"}
    tin = min(S.repo_tokens, int(tok["max_prompt_tokens"])) + int(tok["retry_overhead_in"])
    tout = int(int(tok["expected_out"]) * float(tok.get("reasoning_out_multiplier", 1.0)))
    ph = cfg["prices_usd_per_m"]["haiku"]
    naive, memo, hits = _memo_counts(router.RouterInput(bug_class="hard", free_tries=3, haiku_tries=2, total_tries=5, last_tier="haiku",
                                                        quota_left=(qt[0], qt[1], qt[2]), quota_total=qt, cur_info="memo"), cfg)
    opt_rows = "".join(f"<tr><td>{E(names.get(o['action'], o['action']))}</td><td>{'—' if not o.get('p') else str(round(o['p'] * 100)) + '%'}</td>"
                       f"<td>{_rs(o.get('try_cost', 0))}</td><td><b>{_rs(o['expected_cost'])}</b></td></tr>" for o in (d.options or []))
    opt_table = (f"<div class='table-wrap'><table class='table mini'><tr><th>Option</th><th>p</th><th>ĉ (provider cost)</th><th>V (estimated total)</th></tr>"
                 f"{opt_rows}</table></div>") if opt_rows else ""
    sonnet_v = next((o["expected_cost"] for o in d.options if o["action"] == "sonnet"), None) if d.options else None

    prob_rows = ""
    for c, row in fx_config.PLACEHOLDER_P.items():
        cells = ""
        for cell in ("groq", "haiku", "haiku_diag", "sonnet", "opus"):
            ok, n = learned.get((c, cell), (0, 0))
            if n >= int(r["min_samples_for_learned"]):
                cells += f"<td><b>{(ok + 1) / (n + 2):.2f}</b><br><small class='muted'>measured, n={n}</small></td>"
            elif n:
                cells += f"<td>{row[cell]:.2f}<br><small class='muted'>{n} samples so far</small></td>"
            else:
                cells += f"<td>{row[cell]:.2f}<br><small class='muted'>starting estimate</small></td>"
        prob_rows += f"<tr><td>{E(c)}</td>{cells}</tr>"
    prob_table = ("<div class='table-wrap'><table class='table mini'><tr><th>bug class</th><th>Low effort</th><th>Normal</th>"
                  f"<th>Normal + diag</th><th>High</th><th>Extra</th></tr>{prob_rows}</table></div>")

    nav = "".join(f"<a href='#{a}'>{t}</a>" for a, t in (("l-cost", "1. Attempt cost"), ("l-ev", "2. Expected cost"), ("l-p", "3. Probability"),
                  ("l-decay", "4. Repeat decay"), ("l-lambda", "5. Quota pressure λ"), ("l-g", "6. Give-up penalty G"), ("l-dp", "7. Dynamic programming"),
                  ("l-depth", "8. Search depth"), ("l-memo", "9. Memoization"), ("l-rules", "10. Hard rules"), ("l-params", "Parameters"), ("l-sim", "Simulator")))
    L = []
    L.append(_lesson("l-cost", "1. The cost of one attempt, ĉ", "What the provider bills us for a single model call.",
        "The rupee cost of one call to one model: tokens sent times the input price plus tokens received times the output price.",
        "Every other formula starts from this number. It is also exactly what the cost ledger records after a real call (with the real token counts).",
        f"ĉ(a) = (tokens_in × price_in(a) + tokens_out × price_out(a)) ÷ 1,000,000 × usd_inr\n"
        f"tokens_in  = min(repo_tokens, {tok['max_prompt_tokens']}) + {tok['retry_overhead_in']} (only after the first try)\n"
        f"tokens_out = {tok['expected_out']} × {tok.get('reasoning_out_multiplier', 1.0)}",
        [("a", "the action, i.e. the mode: haiku = Normal, sonnet = High, opus = Extra (groq = Low effort, free)"),
         ("tokens_in", "estimated prompt size: the relevant code (capped so Normal stays in its cheaper price band) plus error output and a short history after the first try"),
         ("tokens_out", "estimated length of the model's answer (diagnosis + patch)"), ("price_in / price_out", "USD per million tokens, from config"),
         ("usd_inr", f"exchange rate used everywhere: {cfg['usd_inr']}")],
        f"Normal on a 10,000-token repo after earlier tries: tokens_in = {tin:,}, tokens_out = {tout:,}. "
        f"({tin:,} × ${ph['in']} + {tout:,} × ${ph['out']}) ÷ 1,000,000 × {cfg['usd_inr']} = <b>{_rs(est['haiku'])}</b>. "
        f"The same attempt in High costs {_rs(est['sonnet'])} and in Extra {_rs(est['opus'])}.",
        "Higher-priced modes start with a handicap in every comparison; they must make up for it with a much higher chance of success."))
    L.append(_lesson("l-ev", "2. Expected cost, V", "The number the router minimises.",
        "The <i>expected</i> (probability-weighted average) rupees needed to get from the current situation to a fixed bug, counting the attempt "
        "you are about to make and everything that may come after it if it fails.",
        "Choosing the cheapest attempt is wrong when it rarely works: you pay for it and still have the bug. Expected cost weighs each option's price "
        "against its chance of finishing the job.",
        "V(s) = min over allowed actions a of  [ c_eff(a, s) + (1 − p(a, s)) × V(s′) ]\n\nV(fixed) = 0\nV(stop)  = G\n"
        "s′ = the state after a fails (one more try used, spend increased, a stronger diagnosis exists if a was High/Extra)",
        [("s", "the state: tries per mode on this bug, quota left per mode, rupees spent on the bug, last mode, whether a stronger diagnosis exists, bug class"),
         ("a", "an allowed action (a mode, or stop)"), ("c_eff(a, s)", "attempt cost after the quota-pressure multiplier (lesson 5)"),
         ("p(a, s)", "chance this one attempt fixes the bug (lessons 3 and 4)"), ("V(s′)", "the expected cost from the situation after a failure: the recursion"),
         ("G", "the internal value of stopping (lesson 6)")],
        "The customer page showed Low effort with an attempt cost of ₹0.00 but an estimated total of ₹23.90. Here is why that is consistent: "
        "c_eff = 0, so the total is entirely the failure branch, (1 − p) × V(s′). With p = 0.15 for a medium bug, 0.85 × V(s′) = ₹23.90, "
        f"so V(s′) ≈ ₹{23.90 / 0.85:.2f}: the expected cost of whatever comes next, including the chance that a person must step in (G = ₹{G:g}). "
        f"<br><br>Live, from the real router on our example state (medium bug, free tries and the Normal floor done): {opt_table}"
        + (f"Reading the High row: {_rs(sonnet_v)} = c_eff {_rs(eff['sonnet'])} + (1 − {pp['sonnet']:.2f}) × V(after High fails), so "
           f"V(after High fails) ≈ {_rs((sonnet_v - eff['sonnet']) / max(1e-9, 1 - pp['sonnet']))}: cheap, because High leaves a diagnosis that lets "
           f"Normal finish the job." if sonnet_v is not None and pp['sonnet'] < 1 else ""),
        "The router picks the row with the smallest V. A ₹0 attempt can lose to a ₹6 one, and stopping wins when every option's V is above G.",
        "<p>This is the <b>Bellman equation</b> for a cost-minimising Markov decision process: each attempt is a step whose outcome is random "
        "(success ends the process at cost 0; failure moves to s′). The customer calculator uses the same formula but looks only two attempts ahead "
        "and ignores the hard rules, so its numbers differ from the router's.</p>"))
    L.append(_lesson("l-p", "3. Success probability, p", "How likely one attempt in one mode fixes this kind of bug.",
        "A number between 0 and 1: 0.55 means 'about 55 attempts in 100 like this one pass the sandbox check'. It depends on the mode and the bug class "
        "(easy / medium / hard, decided by free rule-based triage). 'Normal + diag' is Normal after High or Extra has written a diagnosis.",
        "Without p the router cannot tell a cheap gamble from a sure thing. It is the weight on the failure branch in lesson 2.",
        f"before {r['min_samples_for_learned']} samples:  p = starting estimate (config)\n"
        f"after  {r['min_samples_for_learned']} samples:  p = (successes + 1) ÷ (tries + 2)",
        [("successes, tries", "counted per (bug class, mode) cell from the fx_attempts ledger: passes vs real attempts"),
         ("+1 / +2", f"Laplace smoothing: a cell with 0 of 0 starts at 0.5 and never hits exactly 0 or 1 from a few unlucky results"),
         ("min samples", f"{r['min_samples_for_learned']}: below that the starting estimate is kept, because 2 results are not evidence")],
        "If Normal fixed 13 of 20 medium bugs, p = (13 + 1) ÷ (20 + 2) = 0.64, replacing the starting estimate 0.55. Current table "
        "(starting estimates unless enough real data exists):" + prob_table,
        "As data accumulates the router adapts to how good each model really is on our customers' bugs. If Normal turns out stronger than "
        "expected, escalations to High become rarer and cheaper months follow."))
    L.append(_lesson("l-decay", "4. Repeat decay", "Trying the same thing again is worth less.",
        "Each earlier failure of the same mode on this bug multiplies that mode's chance by the decay factor.",
        "A model that failed once usually fails again on the same bug in the same way. Without decay the router would keep picking the cheap mode forever.",
        f"p(a, s) = p_class(a) × {decay} ^ (earlier failures of a on this bug)",
        [("p_class(a)", "the probability from lesson 3"), (f"{decay}", "repeat_decay from config"), ("earlier failures", "tries of that mode already spent on this bug")],
        f"Normal on a medium bug: first try {fx_config.PLACEHOLDER_P['medium']['haiku']:.2f}, after 1 failure "
        f"{fx_config.PLACEHOLDER_P['medium']['haiku'] * decay:.2f}, after 2 failures {fx_config.PLACEHOLDER_P['medium']['haiku'] * decay ** 2:.2f}. "
        f"In our example state Normal has failed twice, so its p is {pp['haiku']:.2f}.",
        "Pushes the router to escalate after repeated failures, and works together with the hard rule that a retry must carry new information."))
    L.append(_lesson("l-lambda", "5. Quota pressure, λ", "Saving scarce tries for the bugs that need them.",
        "A multiplier on the attempt cost that grows as the customer uses up that mode's monthly quota. It changes the comparison, not the bill.",
        f"A customer has {qt[1]} High and {qt[2]} Extra tries but {qt[0]} Normal. If the router spent High tries freely on the first bugs of the month, "
        "nothing would be left for a hard bug on day 25.",
        f"c_eff(a) = ĉ(a) × (1 + λ × used_fraction(a))        λ = {lam}\nused_fraction(a) = 1 − tries_left(a) ÷ tries_total(a)",
        [("λ (lambda)", f"how strongly usage counts. {lam} means a fully used mode looks {1 + lam:g}× as expensive"),
         ("used_fraction", "0 at the start of the month, 1 when that mode's quota is gone (bought pack tries count in the total)")],
        f"High: ĉ = {_rs(est['sonnet'])}. With {qt[1] - S.quota_left[1]} of {qt[1]} used (used_fraction {used['sonnet']:.2f}), "
        f"c_eff = {_rs(est['sonnet'])} × (1 + {lam} × {used['sonnet']:.2f}) = <b>{_rs(eff['sonnet'])}</b>. With 5 of 6 used it would be "
        f"{_rs(est['sonnet'] * (1 + lam * 5 / max(1, qt[1])))}.",
        "Early in the month the router escalates readily; late in the month it prefers Normal and saves High and Extra. Low effort is free and never adjusted."))
    L.append(_lesson("l-g", "6. Give-up penalty, G", "The price we put on 'a person has to step in'.",
        f"A fixed internal number, ₹{G:g}, used as the value of stopping and sending the bug to human review.",
        "Without it, stopping would cost 0 and the router would always stop. With it, the router keeps trying only while the expected cost of trying is "
        "lower than G, and stops when further attempts are a bad bet.",
        f"V(stop) = G = ₹{G:g}\nalso: V(any state at the search horizon) = G",
        [("G", "give_up_penalty_inr in config")],
        f"If every remaining option has V above ₹{G:g} (for example a hard bug where only Extra is left and it is nearly used up), the router chooses Stop "
        "and the customer gets a report.",
        "<b>G is not billing.</b> The customer is never charged ₹30, and no money moves when a bug goes to human review. Raise G and the agent tries harder "
        "(more spend, fewer human reviews); lower it and the agent gives up sooner."))
    L.append(_lesson("l-dp", "7. Dynamic programming", "Solving a big decision by reusing answers to smaller ones.",
        "A technique for problems where the best answer is built from best answers to sub-problems. Here the sub-problem is 'what is V of the state "
        "after this attempt fails?', which is the same kind of question one step later.",
        "Choosing the next mode well requires knowing how good the situations after it are, which requires knowing the situations after those, and so on. "
        "Writing V(s) in terms of V(s′) turns that into one short recursive function.",
        "value(state, depth):\n    if depth == 0: return G\n    best = G                       # stopping is always possible\n"
        "    for a in allowed_actions(state):          # hard rules filter first\n"
        "        best = min(best, c_eff(a) + (1 − p(a)) × value(next_state(state, a), depth − 1))\n    return best",
        [("allowed_actions", "router.allowed_actions(): quota, per-bug cap, Normal floor, drop-back, no-repeat rules"),
         ("next_state", "router._next_state(): one more try of a, spend + ĉ, last_tier = a, strong diagnosis if a was High/Extra")],
        "Four modes, two outcomes each. From a medium bug after the free tries: try Normal → pass (cost stops) or fail → from there try Normal again, "
        "High or Extra → each passes or fails → ... The tree of 'what if' paths grows quickly; the DP evaluates it bottom-up and returns the best first move. "
        f"On our example state the result was <b>{E(names.get(d.action, d.action))}</b> ({E(d.reason)}).",
        "This is how the router compares 'cheap now, maybe expensive later' against 'expensive now, probably done', in milliseconds, on every attempt.",
        "<p>Why 'like Dijkstra'? Dijkstra finds the cheapest path when every edge has a fixed cost. Here each edge (an attempt) has a cost but leads to "
        "success or failure at random, so instead of a shortest path we compute an expected cost. The structure — optimal choices built from optimal "
        "sub-choices — is the same principle of optimality.</p>"))
    L.append(_lesson("l-depth", "8. Search depth", "How many attempts ahead the router looks.",
        f"The recursion stops after {depth} levels. A state at the horizon is valued at G, i.e. 'if it is still broken after {depth} more attempts, assume a person steps in'.",
        "Without a limit the search could grow without end (there is always 'one more try'). Six levels covers every realistic path, because the per-bug cap "
        f"is {caps['per_bug_max_tries']} tries anyway.",
        f"value(s, 0) = G        max_depth = {depth}",
        [("max_depth", "router.max_depth in config")],
        "Example: a bug after the free tries. The router imagines Normal → Normal → High → Normal(with High's diagnosis) → Extra → Normal, scores every such "
        "sequence with its probabilities, and only then decides the first step. With depth 1 it could not see that High's diagnosis makes the next Normal "
        "attempt more likely to succeed.",
        "Deeper search sees more strategic plays (like using High for its diagnosis then dropping back to Normal) at the price of more computation; "
        "memoization keeps that price tiny."))
    L.append(_lesson("l-memo", "9. Memoization", "Never calculate the same situation twice.",
        "Storing the result of value(state, depth) in a dictionary the first time it is computed, and returning the stored answer when the same "
        "state comes up again.",
        "Different orders of attempts can lead to the same situation (same tries, same spend, same last mode). Without the cache each is recomputed, and the "
        "work grows exponentially with depth.",
        "key = (tries per mode, last mode, strong diagnosis?, quota left, spend, progress, unusable streak, setting, depth)\n"
        "if key in cache: return cache[key]",
        [("cache", "a plain dict created per decision inside router.solve(); it is thrown away afterwards, so it never goes stale")],
        f"Live count for a hard bug just after the Normal floor: <b>{naive}</b> calls to value() without the cache, <b>{memo}</b> with it "
        f"({hits} answered from the cache). "
        + ("Here few paths meet again, because spend and last mode usually differ, so the saving is modest; it grows with more open choices." if naive - memo < naive * 0.2
           else "That is the work memoization saves on every single decision."),
        "Keeps every routing decision in the low milliseconds, so it can run before each attempt and be logged in full for audits."))
    rules = [("Per-bug caps", f"{caps['per_bug_max_tries']} tries or {_rs(caps['per_bug_cost_inr'])} on one bug → stop.", "safety"),
             ("Your pick wins", "If the customer chose a mode at a warning, use it (inside their quota).", "customer control"),
             ("Free first", f"Up to {r['free_tries']} Low effort tries before any paid mode.", "cost"),
             ("Normal floor", f"At least {r['haiku_floor']} Normal tries before High/Extra ({r['haiku_floor_max_with_progress']} if progressing); waived after "
              f"{r['unusable_waives_floor_after']} unusable answers.", "quota balance: 30 Normal vs 6 High"),
             ("Drop back", f"After High/Extra fails, Normal tries again with its diagnosis (up to {r['drop_back_tries']}).", "cheap model finishes the job"),
             ("No repeats", "Never the same mode with the same information.", "no wasted tries"),
             ("Quota and pauses", "Never past the quota, a paused mode, or the budget level. Economy never uses High/Extra.", "money")]
    rule_rows = "".join(f"<tr><td><b>{E(a)}</b></td><td>{E(b)}</td><td>{E(c)}</td></tr>" for a, b, c in rules)
    L.append(_lesson("l-rules", "10. Hard rules vs the optimizer", "Business rules decide first; the maths decides the rest.",
        "Rules in router.decide() and router.allowed_actions() that either force an action (forced=True) or remove options before the DP runs.",
        "Some things are policy, not arithmetic: the customer's choice, our caps, and the plan's promise to use Normal before High.",
        "decide(s):\n    hard stops (caps)            → stop, forced\n    customer's pick              → that mode, forced\n"
        "    free tries left              → Low effort, forced\n    allowed, forced = allowed_actions(s)\n"
        "    if forced                    → forced action (e.g. Normal floor, drop back)\n    else                         → optimizer: argmin V",
        [], "<div class='table-wrap'><table class='table mini'><tr><th>Rule</th><th>What it does</th><th>Why</th></tr>" + rule_rows + "</table></div>",
        "Every logged decision says which one decided it: 'forced' (a rule) or 'optimizer' (lowest expected cost). The simulator below shows the same."))
    return f"<div class='lesson-nav'>{nav}</div>" + "".join(L)
