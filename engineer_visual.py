"""The 'How the agent fixes a problem' section of /how-it-works: an interactive, animated explanation of the engineer.

A five-step pipeline you can click through (or let it play), with a terminal that replays a real-looking case step by step, the
Normal -> High -> Extra ladder with what each run may cost, and the two decisions that matter to an owner: is it a code problem,
and is the agent sure. No libraries; one inline script (allowed on this page); respects prefers-reduced-motion.
"""
from __future__ import annotations

import html
import json

E = lambda v: html.escape(str(v if v is not None else ""), quote=True)

STEPS = [
    ("📖", "1. Normal goes first", "Reads everything",
     "Every case starts with the low-cost Normal engineer. It reads your whole code base, the error or your request, your live site "
     "and your recent commits, before it changes anything.",
     [("cmd", "case: \"Isaiah 1 is not loading\""), ("out", "reading the whole code base · 34 files"),
      ("cmd", "open_live_page /isaiah/1"), ("bad", "GET bible-api.com/isaiah 1  →  404 Not Found"),
      ("cmd", "recent_commits src/App.jsx"), ("out", "a1b2c3d  'rename chapter helper'  (2 days ago)")]),
    ("🧭", "2. Is it a code problem?", "Decides first",
     "If the cause is outside your code (a key missing on your host, a database or sign-in setting, a service that is down) it stops "
     "right away and writes you simple numbered steps. No money is spent on a stronger AI.",
     [("cmd", "is this a code problem?"), ("out", "the URL is built with a space: \"isaiah\" + \" \" + \"1\""),
      ("ok", "yes: src/App.jsx, line 212 (introduced by a1b2c3d)"), ("dim", "(not code? → \"Needs you\": step-by-step instructions)")]),
    ("🛠", "3. Fix and prove", "Edits, then runs your checks",
     "It edits as much as the fix needs, runs install, build, tests and start-up in the sandbox, then our own check runs again on the "
     "final files. Big judgement calls (deleting a feature, a placeholder) are shown to you before they go live.",
     [("cmd", "edit src/App.jsx   book + \" \" + ch   →   book + \"/\" + ch"), ("cmd", "run_checks"),
      ("ok", "install ✓   build ✓   tests ✓   start ✓   browser journey ✓"), ("ok", "safety rules ✓   our own sandbox run ✓")]),
    ("⇪", "4. Stronger only if needed", "Normal → High → Extra",
     "Most cases end with Normal. Only if it cannot finish does High take over, starting from everything already found. Extra is the "
     "last step, and only after asking you. A run that reaches its limit simply continues: nothing is thrown away.",
     [("ok", "Normal finished the case: no stronger model was needed"), ("dim", "(otherwise: High continues with the findings and edits)"),
      ("dim", "(Extra: only after you press \"Yes, go ahead\")")]),
    ("🚀", "5. Sure or not sure", "Push, or ask you",
     "In Auto mode a fix the agent is sure about (all checks green, low risk, nothing left for you) goes to your branch after your "
     "GitHub tests pass and, for anything on the screen, a real Chrome on GitHub shows it working at phone and desktop size. Then your "
     "live site is checked. Not sure? You get a pull request, the reason in plain words, and how to merge it.",
     [("cmd", "sure?  checks green · low risk · nothing for you"), ("ok", "GitHub tests ✓  real browser ✓  →  pushed to main"),
      ("cmd", "live check /isaiah/1"), ("ok", "200 OK · no errors   →   Verified on your live site")]),
]

