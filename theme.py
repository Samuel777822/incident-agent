"""Agent Daemon look, version 5: one shared design layer for every page (public, customer and admin).

Loaded last in the page <head>, so it refines everything defined before it. The rules of the look:
  * room to breathe: a wider page, generous gaps between sections, nothing closer than 12px to its neighbour;
  * calm type: Cinzel only for page and section titles, the readable sans for card titles and all running text;
  * one card, one button, one pill, one table, one message style everywhere;
  * the mystic palette: obsidian background, crimson to violet light, a thin gold line for ornament.
"""

THEME_CSS = """
/* ============================== v5 theme ============================== */
:root{--gold:#c9a15a;--ink:#f4eefb;--soft:#cfc4de;--muted:#a79bb9;--edge:#372440;--glass:#150c1fd9;--glass2:#0d0814e6;
  --r-lg:20px;--r-md:14px;--r-sm:10px;--grad:linear-gradient(120deg,#d1121f 0%,#a3162b 42%,#5b1fa8 100%);
  --shadow:0 18px 50px #0008,inset 0 1px 0 #ffffff0d}
html{scroll-behavior:smooth;scroll-padding-top:96px}
body{font-size:16px;line-height:1.65;color:var(--ink);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.wrap{max-width:1180px;padding:0 28px}
main.wrap{padding-bottom:72px;min-height:60vh}
p{margin:0 0 12px}p:last-child{margin-bottom:0}
small{font-size:13px}
a{color:#ff7d6e;text-underline-offset:3px}a:hover{color:#ffa79b}
code{font-family:Consolas,Menlo,monospace;font-size:.9em;background:#2a17364d;border:1px solid #ffffff12;border-radius:6px;padding:1px 6px;color:#ffc3b8}
pre code{background:none;border:0;padding:0;color:inherit}
hr{border:0;height:1px;background:linear-gradient(90deg,transparent,#c9a15a55,transparent);margin:32px 0}

/* ---- headings ---- */
h1,h2{font-family:var(--serif);letter-spacing:.03em;color:#fff}
h1{font-size:clamp(28px,3.2vw,40px);line-height:1.18;margin:10px 0 12px}
h2{font-size:clamp(21px,2.1vw,26px);line-height:1.25;margin:0 0 14px}
h3,h4{font-family:"Instrument Sans",Inter,ui-sans-serif,system-ui,sans-serif;letter-spacing:0;color:#fff}
h3{font-size:18px;font-weight:700;line-height:1.35;margin:0 0 8px}
h4{font-size:15px;font-weight:700;margin:0 0 6px}
.section{padding:20px 0 8px}
.section h2,.section-tight h2,main>h2{margin-top:52px;padding-bottom:12px;border-bottom:1px solid;border-image:linear-gradient(90deg,#c9a15a80,#c9a15a1a 45%,transparent 80%) 1}
.section>h2:first-child,.section-tight h2{margin-top:0}
.section-tight{margin:44px 0 14px}
.section-tight .row h2{border:0;padding:0;margin:0}
.section-tight .row{padding-bottom:12px;border-bottom:1px solid;border-image:linear-gradient(90deg,#c9a15a80,#c9a15a1a 45%,transparent 80%) 1;margin-bottom:14px}
.card h2,.card h3,.form-card h1{border:0;padding:0}
.card h2{font-size:21px;margin:0 0 10px}
h3.sub{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);margin:28px 0 10px;font-weight:700}
.eyebrow{font-size:12.5px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;font-variant:normal;color:#ff7d6e;margin-bottom:6px}
.muted{color:var(--muted)}
.lead{font-size:18px;color:var(--soft);line-height:1.65}

/* ---- header ---- */
header.nav{position:sticky;top:0;height:76px;max-width:none;padding:0 max(28px,calc((100vw - 1180px)/2 + 28px));background:#08050dcc;
  -webkit-backdrop-filter:blur(16px) saturate(1.3);backdrop-filter:blur(16px) saturate(1.3);border-bottom:1px solid #ffffff12;border-image:none;gap:18px}
header.nav::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;background:linear-gradient(90deg,transparent,#e11d2a99 25%,#9a4dff99 75%,transparent)}
.navlinks{gap:6px}
.navlinks>a:not(.button){padding:8px 12px;border-radius:9px;font-size:14.5px;font-weight:600;transition:background .18s,color .18s}
.navlinks>a:not(.button):hover{background:#ffffff12}
.nav-trigger{font-size:14.5px;padding:8px 12px;border-radius:9px}
.nav-menu{min-width:210px;padding:8px;border-radius:14px;top:calc(100% + 8px)}
.nav-menu::before{content:"";position:absolute;left:0;right:0;top:-10px;height:10px}
.nav-menu a{padding:10px 12px;font-size:14.5px;border-radius:9px}
.navlinks form{margin:0;display:inline-flex}
.navlinks .button{padding:9px 16px;min-height:40px}

/* ---- buttons ---- */
.button,button.button{min-height:44px;padding:10px 20px;border-radius:12px;font-size:15px;font-weight:650;line-height:1.2;gap:8px;white-space:nowrap;
  background:linear-gradient(180deg,#ffffff14,#ffffff08);border:1px solid #ffffff26;color:#fff;text-decoration:none;
  transition:transform .16s ease,box-shadow .2s ease,border-color .2s ease,background .2s ease,filter .2s ease}
.button:hover{transform:translateY(-1px);border-color:#ffffff4d;background:linear-gradient(180deg,#ffffff1f,#ffffff0d);text-decoration:none;color:#fff;filter:none}
.button.primary{background:var(--grad);border-color:#ff5a4a80;box-shadow:0 8px 26px #d1121f45,inset 0 1px 0 #ffffff38}
.button.primary:hover{background:var(--grad);box-shadow:0 12px 34px #d1121f70,0 0 26px #9a4dff55,inset 0 1px 0 #ffffff38;filter:brightness(1.08)}
.button.danger{color:#ff9488;border-color:#ff4a3a59;background:#ff4a3a12}
.button.danger:hover{background:#ff4a3a26;border-color:#ff4a3a99;color:#ffc1b9}
.button.big{min-height:54px;font-size:17px;padding:14px 28px;border-radius:14px}
.button[disabled],.button[aria-disabled='true']{opacity:.55;cursor:not-allowed;transform:none}
.button.is-busy{opacity:.75;cursor:progress}
@media(max-width:640px){.button{white-space:normal;text-align:center}}
.actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:18px}
.actions form{margin:0;display:inline-flex}
.inline{gap:12px}
.row{gap:20px;flex-wrap:wrap}
form{margin:0}

/* ---- cards ---- */
.card,.stat,.table-wrap,.empty,.price-card,.live-item,.flow-card,.inc,.meter,.mode-card,.accordion-item,.video-card,.gov-info-strip{
  background:linear-gradient(165deg,var(--glass),var(--glass2)) padding-box,
    linear-gradient(140deg,#e11d2a66,#372440 34%,#372440 66%,#9a4dff66) border-box;
  border:1px solid transparent;-webkit-backdrop-filter:blur(12px) saturate(1.2);backdrop-filter:blur(12px) saturate(1.2);box-shadow:var(--shadow)}
.card{border-radius:var(--r-lg);padding:28px}
.card>*:last-child{margin-bottom:0}
.card p{color:var(--soft)}
.card .muted,.card p.muted{color:var(--muted)}
.card+.card{margin-top:20px}
.grid>.card+.card,.steps-grid>.card+.card,.price-grid>.card+.card,.founders-grid>.card+.card{margin-top:0}
a.card:hover,.hover-float:hover{transform:translateY(-3px);box-shadow:0 26px 60px #000a,0 0 30px #9a4dff33}
.card.success{background:linear-gradient(165deg,#0f241dd9,#0b0f12e6) padding-box,linear-gradient(140deg,#62e6a480,#1f5a49 50%,#62e6a440) border-box}
.grid{gap:20px;margin:22px 0 8px;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr))}
.empty{border-radius:var(--r-lg);padding:38px 28px;color:var(--muted);font-size:15.5px;border-style:solid}

/* ---- stats ---- */
.statgrid{grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px;margin:24px 0 8px}
.stat{border-radius:var(--r-md);padding:20px 20px 18px}
.stat b{font-family:var(--serif);font-size:34px;line-height:1.1;margin-bottom:6px}
.stat span{font-size:13.5px;line-height:1.4;display:block}
.stats{gap:10px;margin:16px 0}

/* ---- pills, chips, messages ---- */
.pill{padding:6px 12px;font-size:13px;font-weight:600;line-height:1.3;border-radius:999px;gap:6px;background:#241531;color:#dccdf0;border:1px solid #43305a}
.pill.green,.pill.tone-green{background:#0f2f27;color:#8ce4c0;border-color:#1f5a49}
.pill.amber,.pill.tone-amber{background:#33270f;color:#f4d491;border-color:#6b5320}
.pill.red,.pill.tone-red{background:#3a1014;color:#ff9c90;border-color:#7a2424}
.pill.tone-blue,.pill.mode{background:#2a1a4a;color:#d9c6ff;border-color:#4d3585}
.pill.tone-muted,.pill.src{background:#211629;color:#cdbfe0;border-color:#3a2a48}
.chip{padding:4px 10px;font-size:12.5px;margin:3px 6px 3px 0;border-radius:999px;background:#ffffff08}
/* a pill used as a page message (long text, direct child of a section or the page): a proper notice, never a squeezed capsule */
main>.pill,.section>.pill,.section>p>.pill:only-child,.form-card>.pill,div.pill,p.pill{display:flex;align-items:flex-start;gap:10px;white-space:normal;
  border-radius:var(--r-md);padding:14px 18px;font-size:15px;font-weight:500;line-height:1.55;margin:16px 0;text-align:left}
main>.pill::before,.section>.pill::before,.form-card>.pill::before,div.pill::before,p.pill::before{content:"✦";flex:none;opacity:.9}
.alert{display:block;border-radius:var(--r-md);padding:14px 18px;margin:18px 0;font-size:15px;line-height:1.55;background:#2a1e0ce6;border:1px solid #8a6a2c;color:#f8e2ae}
.alert a{color:#ffd58a;text-decoration:underline}
.new-banner{margin:28px 0;padding:16px 20px;border-radius:var(--r-md);line-height:1.7;display:block}
.new-banner .pill{margin-right:8px;vertical-align:1px}

/* ---- tables ---- */
.table-wrap{border-radius:var(--r-lg);margin:18px 0;overflow-x:auto}
.table{min-width:680px;font-size:15px}
.table th{padding:14px 18px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold);font-weight:700;background:#ffffff06;white-space:nowrap}
.table td{padding:16px 18px;border-bottom:1px solid #ffffff0f;line-height:1.5}
.table tbody tr:last-child td{border-bottom:0}
.table tbody tr{transition:background .15s}.table tbody tr:hover{background:#ffffff07}
.table td small{display:inline-block;margin-top:3px}
.table td .button{min-height:38px;padding:8px 14px;font-size:14px}
.table td form{display:inline-flex;gap:8px;flex-wrap:wrap;align-items:center;margin:2px 0}

/* ---- forms ---- */
.field{margin:20px 0}
.field label,label.label{display:block;font-weight:650;font-size:14.5px;margin-bottom:8px;color:#efe7fa}
.field small{margin-top:8px;color:var(--muted);line-height:1.5}
input[type=text],input[type=email],input[type=password],input[type=url],input[type=number],input[type=tel],input[type=search],input:not([type]),textarea,select{
  width:100%;min-height:48px;padding:12px 14px;border-radius:12px;border:1px solid #45305233;border-color:#453052;background:#0a0610e6;color:var(--ink);
  font:inherit;font-size:15.5px;line-height:1.4;transition:border-color .18s,box-shadow .18s}
textarea{min-height:120px;resize:vertical;line-height:1.55}
select{width:auto;min-width:160px;padding-right:34px;cursor:pointer}
.field select{width:100%}
input::placeholder,textarea::placeholder{color:#7d7190}
input:focus,textarea:focus,select:focus,.field input:focus,.field select:focus{outline:none;border-color:#ff5a4a;box-shadow:0 0 0 3px #e11d2a2e,0 0 22px #9a4dff2e}
input[type=checkbox],input[type=radio]{width:18px;height:18px;min-height:0;accent-color:#c0182a;flex:none;margin:3px 0 0}
.checkbox{gap:12px;line-height:1.5;color:var(--soft)}
.checkbox input{margin-top:3px}
fieldset.choice{border-radius:var(--r-md);padding:16px 18px;border-color:var(--edge)}
.form-card{max-width:520px;margin:min(12vh,96px) auto 40px;padding:36px}
.form-card h1{font-size:30px;margin:6px 0 10px}
.form-card .button{width:100%}
.form-card .actions .button{width:auto;flex:1 1 auto}
details>summary{cursor:pointer}
details>summary:focus-visible{outline:2px solid #ff6655;outline-offset:4px;border-radius:6px}
pre.log,pre{border-radius:12px}
pre.log{padding:14px;font-size:13px;line-height:1.55;max-height:320px}

/* ---- page head ---- */
.page-head{align-items:flex-end;gap:20px;margin:28px 0 24px;padding-bottom:22px;border-bottom:1px solid #ffffff10}
.page-head h1{margin:6px 0 6px}
.page-head .actions{margin:0}
.plan-strip{margin:0 0 8px}

/* ---- tries meters (dashboard) ---- */
.meters{grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:16px 0 0}
.meter{border-radius:var(--r-md);padding:18px 20px}
.meter-top b{font-size:17px}.meter-top span{font-size:14px;color:var(--soft)}
.meter-bar{height:10px;border-radius:999px;margin:12px 0 8px;background:#ffffff12}
.meter-bar i{border-radius:999px;background:linear-gradient(90deg,#3fd69a,#8ce4c0);box-shadow:0 0 12px #62e6a466}
.meter.warn .meter-bar i{background:linear-gradient(90deg,#e3a23c,#f4d491);box-shadow:0 0 12px #e3bd7466}
.meter.bad .meter-bar i{background:linear-gradient(90deg,#e0352b,#ff8a7a);box-shadow:0 0 12px #ff7a6a66}
.meter small{font-size:13px}

/* ---- "agent right now" and case cards ---- */
.live{font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:6px}
.live-list{gap:16px;margin:16px 0}
.live-item{border-radius:var(--r-lg);padding:22px 24px}
.live-item[data-active='1']{box-shadow:var(--shadow),0 0 0 1px #9a4dff55,0 0 34px #9a4dff22}
.live-top{gap:14px}.live-top a{font-size:16.5px;line-height:1.4;text-decoration:none}.live-top a:hover{color:#fff;text-decoration:underline}
.live-meta{gap:8px;margin:12px 0 4px;font-size:13px}
.live-detail{margin:14px 0 0;padding:10px 14px;border-radius:10px;background:#ffffff08;font-size:14px;line-height:1.5;color:var(--soft)}
:is(#incident-board,#agent-live) .steps{gap:12px 30px;margin:16px 0 0}
:is(#incident-board,#agent-live) .steps li{padding:8px 15px;font-size:13.5px;font-weight:600;border-color:#ffffff1a;color:#8f84a3}
:is(#incident-board,#agent-live) .steps li:not(:last-child)::after{right:-23px;color:#6f6582}

/* ---- "how it looks after your site" flow ---- */
.flow-card{border-radius:var(--r-lg);padding:28px;margin:24px 0}
.flow-card h3{margin-bottom:18px}
.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:16px 34px}
.flow-node{min-width:0;max-width:none;padding:16px 16px 14px;border-radius:var(--r-md);background:#ffffff08;border:1px solid #ffffff14;gap:4px}
.flow-node b{font-size:15.5px}
.flow-node small{font-size:13px;line-height:1.45}
.flow-node:not(:last-child)::after{right:-27px;color:#9a4dff;font-size:18px}
.flow-node:nth-child(4n)::after{display:none}
.flow-num{width:26px;height:26px;font-size:13px;margin-bottom:8px;background:var(--grad);color:#fff;box-shadow:0 0 14px #e11d2a55}
.flow-loop{margin-top:20px;padding:14px 18px;border-radius:var(--r-md);font-size:14px;line-height:1.6;border-style:solid;border-color:#6b5320;background:#33270f66;color:#f4dfae}
@media(max-width:900px){.flow{grid-template-columns:repeat(2,1fr)}.flow-node:nth-child(2n)::after{display:none}}
@media(max-width:560px){.flow{grid-template-columns:1fr}.flow-node::after{display:none!important}}
.report-card textarea{margin:14px 0;border-radius:12px;border-color:#453052;background:#0a0610e6;min-height:130px}
.report-card textarea:focus{border-color:#ff5a4a;box-shadow:0 0 0 3px #e11d2a2e}

/* ---- project cards on the dashboard ---- */
.project-card{gap:6px;padding:26px}
.project-card .pc-head{gap:14px;margin-bottom:6px}
.project-card .pc-head h3{font-size:19px}
.project-card p{margin:6px 0;font-size:14.5px}
.project-card .stats{margin:10px 0;gap:8px}
.project-card .pc-foot{padding-top:18px}
.project-card .pc-foot .button{width:100%}

/* ---- pricing and plans ---- */
.price-grid{gap:22px;margin-top:24px;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}
.price-card{border-radius:var(--r-lg);padding:30px;gap:10px}
.price-card.featured{background:linear-gradient(165deg,#1d0d22e6,#0d0814e6) padding-box,linear-gradient(140deg,#ff4a3a,#9a4dff) border-box;box-shadow:var(--shadow),0 0 40px #e11d2a2e}
.price-card .price{font-family:var(--serif);font-size:38px;line-height:1.1;margin:10px 0}
.price-card .price small{font-family:"Instrument Sans",sans-serif;font-size:14px}
.price-card .button{margin-top:18px}
.quota-list{gap:10px;font-size:15px;margin:12px 0 16px}
.quota-list li{padding-left:28px}
.addon-row{gap:20px}
.card.addon{gap:10px}.card.addon .button{margin-top:14px}
.feat-ico{width:46px;height:46px;border-radius:13px;font-size:21px;margin-bottom:14px;background:linear-gradient(140deg,#e11d2a26,#9a4dff26);border-color:#ffffff24}

/* ---- numbered steps and guides ---- */
.steps.big{gap:18px;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr))}
.steps.big li{padding:20px 20px 20px 64px;border-radius:var(--r-md);line-height:1.55}
.steps.big li::before{left:18px;top:18px;width:32px;height:32px}
ol.steps:not(.big),.steps-grid ol.steps{padding-left:24px}
ol.steps:not(.big) li,.steps-grid ol.steps li{margin:10px 0;line-height:1.6;padding-left:4px}
.steps-grid{gap:20px}
.gate .lead{font-size:18px;line-height:1.65}
.monitor-status{margin:24px 0}
.monitor-list{padding-left:20px}.monitor-list li{margin:8px 0}
.guide h3{margin:28px 0 8px}

/* ---- help, faq, accordions ---- */
.accordion-group{gap:14px}
.accordion-item{border-radius:var(--r-md)}
.accordion-summary{padding:18px 22px;font-size:16px;gap:16px}
.accordion-body{padding:4px 22px 22px;font-size:15px;line-height:1.7}
.help-section{margin:56px 0}
.help-section-title{font-size:24px;margin-bottom:22px}
.modes-grid{gap:20px}.mode-card{padding:24px;border-radius:var(--r-md)}
.mode-card p{font-size:14.5px;line-height:1.6}
.chapter-list{gap:12px}.chapter-item{padding:12px 16px;font-size:14px;border-radius:10px}
.code-box{padding:14px 16px;border-radius:10px;font-size:13.5px;line-height:1.6}

/* ---- footer ---- */
.footer{margin-top:40px;padding:64px 0 44px;background:linear-gradient(180deg,transparent,#05030899 30%)}
.footer-grid{gap:40px;margin-bottom:48px}
.footer-heading{font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);margin-bottom:18px}
.footer-links{gap:13px}.footer-links li a{font-size:14.5px}
.gov-info-strip{border-radius:var(--r-lg);padding:22px 28px;margin:0 0 32px}
.footer-bottom{padding-top:30px;gap:18px;line-height:1.6}

/* ---- small screens ---- */
@media(max-width:860px){header.nav{height:auto;min-height:68px;padding:12px 18px;position:relative}.wrap{padding:0 18px}.card{padding:22px}.form-card{padding:26px;margin-top:40px}
  .section h2,main>h2{margin-top:40px}.page-head{align-items:flex-start}.table{font-size:14px}.table th,.table td{padding:12px 14px}}
@media(max-width:640px){.actions{flex-direction:row}.actions .button{flex:1 1 auto}.page-head .actions{width:100%}.statgrid{grid-template-columns:repeat(2,1fr)}
  .meters{grid-template-columns:1fr}.live-item{padding:18px}.price-card{padding:22px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}.button,.card,.hover-float{transition:none}}
"""

