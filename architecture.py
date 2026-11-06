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
    ("router", "Pick the cheapest smart mode", "The router compares Low effort, Normal, High and Extra and picks the one with the lowest expected cost to reach a working fix.", "expected-cost DP"),
    ("model", "AI writes a small patch", "The model only reads the relevant files and the error, and only returns text. It cannot run anything or touch GitHub.", "text in, text out"),
    ("policy", "Safety rules", "Our code checks the patch: at most 3 files and 40 lines, never tests, CI files, build configs, dependencies or secrets.", "policy gate"),
    ("retest", "Same check, patched code", "The patched repo goes through the exact check that failed. Not green? Back to the router with what was learned.", "proof"),
    ("pushfix", "Push the fix to GitHub", "A new branch <code>agent-daemon/fix-…</code> with a pull request into your branch. Auto mode merges it once proven; otherwise you review it.", "PR · auto-merge"),
]
LIVE_FLOW = [
    ("app", "Your live app crashes", "A real user hits a bug in the deployed app.", "production"),
    ("report", "Error reported", "A tiny reporter in the app (added automatically for Python apps) sends the error and stack trace to Agent Daemon.", "/ingest"),
    ("group", "Grouped into an incident", "Repeats of the same error become one incident with a count, so you are not spammed.", "dedupe"),
    ("repro", "Reproduce in the sandbox", "We download your branch and run the same install → build → tests → start-up check to see what fails today.", "baseline"),
    ("router2", "Router, model, policy, re-test", "Exactly the same fix loop as the push guard: cheapest smart mode first, safety rules, proof in the sandbox.", "shared engine"),
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
    loop = ("<div class='loop'>↺ Not green after the re-test? The agent goes back to the router with the new error and the stronger "
            "model's diagnosis, never repeating the same try with the same information, until it is fixed or a cap is reached "
            "(then a human gets a clear report).</div>")
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
  // router playground (one step of the expected-cost comparison, with the plan's placeholder numbers)
  var data=document.getElementById('arch-data'); if(!data){return;}
  var D=JSON.parse(data.textContent);
  var cls=document.getElementById('pg-class'), used=document.getElementById('pg-used'), usedOut=document.getElementById('pg-used-out'), bars=document.getElementById('pg-bars');
  function draw(){
    var c=cls.value, u=+used.value/100; usedOut.textContent=Math.round(u*100)+'%';
    function cost(t){return t.cost*(1+D.lambda*(t.key==='groq'?0:u));}
    function p(t,fails){return D.p[c][t.key]*Math.pow(D.decay,fails);}
    // two-step lookahead: try m; if it fails, take the best second try (or give up for G)
    function second(first){var best=D.G;D.tiers.forEach(function(n){var f=(n.key===first.key)?1:0;
      var v=cost(n)+(1-p(n,f))*D.G; if(v<best){best=v;}});return best;}
    var rows=D.tiers.map(function(t){var pp=p(t,0);var ev=cost(t)+(1-pp)*second(t);return {name:t.name,ev:ev,p:pp,cost:cost(t)};});
    var best=rows.reduce(function(a,b){return b.ev<a.ev?b:a;}); var max=Math.max.apply(null,rows.map(function(r){return r.ev;}));
    bars.innerHTML=rows.map(function(r){return '<div class="bar'+(r===best?' best':'')+'"><b>'+r.name+'</b><i style="width:'+Math.max(4,100*r.ev/max)+'%"></i><span>₹'+r.ev.toFixed(1)+'</span></div>'+
      '<div class="muted bar-note">chance it works '+Math.round(r.p*100)+'% · cost of one try ₹'+r.cost.toFixed(2)+'</div>';}).join('')+
      '<p class="muted">Lowest expected cost: <b>'+best.name+'</b>. Bars show the expected rupees to reach a fix, looking two tries ahead (giving up costs ₹'+D.G+'). The real router looks '+D.depth+' tries ahead and applies the hard rules on top.</p>';
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
    return f"""<section class='section' id='router'><div class='eyebrow'>The algorithm</div><h2>How the agent decides which AI to use</h2>
<div class='algo'><div>
<p>Think of fixing a bug as a trip with several possible routes. Cheap routes (Low effort, Normal) often get there; expensive ones (High, Extra)
get there more often. Agent Daemon uses an <b>expected-cost optimizer</b>: a small <b>dynamic program</b>, the same "cheapest route" idea as
<b>Dijkstra's algorithm</b>, adapted to steps that can succeed <i>or fail</i>. For every possible next move it adds what the try costs to what
happens if it fails, weighted by how likely that is, and picks the lowest total.</p>
<div class='formula'>V(state) = min over modes m of
           effective_cost(m) + (1 − p(m)) × V(state after m fails)

V(fixed)      = 0
V(give up)    = G   (send it to a human)

effective_cost(m) = cost of one try × (1 + λ × share of that
                    mode's monthly tries already used)</div>
<p class='muted'>On top of the maths sit hard rules: a free first look, Normal at least twice before High (you have {q['normal']} Normal but only
{q['high']} High tries), drop back to Normal with the stronger model's diagnosis, never the same try twice with the same information,
per-bug caps, and never past your quota. The success chances start as the plan's estimates and are replaced by what the agent actually
measures.</p></div>
<div class='card play'><h3>Try it</h3><p class='muted'>One step of the comparison, using the plan's starting numbers.</p>
<label for='pg-class'>How hard is the bug?</label><select id='pg-class'><option value='easy'>Easy (typo, missing import, config)</option>
<option value='medium' selected>Medium (wrong logic, a few files)</option><option value='hard'>Hard (async, state, many files)</option></select>
<label for='pg-used'>Paid tries already used this month: <span id='pg-used-out'>20%</span></label>
<input id='pg-used' type='range' min='0' max='100' value='20'>
<div class='bars' id='pg-bars'></div></div></div></section>
<script type='application/json' id='arch-data'>{_playground_data(cfg)}</script>"""


def user_page_html(cfg: dict | None = None) -> str:
    from fixengine import config as fx_config
    cfg = cfg or fx_config.load()
    legend = "".join(f"<div><b>{E(t)}</b><span class='muted'>{E(d)}</span></div>" for t, d in STAGES)
    return f"""<style>{CSS}</style><div class='arch'>
<section class='section'><div class='eyebrow'>How it works</div>
<h1>Push your code. The agent catches what broke, fixes it, and pushes the fix back.</h1>
<p class='lead'>Two ways in, one fix engine. Tap any box to read what happens there, or press play to follow a bug from push to fix.</p>
<div class='arch-tabs' role='tablist'>
<button class='arch-tab' role='tab' aria-selected='true' aria-controls='panel-push'>Push guard (new · catches bugs before you deploy)</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='panel-live'>Live error watch (classic · after deploy)</button></div>
<div class='arch-panel flow-wrap' id='panel-push' role='tabpanel'>
<div class='arch-controls'><button class='button primary arch-play' type='button'>▶ Play the flow</button><span class='arch-narr' aria-live='polite'></span></div>
{_flow_html(PUSH_FLOW, 'push')}<div class='arch-detail' aria-live='polite'></div>
<div class='stack-row'><span>Python</span><span>JavaScript</span><span>TypeScript</span><span>React · Next.js · Node</span><span>Java · Maven · Gradle</span><span>HTML · CSS</span><span>mixed repos</span></div></div>
<div class='arch-panel flow-wrap' id='panel-live' role='tabpanel' hidden>
<div class='arch-controls'><button class='button primary arch-play' type='button'>▶ Play the flow</button><span class='arch-narr' aria-live='polite'></span></div>
{_flow_html(LIVE_FLOW, 'live')}<div class='arch-detail' aria-live='polite'></div></div>
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
</div><script>{SCRIPT}</script>"""


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
    params = [("λ (quota pressure)", r["lambda"]), ("G (give-up penalty, ₹)", r["give_up_penalty_inr"]), ("search depth", r["max_depth"]),
              ("free tries first", r["free_tries"]), ("Normal floor", r["haiku_floor"]), ("drop-back tries", r["drop_back_tries"]),
              ("repeat decay", r["repeat_decay"]), ("min samples before learned p", r["min_samples_for_learned"]),
              ("per-bug cap ₹ / tries", f"{caps['per_bug_cost_inr']} / {caps['per_bug_max_tries']}"),
              ("user ceiling ₹/month", caps["user_month_ceiling_inr"]), ("budget B / credits ₹", f"{b['b_inr']} / {b['credits_inr']}"),
              ("kill-switch levels (× B)", ", ".join(str(x) for x in b["levels"])), ("max prompt tokens", tok["max_prompt_tokens"]),
              ("USD → INR", cfg["usd_inr"])]
    param_rows = "".join(f"<tr><td class='k'>{E(k)}</td><td class='v'>{E(v)}</td></tr>" for k, v in params)
    sim = """<form id='sim' class='card play' onsubmit='return false'><h3>Router simulator</h3>
<p class='muted'>Calls the real <code>router.decide()</code> on the server with this state. Nothing is saved, no model is called.</p>
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
var rows=(d.options||[]).map(function(o){return '<tr><td>'+o.name+'</td><td>'+(o.p===null||o.p===undefined?'—':Math.round(o.p*100)+'%')+'</td><td>₹'+(o.try_cost===undefined?'—':o.try_cost)+'</td><td><b>₹'+o.expected_cost+'</b></td></tr>';}).join('');
out.innerHTML='<p><b>Decision: '+d.action_name+'</b> '+(d.forced?'(hard rule)':'(optimizer)')+' — '+d.reason+'</p>'+(rows?'<table class="mini"><tr><th>Option</th><th>p</th><th>try cost</th><th>expected cost</th></tr>'+rows+'</table>':'');
}).catch(function(){out.textContent='Could not reach the simulator.';});});})();</script>"""
    return f"""<style>{CSS}</style><div class='arch'>
<section class='section'><p><a href='/admin'>← Admin</a></p><div class='eyebrow'>Admin · architecture</div>
<h1>System architecture, model adapters and the cost function</h1>
<p class='lead'>Live numbers below come straight from <code>fixengine/config.py</code> (plus <code>FIXENGINE_CONFIG_JSON</code> overrides) and the cost ledger.</p>
<div class='arch-tabs' role='tablist'>
<button class='arch-tab' role='tab' aria-selected='true' aria-controls='a-system'>General architecture</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='a-flows'>Request flows</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='a-adapters'>Model adapters</button>
<button class='arch-tab' role='tab' aria-selected='false' aria-controls='a-cost'>Cost function &amp; router</button></div>
<div class='arch-panel' id='a-system' role='tabpanel'><p class='muted'>Click a box for details.</p>{_layers_html(SYSTEM_LAYERS, 'sys-layers')}
<div class='arch-detail' id='sys-detail'><h3>Golden rule</h3><p>Only the router chooses models; every model call passes the quota and budget guard and writes one ledger row. Customer code runs only in the sandbox.</p></div></div>
<div class='arch-panel' id='a-flows' role='tabpanel' hidden>
<h3>Push guard (v3)</h3><div class='flow-wrap'><div class='arch-controls'><button class='button primary arch-play' type='button'>▶ Play</button><span class='arch-narr'></span></div>{_flow_html(PUSH_FLOW, 'apush')}<div class='arch-detail'></div></div>
<h3>Live error watch (classic)</h3><div class='flow-wrap'><div class='arch-controls'><button class='button primary arch-play' type='button'>▶ Play</button><span class='arch-narr'></span></div>{_flow_html(LIVE_FLOW, 'alive')}<div class='arch-detail'></div></div></div>
<div class='arch-panel' id='a-adapters' role='tabpanel' hidden><p class='muted'>Every model call goes down this stack. Click a box for details.</p>{_layers_html(ADAPTER_LAYERS, 'ad-layers')}
<div class='arch-detail' id='ad-detail'><h3>One interface</h3><p>Adapters take text and return text plus token counts. They never get tools, the network is only the provider API, and every error is classified and redacted.</p></div>
<h3>Tiers, models, prices and quotas</h3><div class='table-wrap'><table class='table mini'><tr><th>Mode</th><th>Model id</th><th>USD per M tokens (in / out)</th><th>Quota</th></tr>{prices}</table></div></div>
<div class='arch-panel' id='a-cost' role='tabpanel' hidden><div class='algo'><div>
<div class='formula'>V(s) = min_a [ c_eff(a, s) + (1 − p(a, s)) · V(s' | a failed) ]
V(fixed) = 0      V(stop) = G = ₹{E(r['give_up_penalty_inr'])}

c_eff(a, s) = ĉ(a, s) · (1 + λ · used_fraction(a))        λ = {E(r['lambda'])}
ĉ(a, s)     = price_in(a) · tokens_in + price_out(a) · tokens_out   (₹)
tokens_in   = min(repo_tokens, {E(tok['max_prompt_tokens'])}) + retry_overhead ({E(tok['retry_overhead_in'])} after the 1st try)
p(a, s)     = p_class(a) · {E(r['repeat_decay'])}^(earlier fails of a)   (haiku_diag after a strong diagnosis)
p_class     = (successes + 1) / (tries + 2) once a cell has ≥ {E(r['min_samples_for_learned'])} samples, else the placeholder
depth       = {E(r['max_depth'])}, memoised: runs in milliseconds</div>
<h3>Hard rules (applied before the optimizer)</h3><ol class='muted'>
<li>Per-bug caps: {E(caps['per_bug_max_tries'])} tries or ₹{E(caps['per_bug_cost_inr'])} → stop.</li>
<li>User's pick at a warning wins (inside quota).</li><li>Free first: up to {E(r['free_tries'])} Low effort tries.</li>
<li>Normal floor: {E(r['haiku_floor'])} tries before High/Extra ({E(r['haiku_floor_max_with_progress'])} if progressing); waived after {E(r['unusable_waives_floor_after'])} unusable answers.</li>
<li>Drop back to Normal after High/Extra, up to {E(r['drop_back_tries'])} tries with the stronger diagnosis.</li>
<li>Never repeat a mode with the same information. Never past quota; Economy never escalates.</li></ol></div>
<div><h3>Parameters</h3><div class='table-wrap'><table class='table mini'>{param_rows}</table></div></div></div>
<h3>Success probabilities p(mode | bug class)</h3><div class='table-wrap'><table class='table mini'><tr><th>class</th><th>Low effort</th><th>Normal</th><th>Normal + diag</th><th>High</th><th>Extra</th></tr>{prob_rows}</table></div>
{sim}</div>
</section></div><script>{SCRIPT}
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