CSS = """
.eng{--eng-v:#b06cff;--eng-c:#ff4f6a;--eng-g:#62e6a4;--eng-a:#ffc857;--eng-line:#3a2338}
.eng .eng-lead{max-width:780px}
.eng-stage{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:22px;margin:26px 0 8px;align-items:stretch}
.eng-steps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;position:relative}
.eng-steps:before{content:"";position:absolute;left:27px;top:24px;bottom:24px;width:2px;background:linear-gradient(var(--eng-v),var(--eng-c),var(--eng-g));opacity:.45}
.eng-step{position:relative;display:flex;gap:14px;align-items:center;width:100%;text-align:left;cursor:pointer;padding:12px 14px;border-radius:16px;
  background:#140b20;border:1px solid var(--eng-line);color:inherit;font:inherit;transition:transform .25s,border-color .25s,background .25s,box-shadow .25s}
.eng-step:hover{transform:translateX(3px);border-color:#5b3a73}
.eng-step .ico{flex:none;display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#0b0612;border:2px solid #4a2d60;font-size:15px;z-index:1}
.eng-step b{display:block;font-size:15px;color:#f4ecff}.eng-step small{display:block;color:#a99dbb;font-size:12.5px;margin-top:2px}
.eng-step.on{background:linear-gradient(120deg,#2a1240,#1a0d2a);border-color:var(--eng-v);box-shadow:0 0 0 1px #b06cff55,0 10px 40px #9a4dff30}
.eng-step.on .ico{border-color:var(--eng-g);box-shadow:0 0 16px #62e6a488}
.eng-step .bar{position:absolute;left:0;bottom:0;height:3px;border-radius:0 0 16px 16px;background:linear-gradient(90deg,var(--eng-v),var(--eng-c));width:0}
.eng-step.on .bar{animation:engbar 4.6s linear forwards}
@keyframes engbar{to{width:100%}}
.eng-view{display:flex;flex-direction:column;gap:12px;min-width:0}
.eng-term{flex:1;min-height:250px;border-radius:16px;background:#07040c;border:1px solid #2b1838;box-shadow:inset 0 0 60px #9a4dff14,0 18px 50px #0007;overflow:hidden}
.eng-term .top{display:flex;align-items:center;gap:7px;padding:10px 14px;border-bottom:1px solid #1e1029;background:#0d0716}
.eng-term .top i{width:10px;height:10px;border-radius:50%;background:#ff5f57}.eng-term .top i:nth-child(2){background:#febc2e}.eng-term .top i:nth-child(3){background:#28c840}
.eng-term .top span{margin-left:8px;font-size:12px;color:#8f84a3;font-family:Consolas,Menlo,monospace}
.eng-term pre{margin:0;padding:16px 18px;font:13px/1.75 Consolas,Menlo,monospace;color:#d9d0e8;white-space:pre-wrap;word-break:break-word}
.eng-term .l{display:block;opacity:0;transform:translateY(4px);animation:engline .35s ease forwards}
.eng-term .cmd:before{content:"› ";color:var(--eng-v)}.eng-term .cmd{color:#efe7ff}
.eng-term .out{color:#a99dbb;padding-left:16px}.eng-term .ok{color:var(--eng-g);padding-left:16px}.eng-term .ok:before{content:"✓ "}
.eng-term .bad{color:#ff8a8a;padding-left:16px}.eng-term .bad:before{content:"✗ "}.eng-term .dim{color:#6f6582;padding-left:16px;font-style:italic}
.eng-term .cur{display:inline-block;width:8px;height:15px;background:var(--eng-g);vertical-align:-2px;animation:engblink 1s steps(2) infinite}
@keyframes engline{to{opacity:1;transform:none}}@keyframes engblink{50%{opacity:0}}
.eng-cap{padding:14px 16px;border-radius:14px;background:#120a1bcc;border:1px solid var(--eng-line);color:#d8cde6;font-size:14.5px;line-height:1.6}
.eng-cap h3{margin:0 0 6px;font-size:17px;color:#fff}
.eng-ctl{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.eng-ctl .muted{font-size:12.5px}
.eng-ladder{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:12px;align-items:stretch;margin:34px 0 10px}
.eng-tier{position:relative;padding:18px;border-radius:18px;background:linear-gradient(160deg,#1a0e28,#0e0817);border:1px solid var(--eng-line);overflow:hidden}
.eng-tier:after{content:"";position:absolute;inset:auto -40% -60% auto;width:180px;height:180px;border-radius:50%;filter:blur(40px);opacity:.35;background:var(--tc)}
.eng-tier .badge{display:inline-block;font-size:11px;letter-spacing:.12em;text-transform:uppercase;padding:4px 10px;border-radius:999px;border:1px solid var(--tc);color:var(--tc)}
.eng-tier h4{margin:10px 0 4px;font-size:22px;color:#fff;font-family:var(--serif,inherit)}.eng-tier p{margin:6px 0;color:#c9bedb;font-size:14px;line-height:1.55}
.eng-tier .cost{font-size:13px;color:#fff;background:#ffffff10;border:1px solid #ffffff1a;border-radius:10px;padding:6px 10px;display:inline-block;margin-top:6px}
.eng-tier.most{border-color:#2c6b57;box-shadow:0 0 0 1px #62e6a433,0 12px 40px #62e6a41a}
.eng-arrow{display:grid;place-items:center;color:#8f84a3;font-size:22px}
.eng-split{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:30px 0 8px}
.eng-out{padding:18px;border-radius:18px;border:1px solid var(--eng-line);background:#120a1b}
.eng-out h4{margin:0 0 8px;font-size:18px;color:#fff;display:flex;gap:10px;align-items:center}
.eng-out p{margin:6px 0;color:#c9bedb;font-size:14px;line-height:1.55}
.eng-out.yes{border-color:#2c6b57;background:linear-gradient(160deg,#0f2a20,#0c0f14)}.eng-out.no{border-color:#7a5a20;background:linear-gradient(160deg,#2a210c,#0f0c14)}
.eng-out ol{margin:8px 0 0 20px;padding:0;color:#e9dcc0;font-size:13.5px}.eng-out li{margin:4px 0}
.eng-chips{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0 4px}
.eng-chips span{padding:8px 14px;border-radius:999px;background:#1a0f27;border:1px solid #4a2d60;color:#efe7ff;font-size:13.5px}
.eng-chips span b{color:var(--eng-g)}
.eng-foot{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:22px}.eng-foot article{padding:16px;border-radius:14px;background:#0f0817;border:1px solid var(--eng-line)}
.eng-foot h4{margin:0 0 6px;color:#fff}.eng-foot p{margin:0;color:#a99dbb;font-size:13.5px;line-height:1.55}
@media(max-width:860px){.eng-stage{grid-template-columns:1fr}.eng-ladder{grid-template-columns:1fr}.eng-arrow{transform:rotate(90deg);height:18px}
  .eng-split,.eng-foot{grid-template-columns:1fr}.eng-term{min-height:210px}}
@media(prefers-reduced-motion:reduce){.eng-term .l{animation:none;opacity:1;transform:none}.eng-step.on .bar{animation:none;width:100%}.eng-term .cur{animation:none}}
"""