THEME_CSS += """
/* ---- calmer backdrop behind working pages (the hero keeps the full artwork) ---- */
body::before{opacity:.26}
body:has(.hero)::before{opacity:.95}

/* ---- project page ---- */
.subnav{position:sticky;top:76px;z-index:50;display:flex;gap:6px;flex-wrap:wrap;margin:22px 0 26px;padding:8px;border-radius:16px;background:#0d0814e6;
  border:1px solid #ffffff14;-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 12px 30px #0007}
.subnav a{padding:9px 16px;border-radius:10px;font-size:14.5px;font-weight:600;color:var(--soft);text-decoration:none;transition:background .18s,color .18s}
.subnav a:hover{background:#ffffff12;color:#fff}
.anchor{scroll-margin-top:150px}
h2[id]{scroll-margin-top:150px}
details.fold{margin:44px 0 0;border-radius:var(--r-lg);border:1px solid #ffffff14;background:#0d081499}
details.fold>summary{padding:18px 24px;font-weight:650;font-size:16px;color:#efe7fa;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:12px}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::after{content:"+";font-size:22px;color:#ff7d6e;line-height:1}
details.fold[open]>summary::after{content:"−"}
details.fold>.flow-card{margin:0 16px 16px;box-shadow:none}
details.fold>.flow-card>h3{display:none}
.settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;margin:22px 0}
.settings-grid>.card{margin:0;display:flex;flex-direction:column}
.settings-grid>.card form{margin-top:auto;padding-top:8px}
.settings-grid>.card .field{margin:14px 0 18px}
.danger-zone{margin-top:28px;background:linear-gradient(165deg,#2a0d12d9,#0d0814e6) padding-box,linear-gradient(140deg,#ff4a3a99,#5a1a22 60%,#ff4a3a55) border-box}
.danger-zone .eyebrow{color:#ff8a7a}
.danger-zone form{max-width:560px}
.danger-zone .checkbox{margin:16px 0 4px}
.cases-bar{display:flex;flex-wrap:wrap;gap:12px 14px;align-items:center;margin:4px 0 22px;padding:14px 18px;border-radius:var(--r-md);background:#ffffff07;border:1px solid #ffffff12}
.cases-bar form{display:inline-flex}
.cases-note{flex:1 1 260px;font-size:14px;line-height:1.5}
.inc-guide .guide form{margin:4px 10px 4px 0}
.inc-guide .guide .guide-line{margin-top:12px}
.report-card{scroll-margin-top:150px}
.report-card .row{align-items:flex-start}
.report-card details{margin-top:18px}
.report-card details summary{color:#ff7d6e;font-weight:600;font-size:14.5px}
.monitor-status .row{align-items:flex-start;margin-bottom:8px}
.monitor-status details.more{margin:12px 0}
.monitor-status details.more summary{color:#ff7d6e;font-weight:600}
@media(max-width:860px){.subnav{top:0;position:relative}.settings-grid{grid-template-columns:1fr}}
"""