SCRIPT = """(function(){var root=document.getElementById('eng');if(!root)return;
var data=JSON.parse(document.getElementById('eng-data').textContent),btns=root.querySelectorAll('.eng-step'),pre=root.querySelector('.eng-term pre'),
cap=root.querySelector('.eng-cap'),title=root.querySelector('.eng-term .top span'),play=root.querySelector('.eng-play'),i=0,timer=null,
still=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
function show(n){i=n;btns.forEach(function(b,k){b.classList.toggle('on',k===n);var bar=b.querySelector('.bar');if(bar){bar.style.animation='none';bar.offsetHeight;bar.style.animation='';}});
var s=data[n];title.textContent='agent-daemon · step '+(n+1)+' of '+data.length;
pre.innerHTML=s.lines.map(function(l,k){return '<span class="l '+l[0]+'" style="animation-delay:'+(still?0:k*0.42)+'s">'+esc(l[1])+'</span>';}).join('')+'<span class="cur"></span>';
cap.innerHTML='<h3>'+esc(s.title)+'</h3>'+esc(s.text);}
function next(){show((i+1)%data.length);}
function start(){if(timer||still)return;timer=setInterval(next,4600);if(play)play.textContent='❚❚ Pause';}
function stop(){clearInterval(timer);timer=null;if(play)play.textContent='▶ Play';}
btns.forEach(function(b,k){b.addEventListener('click',function(){stop();show(k);});});
if(play)play.addEventListener('click',function(){timer?stop():(next(),start());});
show(0);
if('IntersectionObserver' in window){new IntersectionObserver(function(es){es.forEach(function(e){e.isIntersecting?start():stop();});},{threshold:.35}).observe(root);}else{start();}
})();"""