THEME_CSS += """
.section>.card,.section>section.card,.section>article.card,main>.card{margin-top:22px;margin-bottom:22px}
.section>.grid>.card,.grid>.card{margin:0}
"""

THEME_CSS += """
/* ---- billing ---- */
.price-card h2.price{font-family:var(--serif);font-size:40px;line-height:1.1;margin:10px 0 12px;border:0;padding:0}
.price-card h2.price small{font-family:"Instrument Sans",sans-serif;font-size:15px;font-weight:500;letter-spacing:0}
.price-card form{margin-top:auto}.price-card form .button,.price-card>a.button{width:100%}
.price-card>p.muted:last-child{margin-top:12px;font-size:14px}
.fineprint{margin:26px 0 0;padding:18px 22px;border-radius:var(--r-md);background:#ffffff06;border:1px solid #ffffff10;font-size:14.5px;line-height:1.7}
.stack-form{display:flex;flex-direction:column;gap:4px;margin-top:14px}
.stack-form .field{margin:8px 0}
.stack-form .button{margin-top:10px}
/* ---- usage page fit ---- */
.use .u-h2{border:0;padding:0;margin:48px 0 10px}
.use .u-pack{align-items:flex-start}
.use .u-pack>div:last-child{flex:1;min-width:0}
.use .u-pack .row{gap:10px;margin-top:14px}
.use .u-pack .row .button,.use .u-pack .row form{flex:1 1 200px}
.use .u-pack .row form .button{width:100%}
.use .u-case{padding:16px 20px;gap:16px}
.use .u-case .n{display:inline-flex;align-items:center;gap:14px}
.use .u-case .n form{display:inline-flex}
.use .u-case .button{min-height:38px;padding:8px 14px;font-size:14px}
.use .u-choice .acts form{display:inline-flex}
.use .u-tiers{gap:20px}.use .u-modes{gap:18px}.use .u-packs{gap:20px}
.use .u-help{padding:6px 22px}
"""

THEME_CSS += """
.section>h1,.page-head h1{overflow-wrap:anywhere}
.card pre{background:#07040c;border:1px solid #ffffff12;padding:16px 18px;font:13.5px/1.65 Consolas,Menlo,monospace;margin:14px 0 0;overflow:auto;color:#d9d0e8}
.stats+p{margin-top:18px}
.section>p>a:only-child{font-weight:600}
"""

THEME_CSS += """
/* ---- admin ---- */
.warn-card{background:linear-gradient(165deg,#2a1e0cd9,#0d0814e6) padding-box,linear-gradient(140deg,#e3bd7499,#6b5320 55%,#e3bd7444) border-box}
.warn-card .eyebrow{color:#f4d491}.warn-card .eyebrow::before{background:#e3bd74;box-shadow:0 0 10px #e3bd74}
.card ul,.card ol{margin:10px 0 12px;padding-left:22px}.card li{margin:7px 0;line-height:1.6;color:var(--soft)}
details.more{margin-top:10px}details.more>summary{font-weight:650;color:#ff7d6e;padding:4px 0}
.ticket-form{display:flex;flex-direction:column;gap:10px;min-width:260px}
.ticket-row{display:flex;gap:10px;align-items:center}
.ticket-row select{flex:1;min-width:0;width:auto}
.ticket-form input,.ticket-form select{min-height:40px;padding:8px 12px;font-size:14px}
.ticket-form .button{min-height:40px;padding:8px 16px;font-size:14px}.ticket-form .button.primary{flex:1}
.ticket-msg{max-width:340px;font-size:14px;color:var(--soft);margin-top:6px;line-height:1.55;overflow-wrap:anywhere}
.ticket-resolution{margin-top:10px;padding:10px 12px;background:#0f2f2799;border-left:3px solid #6fe0b0;border-radius:8px;font-size:13.5px;color:#b9f3da;line-height:1.5}
.fix-note{margin-top:10px;padding:12px 14px;border-radius:12px;background:#33270f99;border:1px solid #6b5320;color:#f6e6bd;font-size:14px;line-height:1.6;max-width:560px}
.section>h3{margin:32px 0 10px}
"""