def section(cfg: dict, quotas: dict, try_definition: str, human_needed: str) -> str:
    caps = (cfg.get("agent") or {}).get("max_inr_per_run") or {}
    cap = lambda t: f"up to about ₹{int(caps.get(t, 0))} a run" if isinstance(caps, dict) and caps.get(t) else "a fixed limit per run"
    data = [{"title": t, "text": txt, "lines": lines} for _i, t, _s, txt, lines in STEPS]
    steps = "".join(f"<li><button type='button' class='eng-step{' on' if k == 0 else ''}'><span class='ico'>{ico}</span>"
                    f"<span><b>{E(t)}</b><small>{E(sub)}</small></span><span class='bar'></span></button></li>"
                    for k, (ico, t, sub, _txt, _l) in enumerate(STEPS))
    return f"""<style>{CSS}</style><section class='section eng' id='router'><div id='eng'>
<div class='eyebrow'>The engineer</div><h2>How the agent fixes a problem</h2>
<p class='lead eng-lead'>An AI engineer works on a copy of your code the way a developer would: it reads everything, reproduces the
problem, fixes the cause and runs your checks. It starts with the low-cost mode and calls a stronger one only when it has to.
Click a step, or watch it replay a real case.</p>
<div class='eng-stage'><ol class='eng-steps'>{steps}</ol>
<div class='eng-view'><div class='eng-term' aria-live='polite'><div class='top'><i></i><i></i><i></i><span>agent-daemon</span></div><pre></pre></div>
<div class='eng-cap'></div><div class='eng-ctl'><button type='button' class='button eng-play'>❚❚ Pause</button>
<span class='muted'>A replay of a typical case. Your own cases show every real step on the case page.</span></div></div></div>
<script type='application/json' id='eng-data'>{json.dumps(data).replace('</', '<' + chr(92) + '/')}</script>
<h3 style='margin-top:34px'>Normal → High → Extra</h3>
<div class='eng-ladder'>
<article class='eng-tier most' style='--tc:#62e6a4'><span class='badge'>Most cases end here</span><h4>Normal</h4>
<p>The first engineer on every case. Fast and low-cost, with the whole code base and every tool.</p><span class='cost'>{E(cap('haiku'))}</span></article>
<div class='eng-arrow'>→</div>
<article class='eng-tier' style='--tc:#b06cff'><span class='badge'>Only if needed</span><h4>High</h4>
<p>Takes over when Normal could not finish, starting from everything Normal found and changed.</p><span class='cost'>{E(cap('sonnet'))}</span></article>
<div class='eng-arrow'>→</div>
<article class='eng-tier' style='--tc:#ff4f6a'><span class='badge'>Asks you first</span><h4>Extra</h4>
<p>The strongest engineer, for the hardest cases. Never used without your OK.</p><span class='cost'>{E(cap('opus'))}</span></article></div>
<p class='muted'>Your plan includes {quotas.get('normal', 30)} Normal, {quotas.get('high', 6)} High and {quotas.get('extra', 3)} Extra tries a month.</p>
<h3 style='margin-top:30px'>Is it a code problem?</h3>
<div class='eng-split'>
<article class='eng-out yes'><h4>✅ Yes: fixed and proven</h4><p>The engineer fixes the cause, runs your build and tests, and our own check
runs again. You see what it changed, and why.</p></article>
<article class='eng-out no'><h4>🧾 No: "Needs you", step by step</h4><p>A missing key, a database or sign-in setting, the hosting. Nothing is
changed and no stronger AI is paid for. You get steps like:</p><ol><li>Open vercel.com, your project, Settings, Environment Variables</li>
<li>Add VITE_SUPABASE_ANON_KEY (copy it from Supabase, Project Settings, API)</li><li>Press Redeploy, then "I did it, check again"</li></ol></article></div>
<h3 style='margin-top:30px'>Sure or not sure</h3>
<div class='eng-split'>
<article class='eng-out yes'><h4>🚀 Sure: pushed, then checked live</h4><p>All checks green, low risk, nothing left for you. In Auto mode it goes to
your branch after your GitHub tests pass; then the agent opens your live site, and undoes the fix by itself if the site got worse.</p></article>
<article class='eng-out no'><h4>🧐 Not sure: a pull request for you</h4><p>You get the reason in plain words ("removes 'NIV' from a list, check
that this was intended") and step-by-step instructions to merge it. One click when it is right.</p></article></div>
<div class='eng-chips'><span><b>Pause</b> any case</span><span><b>Resume</b> where it stopped</span><span><b>Run again</b> without retyping</span>
<span><b>Still broken?</b> show it a screenshot</span><span><b>Speak</b> instead of typing</span><span><b>Keep going</b> at the spending limit</span><span><b>Undo this fix</b> anytime</span></div>
<div class='eng-foot'><article><h4>What a try is</h4><p>{E(try_definition)}</p></article>
<article><h4>When a person is needed</h4><p>{E(human_needed)}</p></article></div>
</div></section><script>{SCRIPT}</script>"""