THEME_CSS += """
/* ---- public pages ---- */
.price-card .badge-tag{align-self:flex-start;padding:5px 12px;border-radius:999px;font-size:11.5px;letter-spacing:.1em;margin:0 0 8px}
.price-card h3{font-size:21px;margin:0}
.price-card .price small{display:block;margin-top:8px;line-height:1.4;color:var(--muted)}
.price-card>p{margin:4px 0}
.about-hero,.help-hero{padding:min(10vh,84px) 0 36px}
.about-hero h1,.help-hero h1{font-size:clamp(30px,4vw,46px);line-height:1.2;margin:14px 0 18px}
.about-hero p,.help-hero p{font-size:18px;line-height:1.7;max-width:720px;margin-inline:auto}
.about-hero .actions,.help-hero .actions{justify-content:center}
.addon-row div{gap:6px;line-height:1.55}
.founders-grid{gap:28px}
.badge-tag{padding:3px 10px;border-radius:999px;font-size:11.5px;letter-spacing:.06em}
.mission-card{padding:44px 32px}
.help-pills{gap:12px}.help-pill{padding:10px 18px;font-size:14px}
.help-search-input{min-height:54px;padding-left:46px;border-radius:14px}
.video-info{padding:26px 28px}
main>section.card,main>article.card{margin-top:28px}
"""

THEME_CSS += """
/* ---- connect a project ---- */
.connect-layout{display:grid;grid-template-columns:minmax(0,520px) minmax(0,1fr);gap:28px;align-items:start;margin:36px 0}
.connect-layout>.form-card{margin:0;max-width:none}
.connect-layout>.guide{margin:0}
.guide details.fold{margin:14px 0 0;background:#ffffff06}
.guide details.fold>summary{padding:16px 20px;font-size:16px}
.fold-body{padding:0 22px 18px}
.fold-body ol,.fold-body ul{margin:8px 0;padding-left:22px}
.fold-body li{margin:9px 0;line-height:1.6}
.guide>p{margin-top:14px}
@media(max-width:980px){.connect-layout{grid-template-columns:1fr}}
"""
