"""Small, server-rendered web application for Agent Daemon.

This deliberately uses Python's standard-library WSGI server and HTML
templates. It is a development entry point; production should run behind an
HTTPS reverse proxy and set the secrets documented in README.md.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import hmac
import html
import json
import os
import uuid
import re
import secrets
from pathlib import PurePosixPath
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone
from http import cookies
from io import BytesIO
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from wsgiref.simple_server import WSGIServer, make_server

import httpx
from urllib.parse import urlencode

import incident_board
import notifications
import chatbot
import chat_widget
import portal_db
import footer_pages
import homepage
from monitoring_installer import resolve_branch, GitHubInstallError, open_monitoring_pr, validate_repository_access

APP_NAME = "Agent Daemon"
SESSION_COOKIE = "agent_session"
CSRF_COOKIE = "agent_csrf"
SESSION_SECONDS = 60 * 60 * 24 * 7
MAX_BODY = 65536
GOOGLE_CALLBACK_PATH = "/auth/google/callback"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
REPO_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

CSS = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2d;--line:#26324a;--muted:#9aa9c2;--text:#edf3ff;--blue:#75a7ff;--green:#55d6a1;--amber:#f0c36b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20% -20%,#1b3158 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.wrap{max-width:1080px;margin:auto;padding:0 24px}main{position:relative;z-index:2}header{position:relative;z-index:100}button,a{pointer-events:auto}.nav{height:72px;border-bottom:1px solid #ffffff12;display:flex;align-items:center;justify-content:space-between}.brand{font-size:17px;font-weight:750;letter-spacing:.02em;color:var(--text)}.brand-mark{display:inline-grid;place-items:center;width:28px;height:28px;margin-right:9px;background:#274b82;border-radius:9px;color:white}.navlinks{display:flex;gap:20px;align-items:center;color:var(--muted)}.button{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border:1px solid #ffffff20;border-radius:10px;background:#19243a;color:var(--text);font:inherit;font-weight:650;cursor:pointer}.button.primary{background:#2f68c8;border-color:#4e88e7;color:white}.button.danger{color:#ffb3b3}.button:hover{filter:brightness(1.12);text-decoration:none}.hero{padding:76px 0 62px;max-width:760px}.eyebrow{color:var(--green);text-transform:uppercase;letter-spacing:.13em;font-size:12px;font-weight:750}.hero h1{font-size:clamp(38px,6vw,64px);line-height:1.04;letter-spacing:-.045em;margin:15px 0 20px}.hero p{font-size:19px;color:#b7c4d8;max-width:640px}.actions{display:flex;gap:12px;align-items:center;margin-top:28px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:16px;margin:22px 0 50px}.card{background:linear-gradient(145deg,#141e33,#101729);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 18px 50px #0002}.card h2,.card h3{margin:0 0 8px}.muted{color:var(--muted)}.section{padding:18px 0 42px}.section h2{font-size:26px;letter-spacing:-.025em}.form-card{max-width:480px;margin:58px auto}.form-card h1{font-size:32px;margin:0 0 8px}.field{margin:16px 0}.field label{display:block;font-weight:650;margin-bottom:6px}.field input,.field select{width:100%;padding:12px 13px;border-radius:9px;border:1px solid #34425e;background:#0b1324;color:var(--text);font:inherit}.field small{display:block;color:var(--muted);margin-top:5px}.checkbox{display:flex;gap:10px;align-items:flex-start;color:#c7d2e4}.checkbox input{margin-top:6px}.alert{padding:12px 14px;border:1px solid #a47638;border-radius:10px;background:#342918;color:#ffe0a3;margin:16px 0}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.pill{display:inline-flex;gap:7px;align-items:center;padding:5px 10px;border-radius:99px;background:#1b2d43;color:#b8c9df;font-size:12px}.pill.green{color:#8ce4c0;background:#14392f}.pill.amber{color:#ffdc91;background:#3a301b}.row{display:flex;justify-content:space-between;align-items:center;gap:16px}.table{width:100%;border-collapse:collapse;margin-top:16px}.table th,.table td{text-align:left;padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:top}.table th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.footer{border-top:1px solid #ffffff12;padding:24px 0 38px;color:var(--muted);font-size:13px}.empty{padding:30px;text-align:center;border:1px dashed #40506c;border-radius:14px;color:var(--muted)}
@media(max-width:640px){.wrap{padding:0 17px}.navlinks{gap:11px}.hero{padding:54px 0 40px}.hero p{font-size:17px}.actions{align-items:stretch;flex-direction:column}.row{align-items:flex-start;flex-direction:column}.table{font-size:13px}}
.button{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #75a7ff;outline-offset:3px}
.button:active{transform:translateY(1px)}
.card{transition:border-color .18s ease,transform .18s ease}
a.card:hover{border-color:#4d6c9a;transform:translateY(-2px);text-decoration:none}
.table-wrap{max-width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:16px 0}
.table{min-width:640px;margin:0}
.table th,.table td{padding:14px 12px}
.actions{display:flex;flex-wrap:wrap;gap:8px}
.actions form{margin:0}
.field input:focus,.field select:focus{border-color:var(--blue);box-shadow:0 0 0 3px #75a7ff20;outline:none}
h1,h2,h3{line-height:1.2}
@media(max-width:640px){.nav{height:auto;min-height:68px;align-items:flex-start;padding-top:16px;padding-bottom:16px;gap:12px}.navlinks{flex-wrap:wrap;justify-content:flex-end}.table{min-width:620px}.card{padding:18px}.section{padding-top:12px}}

"""


CSS += """
.statgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0 8px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat b{display:block;font-size:28px;line-height:1.1}.stat span{color:var(--muted);font-size:13px}
.pill.red{background:#3a1820;color:#ff8a7a;border-color:#6a2b38}
.ok{color:var(--green)}.bad{color:#ff8a7a}
.qr{background:#fff;border-radius:14px;padding:14px;text-align:center;margin:18px 0}
.qr img{display:block;margin:auto;max-width:100%;height:auto}.qr p{color:#222;margin:8px 0 0}
.section h2{margin-top:32px}
.inline{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}
select{background:#0d1426;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px}
"""


CSS += """
/* ===== Agent Daemon theme: fallen angel, crimson left / violet right ===== */
@font-face{font-family:"Gloock";src:url(/assets/daemon-gloock.woff?v=1) format("woff");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"Instrument Sans";src:url(/assets/daemon-sans-400.woff?v=1) format("woff");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"Instrument Sans";src:url(/assets/daemon-sans-700.woff?v=1) format("woff");font-weight:700;font-style:normal;font-display:swap}
:root{--bg:#07050b;--panel:#120a1b;--line:#3a2338;--muted:#a99dbb;--text:#f2edf7;--blue:#ff6655;--green:#6fe0b0;--amber:#e3bd74;--crimson:#e11d2a;--violet:#9a4dff;--silver:#e9e4ee;--serif:"Cinzel","Gloock","Palatino Linotype",Palatino,Georgia,serif;--display:"Cinzel Decorative","Cinzel","Gloock",Georgia,serif}
html{background:#07050b;scrollbar-color:#5b2a5a #07050b}
body{position:relative;background:transparent;font-family:"Instrument Sans",Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;font-size:16px}
h1,h2,.brand,.stat b,.hero h1,.steps.big li::before{font-weight:700}h3{font-weight:500}h1,h2,h3{letter-spacing:.02em}
::selection{background:#9a4dff66;color:#fff}
body::before{content:"";position:fixed;top:0;width:max(100vw,125vh);left:calc(50% - max(100vw,125vh)/2);height:calc(max(100vw,125vh)*.59);z-index:-3;pointer-events:none;background:url(/assets/daemon-bg.webp?v=1) 50% 0/100% 100% no-repeat;opacity:.45;-webkit-mask-image:linear-gradient(180deg,#000 35%,transparent 100%);mask-image:linear-gradient(180deg,#000 35%,transparent 100%);animation:daemon-rise 1.8s ease-out both}
body:has(.hero)::before{opacity:.95;-webkit-mask-image:linear-gradient(180deg,#000 38%,transparent 100%);mask-image:linear-gradient(180deg,#000 38%,transparent 100%)}
body::after{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:radial-gradient(60% 50% at 8% 6%,#e11d2a38,transparent 70%),radial-gradient(60% 50% at 92% 6%,#9a4dff38,transparent 70%),radial-gradient(90% 60% at 50% 110%,#07050b,transparent 70%);animation:daemon-breathe 7s ease-in-out infinite alternate}
html::before{content:"";position:fixed;left:0;right:0;top:0;height:200vh;z-index:-1;pointer-events:none;opacity:.55;background:radial-gradient(circle,#ff4a3a 0 1.2px,transparent 2px) 0 0/330px 50vh,radial-gradient(circle,#b98aff 0 1px,transparent 1.8px) 140px 24vh/410px 50vh;animation:daemon-embers 38s linear infinite;will-change:transform}
@keyframes daemon-rise{from{opacity:0;transform:scale(1.04)}}
@keyframes daemon-breathe{from{opacity:.65}to{opacity:1}}
@keyframes daemon-embers{to{transform:translate3d(0,-50vh,0)}}
a{color:var(--blue)}
.nav{border-bottom:1px solid;border-image:linear-gradient(90deg,#e11d2a77,#9a4dff77 60%,transparent) 1}
.brand{white-space:nowrap;font-family:var(--display);font-size:19px;font-weight:700;letter-spacing:.05em;color:var(--silver);display:inline-flex;align-items:center;text-shadow:0 0 18px #e11d2a66}
.brand:hover{text-decoration:none}
.brand-mark{width:36px;height:36px;margin-right:11px;font-size:0;color:transparent;background:url(/assets/daemon-crest.webp?v=1) center/cover;border-radius:50%;border:1px solid #c9a15a88;box-shadow:0 0 14px #e11d2a88,0 0 26px #9a4dff55}
.navlinks a:not(.button){color:#cdbfe0}.navlinks a:not(.button):hover{color:#fff;text-decoration:none}
.button{border-radius:8px;background:#ffffff0a;border:1px solid #ffffff2b;font-weight:600;letter-spacing:.02em;backdrop-filter:blur(6px)}
.button.primary{background:linear-gradient(120deg,#d1121f 0%,#a3162b 42%,#5b1fa8 100%);border-color:#ff4a3a99;color:#fff;box-shadow:0 8px 28px #d1121f55,inset 0 1px 0 #ffffff2e}
.button.primary:hover{box-shadow:0 8px 34px #d1121f99,0 0 22px #9a4dff66,inset 0 1px 0 #ffffff2e}
.button.danger{color:#ff7a6a;border-color:#ff4a3a55}
.hero{max-width:none;display:flex;flex-direction:column;justify-content:flex-start;align-items:center;text-align:center;padding:min(38vh,380px) 0 56px}
.hero h1{font-family:var(--display);font-weight:700;font-size:clamp(30px,5.2vw,54px);line-height:1.16;letter-spacing:.015em;background:linear-gradient(180deg,#fff,#d4cadf 55%,#8e8499);-webkit-background-clip:text;background-clip:text;color:transparent;filter:drop-shadow(0 4px 18px #000) drop-shadow(0 0 26px #e11d2a44)}
.hero p{color:#d3c9e0;margin-inline:auto;text-shadow:0 2px 14px #000}
.hero .actions{justify-content:center}
.eyebrow{display:inline-flex;align-items:center;gap:9px;color:#ff6655;text-transform:none;font-variant:small-caps;letter-spacing:.16em;font-size:14px}
.eyebrow{text-shadow:0 0 10px #000,0 2px 8px #000}
.eyebrow::before{content:"";width:7px;height:7px;background:var(--crimson);transform:rotate(45deg);box-shadow:0 0 10px var(--crimson)}
h1,h2,h3{font-family:var(--serif)}
.card,.stat,.table-wrap,.empty{background:linear-gradient(160deg,#1a0e22c7,#0b0710d1) padding-box,linear-gradient(135deg,#e11d2a99,#3a2338 38%,#3a2338 62%,#9a4dff99) border-box;border:1px solid transparent;-webkit-backdrop-filter:blur(10px) saturate(1.2);backdrop-filter:blur(10px) saturate(1.2);box-shadow:0 20px 60px #0009,inset 0 1px 0 #ffffff0d}
.card{border-radius:12px}
a.card:hover{box-shadow:0 20px 60px #0009,0 0 28px #9a4dff44;transform:translateY(-2px)}
.stat{border-radius:10px;padding:16px}
.stat b{font-family:var(--display);font-size:32px;background:linear-gradient(180deg,#fff,#b8aac9);-webkit-background-clip:text;background-clip:text;color:transparent}
.stat span{color:var(--muted)}
.table th{text-transform:none;letter-spacing:.04em;font-size:13px;color:#c9a15a}
.table th,.table td{border-bottom-color:#2e1c31}
.field input,.field select,select{background:#0a0610d9;border:1px solid #3d2a45;border-radius:8px}
.field input:focus,.field select:focus{border-color:var(--crimson);box-shadow:0 0 0 3px #e11d2a2e,0 0 18px #9a4dff33}
.button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #ff6655}
.pill{background:#21132e;color:#d6c8ea;border:1px solid #3a2a4f}
.pill.green{background:#0f2f27;color:#8ce4c0;border-color:#1f5a49}
.pill.amber{background:#33270f;color:#f0cf8a;border-color:#6b5320}
.pill.red{background:#3a0d0d;color:#ff8a7a;border-color:#7a1f1f}
.alert{background:#2a1e0cdd;border-color:#8a6a2c;color:#f6dca0;border-radius:10px}
.footer{border-top:1px solid;border-image:linear-gradient(90deg,#e11d2a55,#9a4dff55 60%,transparent) 1}
.form-card{margin-top:min(26vh,200px)}
.form-card .form-card{margin:22px 0 0;max-width:none;padding:0;border:0;background:none;box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none}
.steps{padding-left:22px}.steps li{margin:8px 0}.steps.big{counter-reset:s;list-style:none;padding:0;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}.steps.big li{counter-increment:s;margin:0;padding:18px 18px 18px 56px;position:relative;border:1px solid #3a2338;border-radius:12px;background:#120a1bb8;-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}.steps.big li::before{content:counter(s);position:absolute;left:16px;top:16px;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;font-family:var(--serif);font-weight:700;color:#fff;background:linear-gradient(120deg,#d1121f 0%,#a3162b 42%,#5b1fa8 100%);box-shadow:0 0 14px #e11d2a66}.guide h3{margin:22px 0 6px}.guide code{background:#2a1736;padding:1px 6px;border-radius:5px;color:#ffb0a3}.guide{margin-bottom:22px}
@media(max-width:640px){.brand{font-size:17px}.stat b{font-size:28px}}
@media(prefers-reduced-motion:reduce){body::before,body::after,html::before{animation:none}}

/* ===== About Us / Co-Founders Page ===== */
.about-hero{text-align:center;padding:min(14vh,110px) 0 30px;max-width:820px;margin:0 auto}
.about-hero h1{font-family:var(--display);font-size:clamp(30px,4.5vw,48px);margin:12px 0 16px;background:linear-gradient(180deg,#fff,#d4cadf 55%,#8e8499);-webkit-background-clip:text;background-clip:text;color:transparent}
.about-hero p{font-size:18px;line-height:1.6;color:var(--muted);margin:0}
.founders-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:28px;margin:36px 0 60px}
.founder-card{display:flex;flex-direction:column;padding:32px 28px;border-radius:16px;position:relative;overflow:hidden}
.founder-card::before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--crimson),var(--violet))}
.founder-header{display:flex;align-items:center;gap:20px;margin-bottom:20px}
.founder-avatar-wrap{position:relative;width:108px;height:108px;flex-shrink:0;border-radius:50%;padding:3px;background:linear-gradient(135deg,var(--crimson),var(--violet));box-shadow:0 0 20px #e11d2a44,0 0 35px #9a4dff33}
.founder-avatar{width:100%;height:100%;border-radius:50%;object-fit:cover;display:block;background:#190e25}
.founder-names h2{font-size:23px;margin:0 0 6px;color:var(--text);font-family:var(--serif)}
.founder-role{display:inline-block;color:#ff8a7a;font-size:13px;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.founder-bio{color:#d3c9e0;font-size:15px;line-height:1.65;margin:0 0 24px;flex-grow:1}
.founder-bio p{margin:0 0 12px}.founder-bio p:last-child{margin-bottom:0}
.founder-links{display:flex;flex-wrap:wrap;gap:10px;padding-top:16px;border-top:1px solid #3a2338}
.founder-link{display:inline-flex;align-items:center;gap:7px;padding:7px 14px;border-radius:8px;background:#ffffff0a;border:1px solid #ffffff1a;color:#f2edf7;font-size:13px;font-weight:500;transition:all .18s ease}
.founder-link:hover{background:#ffffff18;border-color:#ff665588;color:#fff;text-decoration:none;box-shadow:0 0 14px #e11d2a33}
.mission-card{text-align:center;padding:38px 28px;margin-bottom:50px}
.mission-card h3{font-size:24px;margin:0 0 12px;color:var(--silver)}
.mission-card p{max-width:680px;margin:0 auto 22px;color:var(--muted);font-size:16px;line-height:1.6}



/* ===== Header Dropdown Menus (Product, Company, Resources, Legal) ===== */
.navlinks{display:flex;gap:14px;align-items:center;position:relative}
.nav-dropdown{position:relative;display:inline-flex;align-items:center}
.nav-trigger{color:#cdbfe0;font-size:14px;font-weight:600;letter-spacing:.02em;padding:8px 10px;border-radius:8px;background:transparent;border:none;cursor:pointer;display:inline-flex;align-items:center;gap:5px;font-family:inherit;transition:all .18s ease}
.nav-trigger:hover,.nav-dropdown:hover .nav-trigger,.nav-dropdown:focus-within .nav-trigger{color:#fff;background:#ffffff15}
.nav-trigger::after{content:"▾";font-size:11px;opacity:.75;transition:transform .2s ease}
.nav-dropdown:hover .nav-trigger::after,.nav-dropdown:focus-within .nav-trigger::after{transform:rotate(180deg);color:#ff8a7a}
.nav-menu{display:none;position:absolute;top:calc(100% + 4px);left:0;min-width:180px;padding:6px;border-radius:10px;background:linear-gradient(160deg,#160b22,#0b0612);border:1px solid #4a2752;box-shadow:0 18px 48px #000c,0 0 24px #e11d2a2e;z-index:9999;-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);flex-direction:column;gap:2px}
.nav-dropdown:hover .nav-menu,.nav-dropdown:focus-within .nav-menu{display:flex}
.nav-menu a{display:block;padding:8px 12px;border-radius:7px;color:#d8cde6;font-size:13.5px;font-weight:500;text-decoration:none;transition:all .15s ease}
.nav-menu a:hover{background:#ffffff15;color:#ff8a7a;text-decoration:none;transform:translateX(3px)}
@media(max-width:860px){
  .nav{height:auto;padding-top:12px;padding-bottom:12px;flex-wrap:wrap;gap:10px}
  .navlinks{flex-wrap:wrap;gap:6px}
  .nav-trigger{padding:6px 8px;font-size:13px}
}

/* ===== Structured 4-Column Footer ===== */
.footer{border-top:1px solid;border-image:linear-gradient(90deg,#e11d2a55,#9a4dff55 60%,transparent) 1;padding:50px 0 38px;color:var(--muted);font-size:14px}
.footer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:32px;margin-bottom:44px}
.footer-col{display:flex;flex-direction:column}
.footer-heading{font-family:var(--serif);font-size:15px;font-weight:700;color:var(--text);letter-spacing:.04em;margin-bottom:16px}
.footer-links{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:12px}
.footer-links li a{color:#a99dbb;font-size:14px;text-decoration:none;transition:all .18s ease}
.footer-links li a:hover{color:#ff8a7a;text-decoration:none;transform:translateX(2px);display:inline-block}
.footer-bottom{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;padding-top:28px;border-top:1px solid #ffffff12}
.footer-brand-line{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
@media(max-width:768px){.footer-grid{grid-template-columns:repeat(2,1fr);gap:28px}.footer-bottom{flex-direction:column;align-items:flex-start}}
@media(max-width:440px){.footer-grid{grid-template-columns:1fr}}

/* ===== Help Centre & Troubleshooting ===== */
.help-hero{text-align:center;padding:min(12vh,90px) 0 24px;max-width:860px;margin:0 auto}
.help-hero h1{font-family:var(--display);font-size:clamp(30px,4.5vw,46px);margin:12px 0 14px;background:linear-gradient(180deg,#fff,#d4cadf 55%,#8e8499);-webkit-background-clip:text;background-clip:text;color:transparent}
.help-hero p{font-size:17px;line-height:1.6;color:var(--muted);margin:0}
.help-search-bar{max-width:620px;margin:24px auto 0;position:relative}
.help-search-input{width:100%;padding:14px 18px 14px 44px;border-radius:12px;border:1px solid #4a2f4c;background:#140c1fe6;color:var(--text);font:inherit;font-size:15px;backdrop-filter:blur(10px);box-shadow:0 8px 30px #0008;transition:all .2s ease}
.help-search-input:focus{border-color:var(--crimson);box-shadow:0 0 0 3px #e11d2a33,0 0 24px #9a4dff33;outline:none}
.help-search-icon{position:absolute;left:15px;top:50%;transform:translateY(-50%);font-size:16px;pointer-events:none}
.help-pills{display:flex;justify-content:center;flex-wrap:wrap;gap:10px;margin:26px 0 36px}
.help-pill{padding:8px 16px;border-radius:99px;background:#ffffff0a;border:1px solid #ffffff1e;color:#d8cde6;font-size:13px;font-weight:600;cursor:pointer;transition:all .18s ease;text-decoration:none}
.help-pill:hover,.help-pill.active{background:linear-gradient(120deg,#d1121f 0%,#5b1fa8 100%);border-color:#ff4a3a88;color:#fff;text-decoration:none;box-shadow:0 0 14px #e11d2a44}
.video-card{background:linear-gradient(160deg,#190d23,#0e0816);border:1px solid #47264a;border-radius:16px;overflow:hidden;box-shadow:0 24px 60px #000c;margin:24px 0 44px}
.video-frame-wrap{position:relative;padding-bottom:56.25%;height:0;overflow:hidden;background:#000}
.video-frame-wrap iframe{position:absolute;top:0;left:0;width:100%;height:100%;border:0}
.video-info{padding:22px 26px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;border-top:1px solid #361c38}
.video-info h3{margin:0 0 6px;font-size:20px;color:var(--silver);font-family:var(--serif)}
.video-info p{margin:0;color:var(--muted);font-size:14px;max-width:680px;line-height:1.5}
.help-section{margin:40px 0}
.help-section-title{font-family:var(--serif);font-size:23px;margin:0 0 18px;display:flex;align-items:center;gap:12px;color:var(--silver)}
.help-section-title::before{content:"";width:4px;height:22px;border-radius:2px;background:linear-gradient(180deg,var(--crimson),var(--violet))}
.accordion-group{display:flex;flex-direction:column;gap:12px}
.accordion-item{border:1px solid #341e3a;border-radius:12px;background:linear-gradient(160deg,#160b20cc,#0c0612d9);overflow:hidden;transition:all .2s ease}
.accordion-item:hover{border-color:#5a2e63}
.accordion-item[open]{border-color:#e11d2a66;box-shadow:0 0 20px #e11d2a1a}
.accordion-summary{padding:16px 20px;cursor:pointer;font-weight:600;font-size:15px;color:var(--text);display:flex;justify-content:space-between;align-items:center;user-select:none}
.accordion-summary::-webkit-details-marker{display:none}
.accordion-summary::after{content:"+";font-size:18px;font-weight:700;color:#ff8a7a;transition:transform .2s ease}
.accordion-item[open] .accordion-summary::after{content:"−";color:var(--violet)}
.accordion-body{padding:0 20px 20px;color:#d1c4df;font-size:14px;line-height:1.65;border-top:1px solid #28142e}
.accordion-body p{margin:12px 0 8px}
.accordion-body ul,.accordion-body ol{margin:8px 0;padding-left:22px}
.accordion-body li{margin:5px 0}
.code-box{background:#09050d;border:1px solid #2f1736;border-radius:8px;padding:12px 14px;font-family:Consolas,Monaco,monospace;font-size:13px;color:#ffb8ac;overflow-x:auto;margin:10px 0;white-space:pre}
.badge-tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;text-transform:uppercase;margin-right:8px}
.badge-tag.bug{background:#45141b;color:#ff8a7a;border:1px solid #73222e}
.badge-tag.setup{background:#163229;color:#6fe0b0;border:1px solid #235c4b}
.badge-tag.git{background:#231a3b;color:#b98aff;border:1px solid #432e6e}
.badge-tag.mode{background:#2e1f0e;color:#f0cf8a;border:1px solid #6b5320}
.modes-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin:18px 0 28px}
.mode-card{padding:22px 20px;border-radius:12px;background:linear-gradient(160deg,#180c24,#0e0716);border:1px solid #3d2144;position:relative}
.mode-card h4{margin:0 0 8px;font-size:17px;color:var(--text);display:flex;align-items:center;gap:8px;font-family:var(--serif)}
.mode-card p{margin:0;font-size:13.5px;color:var(--muted);line-height:1.55}
.chapter-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:14px}
.chapter-item{padding:10px 14px;background:#140a1d;border:1px solid #2d1830;border-radius:8px;font-size:13px;color:var(--muted)}
.chapter-item b{color:#ff8a7a;margin-right:6px}

"""


CSS += """
/* ===== Homepage Visual Simulation & Animations ===== */
@keyframes simPulseRed {
  0% { box-shadow: 0 0 0 0 rgba(225, 29, 42, 0.7); }
  70% { box-shadow: 0 0 0 8px rgba(225, 29, 42, 0); }
  100% { box-shadow: 0 0 0 0 rgba(225, 29, 42, 0); }
}
@keyframes simPulseGreen {
  0% { box-shadow: 0 0 0 0 rgba(111, 224, 176, 0.7); }
  70% { box-shadow: 0 0 0 8px rgba(111, 224, 176, 0); }
  100% { box-shadow: 0 0 0 0 rgba(111, 224, 176, 0); }
}
@keyframes simPulseAmber {
  0% { box-shadow: 0 0 0 0 rgba(227, 189, 116, 0.7); }
  70% { box-shadow: 0 0 0 8px rgba(227, 189, 116, 0); }
  100% { box-shadow: 0 0 0 0 rgba(227, 189, 116, 0); }
}
@keyframes floatSlow {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
.pulse-red {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff4a3a;
  animation: simPulseRed 2s infinite;
}
.pulse-green {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6fe0b0;
  animation: simPulseGreen 2s infinite;
}
.pulse-amber {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e3bd74;
  animation: simPulseAmber 2s infinite;
}
.hover-float {
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
}
.hover-float:hover {
  transform: translateY(-4px);
  border-color: #ff4a3a88;
  box-shadow: 0 18px 45px rgba(0,0,0,0.7), 0 0 25px rgba(154, 77, 255, 0.25);
}
.sim-tab {
  transition: all 0.2s ease;
}
.sim-tab:hover {
  filter: brightness(1.2);
}
.sim-box {
  animation: floatSlow 6s ease-in-out infinite alternate;
}
.setup-drawer summary::-webkit-details-marker { display:none; }
.setup-drawer summary { list-style:none; }
"""



CSS += homepage.HOMEPAGE_CSS

def _escape(value) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return html.escape(str(value or ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret() -> bytes:
    value = os.getenv("SESSION_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return value.encode("utf-8")


def _sign(value: str) -> str:
    mac = hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _signed_cookie(value: str) -> str:
    return f"{value}.{_sign(value)}"


def _verify_cookie(value: str) -> str | None:
    if not value or "." not in value:
        return None
    raw, signature = value.rsplit(".", 1)
    try:
        return raw if hmac.compare_digest(signature, _sign(raw)) else None
    except RuntimeError:
        return None


class Request:
    def __init__(self, environ):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = urlsplit(environ.get("PATH_INFO", "/")).path
        self.query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        raw_cookie = cookies.SimpleCookie()
        try:
            raw_cookie.load(environ.get("HTTP_COOKIE", ""))
        except cookies.CookieError:
            pass
        self.cookies = {k: v.value for k, v in raw_cookie.items()}
        self.form = {}
        self.raw_body = b""
        if self.method == "POST":
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = MAX_BODY + 1
            if length > MAX_BODY:
                raise ValueError("Request body is too large")
            self.raw_body = environ.get("wsgi.input", BytesIO()).read(length)
            content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].lower()
            if content_type == "application/json":
                try:
                    parsed = json.loads(self.raw_body.decode("utf-8"))
                    self.form = parsed if isinstance(parsed, dict) else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.form = {}
            else:
                data = self.raw_body.decode("utf-8", errors="replace")
                self.form = {key: values[-1] for key, values in parse_qs(data, keep_blank_values=True).items()}
        self.remote = environ.get("REMOTE_ADDR", "unknown")
        self.session = None
        self.new_csrf_cookie = None
        signed = _verify_cookie(self.cookies.get(SESSION_COOKIE, ""))
        if signed:
            self.session = portal_db.get_session(signed)
        self.visitor_id = self.cookies.get("agent_visitor_id", "").strip()
        self.new_visitor_cookie = None
        if not self.visitor_id or not re.fullmatch(r"[0-9a-f-]{36}", self.visitor_id):
            self.visitor_id = str(uuid.uuid4())
            self.new_visitor_cookie = _cookie("agent_visitor_id", self.visitor_id, max_age=60*60*24*365, http_only=False)


class Response:
    def __init__(self, body="", status="200 OK", headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = list(headers or [])


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _google_oauth_settings() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Google sign-in is not configured yet. Ask the deployment owner to finish Google OAuth setup.")
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path != GOOGLE_CALLBACK_PATH or parsed.query or parsed.fragment:
        raise RuntimeError("Google sign-in callback must be the HTTPS /auth/google/callback URL.")
    return client_id, client_secret, redirect_uri


def _google_login_url(state: str, client_id: str, redirect_uri: str) -> str:
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": "openid email profile", "state": state, "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _verified_google_identity(code: str, state: str, request: Request) -> dict:
    expected_state = _verify_cookie(request.cookies.get("agent_google_state", ""))
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        raise ValueError("Google sign-in expired or could not be validated. Please try again.")
    client_id, client_secret, redirect_uri = _google_oauth_settings()
    try:
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }, timeout=10, follow_redirects=False)
        if token_response.status_code != 200:
            raise ValueError("Google could not complete sign-in. Please try again.")
        token_data = token_response.json()
        id_token = token_data.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise ValueError("Google did not return a verified identity.")
        claims_response = httpx.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token},
                                    timeout=10, follow_redirects=False)
        if claims_response.status_code != 200:
            raise ValueError("Google identity could not be verified. Please try again.")
        claims = claims_response.json()
    except httpx.HTTPError:
        raise ValueError("Google sign-in service could not be reached. Please try again.") from None
    if (claims.get("aud") != client_id or claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or not claims.get("sub") or claims.get("email_verified") not in (True, "true")):
        raise ValueError("Google account verification failed. Use a verified Google account.")
    email = claims.get("email")
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
        raise ValueError("Google did not provide a valid email address.")
    name = (claims.get("name") or "").strip()
    return {"email": email.lower().strip(), "google_sub": str(claims["sub"]), "email_verified": True, "name": name}


def _google_begin(request: Request):
    try:
        client_id, _client_secret, redirect_uri = _google_oauth_settings()
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "503 Service Unavailable")
    state = secrets.token_urlsafe(32)
    state_cookie = _cookie("agent_google_state", _signed_cookie(state), max_age=600, http_only=True)
    return _redirect(_google_login_url(state, client_id, redirect_uri), [state_cookie])


def _google_callback(request: Request):
    if request.method != "GET":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    error = request.query.get("error", [""])[0]
    code = request.query.get("code", [""])[0]
    state = request.query.get("state", [""])[0]
    clear_state = _cookie("agent_google_state", "", max_age=0, http_only=True)
    if error:
        return _redirect("/login", [clear_state])
    if not code:
        return _response("<div class='alert'>Google did not return an authorization code.</div>", request, "400 Bad Request",
                         headers=[clear_state])
    try:
        identity = _verified_google_identity(code, state, request)
        user = portal_db.get_or_create_google_user(identity["email"], identity["google_sub"], identity["email_verified"], identity.get("name", ""))
    except (ValueError, RuntimeError) as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request",
                         headers=[clear_state])
    session_headers = _new_session(user["id"])
    session_headers.append(clear_state)
    target = "/admin" if identity["email"] in _admin_emails() else "/dashboard"
    if not user.get("name"):
        suggested = identity.get("name", "")
        dest = "/onboarding/name"
        if suggested:
            dest += f"?suggested={quote(suggested)}"
        return _redirect(dest, session_headers)
    return _redirect(target, session_headers)


def _admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "") or os.getenv("ADMIN_EMAIL", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}

def _admin_password_env(email: str) -> str:
    key = "ADMIN_PASSWORD_" + re.sub(r"[^A-Z0-9]", "_", email.upper())
    specific = os.getenv(key, "")
    if specific:
        return specific
    admins = _admin_emails()
    return os.getenv("ADMIN_PASSWORD", "") if len(admins) == 1 and email in admins else ""

def _is_admin(request: Request) -> bool:
    return bool(request.session and request.session.get("email", "").lower() in _admin_emails())


def _layout(title: str, body: str, request: Request | None = None) -> str:
    signed_in = bool(request and request.session)
    is_admin = _is_admin(request) if request else False
    csrf_token = _csrf(request) if (request and signed_in) else ""
    links = footer_pages.render_header_nav_html(signed_in=signed_in, is_admin=is_admin, csrf_token=csrf_token)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="AI incident response for Python apps"><title>{_escape(title)} · {APP_NAME}</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&amp;family=Cinzel+Decorative:wght@700&amp;display=swap"><style>{CSS}</style></head><body><header class="wrap nav"><a class="brand" href="/"><span class="brand-mark">A</span>{APP_NAME}</a><nav class="navlinks">{links}</nav></header><main class="wrap">{body}</main>{footer_pages.render_footer_html()}<script src="/assets/home.js" defer></script><script src="/assets/chat.js" defer></script></body></html>"""


def _csrf(request: Request) -> str:
    if request.session:
        return request.session["csrf_token"]
    if getattr(request, "_cached_csrf_token", None):
        return request._cached_csrf_token
    token = _verify_cookie(request.cookies.get(CSRF_COOKIE, ""))
    if not token:
        token = secrets.token_urlsafe(32)
        request.new_csrf_cookie = _cookie(CSRF_COOKIE, _signed_cookie(token), max_age=7200, http_only=False)
    request._cached_csrf_token = token
    return token


def _response(body, request=None, status="200 OK", headers=None):
    defaults = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "strict-origin-when-cross-origin"),
                ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.ytimg.com https://*.youtube.com https://i.ytimg.com https://img.youtube.com; frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; child-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
    response = Response(_layout("Agent Daemon", body, request), status, defaults + list(headers or []))
    if request and request.new_csrf_cookie:
        response.headers.append(request.new_csrf_cookie)
    if request and getattr(request, "new_visitor_cookie", None):
        response.headers.append(request.new_visitor_cookie)
    return response


def _redirect(location: str, headers=None):
    return Response(b"", "303 See Other", [("Location", location), ("Cache-Control", "no-store")] + list(headers or []))


def _cookie(name: str, value: str, *, max_age: int, http_only=True):
    secure = "; Secure" if os.getenv("APP_ENV", "development").lower() == "production" else ""
    http = "; HttpOnly" if http_only else ""
    return ("Set-Cookie", f"{name}={value}; Path=/; Max-Age={max_age}; SameSite=Lax{http}{secure}")


def _csrf_valid(request: Request) -> bool:
    submitted = request.form.get("csrf", "")
    expected = _csrf(request)
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


def _require_session(request: Request):
    if not request.session:
        return _redirect("/login")
    return None

def _require_access(request: Request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request) or portal_db.user_has_active_access(request.session["user_id"]):
        return None
    return _redirect("/billing")


def _new_session(user_id: str):
    csrf = secrets.token_urlsafe(32)
    expires = (_now() + timedelta(seconds=SESSION_SECONDS)).isoformat(timespec="seconds")
    session_id = portal_db.create_session(user_id, csrf, expires)
    return [_cookie(SESSION_COOKIE, _signed_cookie(session_id), max_age=SESSION_SECONDS),
            _cookie(CSRF_COOKIE, "", max_age=0, http_only=False)]


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + digest.hex()


def _password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(expected)))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _form(title: str, intro: str, fields: str, action: str, submit: str, csrf: str) -> str:
    return f"<section class='card form-card'><h1>{title}</h1><p class='muted'>{intro}</p><form method='post' action='{action}'><input type='hidden' name='csrf' value='{_escape(csrf)}'>{fields}{submit}</form></section>"


PLANS = {
    "monthly": {"label": "Monthly", "rupees": 100, "days": 30},
    "yearly": {"label": "Yearly", "rupees": 1000, "days": 365},
}

_INCIDENT_LABELS = {
    "diagnosing": "Diagnosing", "queued": "Diagnosing", "processing": "Diagnosing",
    "diagnosed": "Diagnosed · report ready", "pr_opened": "Fix PR opened · review it",
    "needs_human": "Needs human review", "resolved": "Resolved",
}


def _base_url() -> str:
    return os.getenv("PORTAL_BASE_URL", "https://incident-agent-portal.onrender.com").strip().rstrip("/")


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _fmt_time(value) -> str:
    parsed = _parse_iso(value)
    return parsed.astimezone(IST).strftime("%d %b %Y, %H:%M IST") if parsed else "never" 


def _ago(value) -> str:
    parsed = _parse_iso(value)
    if not parsed:
        return "never"
    seconds = int((_now() - parsed).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _remaining(value) -> str:
    parsed = _parse_iso(value)
    if not parsed:
        return ""
    seconds = int((parsed - _now()).total_seconds())
    if seconds <= 0:
        return "ended"
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min left"
    if seconds < 86400:
        return f"{seconds // 3600} h left"
    return f"{seconds // 86400} days left"


def _pill(text, css="") -> str:
    return f"<span class='pill {css}'>{_escape(text)}</span>"


def _table(headers, rows, empty="Nothing here yet.") -> str:
    if not rows:
        return f"<div class='empty'>{_escape(empty)}</div>"
    head = "".join(f"<th>{_escape(item)}</th>" for item in headers)
    return f"<div class='table-wrap'><table class='table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _incident_label(status: str) -> str:
    return _INCIDENT_LABELS.get(status, str(status).replace("_", " ").title())


def _access_state(user_id: str) -> dict:
    until = portal_db.get_subscription_active_until(user_id) or ""
    active = bool(until and until > _now().isoformat(timespec="seconds"))
    kind = ""
    if until:
        conn = portal_db.get_connection()
        try:
            row = portal_db._execute(conn, "SELECT grant_type FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        finally:
            conn.close()
        kind = row["grant_type"] if row else ""
    return {"active": active, "until": until, "kind": kind,
            "remaining": _remaining(until) if active else "",
            "trial": portal_db.user_trial_status(user_id)}


def _project_state(project: dict, has_access=None):
    if has_access is None:
        until = project.get("active_until") or ""
        has_access = bool(until and until > _now().isoformat(timespec="seconds"))
    if not has_access:
        return "Access ended", "amber"
    if project.get("paused"):
        return "Paused", "amber"
    status = project.get("status", "")
    beat = _parse_iso(project.get("last_heartbeat_at") or "")
    if status == "connected":
        if beat is None:
            return "Connected", "green"
        if (_now() - beat).total_seconds() <= 900:
            return "Live", "green"
        return "No recent check-in", "amber"
    if status == "install_pr_open":
        return "Waiting for monitoring to deploy", "amber"
    return "Setup needed", "amber"


def _razorpay_keys():
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id.startswith(("rzp_test_", "rzp_live_")) or not secret:
        raise RuntimeError("Online payments are not configured yet.")
    return key_id, secret


def _gateway_ready() -> bool:
    try:
        _razorpay_keys()
        return True
    except RuntimeError:
        return False


def _razorpay_settings(plan: str = "yearly"):
    if plan not in PLANS:
        raise RuntimeError("Unknown subscription plan")
    key_id, secret = _razorpay_keys()
    raw = os.getenv(f"RAZORPAY_{plan.upper()}_AMOUNT_PAISE", "").strip()
    amount = int(raw) if raw.isdigit() else PLANS[plan]["rupees"] * 100
    if amount < 100:
        raise RuntimeError("Subscription amount must be at least 100 paise")
    return key_id, secret, amount


def _upi_uri(plan: str) -> str:
    vpa = os.getenv("UPI_ID", "7975291636@ptsbi").strip()
    name = os.getenv("UPI_PAYEE_NAME", "Pranav V Rao").strip()
    amount = PLANS[plan]["rupees"]
    parts = {"pa": vpa, "pn": name, "am": f"{amount:.2f}", "cu": "INR", "tn": f"Agent Daemon {plan}"}
    return "upi://pay?" + "&".join(f"{key}={quote(value, safe='@')}" for key, value in parts.items())


def _qr_data_uri(text: str) -> str:
    try:
        import segno
        return segno.make(text, error="m").svg_data_uri(scale=6, border=2, dark="#0b1020", light="#ffffff")
    except Exception:
        # Never fail silently: a missing 'segno' package would otherwise just hide the QR code.
        logging.getLogger(__name__).exception("Could not generate a QR code (is 'segno' installed? pip install -r requirements.txt)")
        return ""


def _after_payment(order_id: str, payment_id: str) -> None:
    order = portal_db.get_payment_order(order_id)
    if not order:
        return
    user = portal_db.get_user_by_id(order["user_id"]) or {}
    email = user.get("email") or portal_db.get_user_email(order["user_id"])
    plan = PLANS.get(order["plan"], PLANS["yearly"])
    u_name = user.get("name") or "User"
    u_phone = user.get("phone") or "Not provided"
    u_ref = user.get("referral_source") or "Not specified"
    u_org = user.get("organization") or "Not specified"
    if email:
        notifications.notify_customer(
            email, "Payment received - your Agent Daemon access is active",
            f"Thanks {u_name}! We received your payment of INR {plan['rupees']} for the {plan['label'].lower()} plan.\n"
            f"Your access is active now: {_base_url()}/dashboard", "payment_customer")
    admin_body = (
        f"New paid subscription activated: {email or order['user_id']}\n\n"
        f"Customer Details:\n"
        f"  - Name: {u_name}\n"
        f"  - Email: {email}\n"
        f"  - Mobile / WhatsApp: {u_phone}\n"
        f"  - How they found us: {u_ref}\n"
        f"  - Company / Project: {u_org}\n\n"
        f"Payment Details:\n"
        f"  - Amount: INR {plan['rupees']} ({plan['label']})\n"
        f"  - Razorpay Order ID: {order_id}\n"
        f"  - Razorpay Payment ID: {payment_id}\n\n"
        f"View admin dashboard:\n{_base_url()}/admin"
    )
    notifications.notify_admins(
        f"New paid subscription: {email or order['user_id']}",
        admin_body, "payment_admin")


def _github_setup_guide() -> str:
    """What a customer needs on GitHub before connecting a repository (shown on the home and connect pages)."""
    return (
        "<section class='card guide'><h2>Before you connect a repository</h2>"
        "<p class='muted'>Agent Daemon talks to GitHub with a <b>classic</b> personal access token. "
        "Fine-grained tokens are not supported. Two things to do first:</p>"
        "<h3>1. Make your repository private</h3>"
        "<p class='muted'>We read your source files and error logs to diagnose problems, and Auto mode only merges fixes in private repositories. "
        "A private repository keeps your code and logs away from the public.</p>"
        "<ol class='steps muted'>"
        "<li>Open your repository on <b>github.com</b> in a browser.</li>"
        "<li>Tap or click the <b>Settings</b> tab of the repository (not your profile settings).</li>"
        "<li>Stay on <b>General</b> and scroll to the very bottom, to the <b>Danger Zone</b>.</li>"
        "<li>Press <b>Change visibility</b>, then <b>Change to private</b>.</li>"
        "<li>Read the warnings, type the repository name when GitHub asks, and confirm.</li></ol>"
        "<h3>2. Create a classic token</h3>"
        "<ol class='steps muted'>"
        "<li>On GitHub press your profile picture, then <b>Settings</b>.</li>"
        "<li>At the bottom of the left menu open <b>Developer settings</b>, then <b>Personal access tokens</b>, then <b>Tokens (classic)</b>.</li>"
        "<li>Press <b>Generate new token</b>, then <b>Generate new token (classic)</b>.</li>"
        "<li>Name it <b>Agent Daemon</b> and pick how long it should last. When it expires, use <b>Update GitHub token</b> on your project page.</li>"
        "<li>Tick exactly two boxes: <code>repo</code> and <code>workflow</code>. Leave everything else unticked.</li>"
        "<li>Press <b>Generate token</b> and copy it right away. GitHub shows it only once. Paste it into the connect form.</li></ol>"
        "<h3>What the agent uses each permission for</h3>"
        "<ul class='muted'>"
        "<li><code>repo</code>: read your code, create a branch and open pull requests. Nothing is merged unless you choose Auto mode.</li>"
        "<li><code>workflow</code>: add a small test workflow file, so Auto mode has a check that must pass before merging.</li></ul>"
        "<p class='muted'>Classic tokens are not limited to one repository, so keep yours secret. "
        "You can delete the token on GitHub at any time to cut our access immediately.</p></section>")


def _page_about(request):
    body = ("""<section class="about-hero">
<div class="eyebrow">Meet the Creators</div>
<h1>About Us &amp; Co-Founders</h1>
<p>Agent Daemon is created by systems builders and software engineers dedicated to giving developer teams automated, reliable on-call intelligence without the chaos of 3 AM emergencies.</p>
</section>

<section class="founders-grid">
  <article class="card founder-card">
    <div class="founder-header">
      <div class="founder-avatar-wrap">
        <img class="founder-avatar" src="/assets/daemon-founder-abhay.webp" alt="Abhay Samuel H" width="108" height="108" loading="lazy">
      </div>
      <div class="founder-names">
        <h2>Abhay Samuel H</h2>
        <span class="founder-role">Co-Founder &amp; CTO</span>
      </div>
    </div>
    <div class="founder-bio">
      <p>Abhay is a Computer Science Engineering student at BMSCE, Bangalore, and the technical co-founder of Agent Daemon. He built the core of the product: the monitoring client that reports errors from a customer's app, the incident pipeline, the automated fix pull requests, and the customer and admin portal.</p>
      <p>He also owns testing and quality, with more than 90 automated tests covering the flows end to end. His mission with Agent Daemon is to give small teams without a dedicated on-call engineer an AI one that spots problems, finds the cause, and proposes a fix for a human to review.</p>
    </div>
    <div class="founder-links">
      <a class="founder-link" href="https://github.com/Samuel777822" target="_blank" rel="noopener">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
        GitHub
      </a>
      <a class="founder-link" href="https://github.com/Samuel777822/incident-agent" target="_blank" rel="noopener">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1h-8a1 1 0 00-1 1v6.708A2.486 2.486 0 014.5 9h8V1.5z"/></svg>
        Repository
      </a>
      <a class="founder-link" href="mailto:naveenachandra371@gmail.com">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M1.75 2h12.5c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0114.25 14H1.75A1.75 1.75 0 010 12.25v-8.5C0 2.784.784 2 1.75 2zm0 1.5a.25.25 0 00-.25.25v.725l6.5 3.9 6.5-3.9v-.725a.25.25 0 00-.25-.25H1.75zm13 2.748l-6.236 3.742a.5.5 0 01-.528 0L1.5 6.248v5.502c0 .138.112.25.25.25h12.5a.25.25 0 00.25-.25V6.248z"/></svg>
        Email
      </a>
    </div>
  </article>

  <article class="card founder-card">
    <div class="founder-header">
      <div class="founder-avatar-wrap">
        <img class="founder-avatar" src="/assets/daemon-founder-pranav.webp" alt="Pranav V Rao" width="108" height="108" loading="lazy">
      </div>
      <div class="founder-names">
        <h2>Pranav V Rao</h2>
        <span class="founder-role">Co-Founder &amp; Systems Architect</span>
      </div>
    </div>
    <div class="founder-bio">
      <p>Pranav is an AI &amp; ML Engineering student and the co-founder of Agent Daemon. He plays a key role in designing the system architecture and building the backend infrastructure that powers the platform. His contributions include backend development, architecting the system with Codex, developing the uptime monitoring setup, building and integrating the autonomous worker agent, and establishing deployment and automation workflows using Render.</p>
      <p>He also works on backend integrations, system reliability, and connecting the different components that make Agent Daemon function as a unified platform. His mission with Agent Daemon is to build reliable, AI-powered incident response infrastructure that helps smaller development teams monitor applications, investigate failures, and resolve issues more efficiently.</p>
      <p>Beyond technology, he is a defence enthusiast with a keen interest in military technology and its real-world applications.</p>
    </div>
    <div class="founder-links">
      <a class="founder-link" href="https://github.com/pranavvrao1-ai" target="_blank" rel="noopener">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
        GitHub
      </a>
      <a class="founder-link" href="https://www.linkedin.com/in/pranav-v-rao-061040393/" target="_blank" rel="noopener">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M0 1.146C0 .513.526 0 1.175 0h13.65C15.474 0 16 .513 16 1.146v13.708c0 .633-.526 1.146-1.175 1.146H1.175C.526 16 0 15.487 0 14.854V1.146zm4.943 12.248V6.169H2.542v7.225h2.401zm-1.2-8.212c.837 0 1.358-.554 1.358-1.248-.015-.709-.52-1.248-1.342-1.248-.822 0-1.359.54-1.359 1.248 0 .694.521 1.248 1.327 1.248h.016zm4.908 8.212V9.359c0-.216.016-.432.08-.586.173-.431.568-.878 1.232-.878.869 0 1.216.662 1.216 1.634v3.865h2.401V9.25c0-2.22-1.184-3.252-2.764-3.252-1.274 0-1.845.7-2.165 1.193v.025h-.016a5.54 5.54 0 01.016-.025V6.169h-2.4c.03.678 0 7.225 0 7.225h2.4z"/></svg>
        LinkedIn
      </a>
      <a class="founder-link" href="https://github.com/Samuel777822/incident-agent" target="_blank" rel="noopener">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1h-8a1 1 0 00-1 1v6.708A2.486 2.486 0 014.5 9h8V1.5z"/></svg>
        Repository
      </a>
      <a class="founder-link" href="mailto:pranavvrao1@gmail.com">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M1.75 2h12.5c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0114.25 14H1.75A1.75 1.75 0 010 12.25v-8.5C0 2.784.784 2 1.75 2zm0 1.5a.25.25 0 00-.25.25v.725l6.5 3.9 6.5-3.9v-.725a.25.25 0 00-.25-.25H1.75zm13 2.748l-6.236 3.742a.5.5 0 01-.528 0L1.5 6.248v5.502c0 .138.112.25.25.25h12.5a.25.25 0 00.25-.25V6.248z"/></svg>
        Email
      </a>
    </div>
  </article>
</section>

<section class="card mission-card">
  <h3>Our Mission</h3>
  <p>Agent Daemon was conceived to eliminate the stress of production emergencies for fast-moving engineering teams. By combining continuous telemetry analysis, intelligent diagnosis, and automated pull requests, we make reliable 24/7 on-call engineering accessible to everyone.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/login">Get Started with Agent Daemon</a>
    <a class="button" href="/">How It Works</a>
  </div>
</section>
""")
    return _response(body, request)


def _page_onboarding_name(request: Request):
    gate = _require_session(request)
    if gate:
        return gate
    user_id = request.session["user_id"]
    next_dest = "/admin" if _is_admin(request) else "/dashboard"

    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Please try again.</div>", request, "403 Forbidden")
        name = request.form.get("name", "").strip()
        if name:
            portal_db.update_user_name(user_id, name)
            request.session["name"] = name
        return _redirect(next_dest)

    # GET
    current_name = request.session.get("name", "") or request.query.get("suggested", [""])[0]
    body = (
        "<section class='card form-card'>"
        "<div class='eyebrow'>Welcome to Agent Daemon</div>"
        "<h1>What is your name?</h1>"
        "<p class='muted'>Tell us your name so your dashboard, notifications, and projects reflect who you are.</p>"
        "<form method='post' action='/onboarding/name'>"
        f"<input type='hidden' name='csrf' value='{_csrf(request)}'>"
        "<div class='field'>"
        "<label for='name'>Full Name</label>"
        f"<input id='name' name='name' type='text' placeholder='e.g. Alex Smith' value='{_escape(current_name)}' maxlength='120' autofocus required>"
        "<small>Your name helps personalize your incident management experience.</small>"
        "</div>"
        "<div class='actions'>"
        "<button class='button primary' type='submit'>Continue</button>"
        f"<a class='button' href='{next_dest}'>Skip for now</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    return _response(body, request)




# --- Live Chat & Visitor Alert Endpoints -------------------------------------

def _page_chat_js(request: Request) -> Response:
    return Response(chat_widget.CHAT_JS, "200 OK",
                    [("Content-Type", "application/javascript; charset=utf-8"),
                     ("Cache-Control", "public, max-age=300"), ("X-Content-Type-Options", "nosniff")])


def _api_visitor_track(request: Request) -> Response:
    if request.method != "POST":
        return Response(b"{}", "405 Method Not Allowed", [("Content-Type", "application/json")])
    visitor_id = request.visitor_id
    path = request.form.get("path", "/") if isinstance(request.form, dict) else "/"
    ref = request.form.get("referrer", "") if isinstance(request.form, dict) else ""
    should_notify = portal_db.track_visitor_visit(visitor_id)
    if should_notify:
        notifications.notify_admins(
            f"New visitor arrived on portal ({path})",
            f"A visitor arrived at {path}.\nReferrer: {ref or 'Direct'}\nVisitor ID: {visitor_id}\n"
            f"Live admin console: {_base_url()}/admin#live-chats",
            "visitor_alert"
        )
    resp = Response(json.dumps({"ok": True}), "200 OK", [("Content-Type", "application/json")])
    if getattr(request, "new_visitor_cookie", None):
        resp.headers.append(request.new_visitor_cookie)
    return resp


def _api_chat_messages(request: Request) -> Response:
    conv = portal_db.get_or_create_conversation(request.visitor_id)
    after = request.query.get("after", [""])[0]
    msgs = portal_db.list_chat_messages(conv["id"], after_time=after)
    return Response(json.dumps({"messages": msgs, "conversation_id": conv["id"]}), "200 OK",
                    [("Content-Type", "application/json"), ("Cache-Control", "no-store")])


def _api_chat_send(request: Request) -> Response:
    if request.method != "POST":
        return Response(b"{}", "405 Method Not Allowed", [("Content-Type", "application/json")])
    form = request.form if isinstance(request.form, dict) else {}
    text = form.get("text", "").strip()
    contact = form.get("contact", "").strip()
    if not text:
        return Response(json.dumps({"error": "Empty message"}), "400 Bad Request", [("Content-Type", "application/json")])

    conv = portal_db.get_or_create_conversation(request.visitor_id)
    if contact:
        if "@" in contact:
            portal_db.update_conversation_visitor_details(conv["id"], conv.get("visitor_name", ""), contact)
        else:
            portal_db.update_conversation_visitor_details(conv["id"], contact, conv.get("visitor_email", ""))

    # Save visitor message
    portal_db.add_chat_message(conv["id"], "visitor", text)

    # Notify admins about user question / chat inquiry
    contact_info = f" (Contact: {contact})" if contact else ""
    notifications.notify_admins(
        f"Live chat inquiry from visitor{contact_info}",
        f"Visitor message:\n\"{text}\"\n\nReply in live admin dashboard:\n{_base_url()}/admin#live-chats",
        "chat_inquiry"
    )

    # Generate AI Assistant response
    history = portal_db.list_chat_messages(conv["id"])
    reply = chatbot.answer_visitor_query(text, history)
    bot_msg = portal_db.add_chat_message(conv["id"], "bot", reply, "AI Assistant")

    return Response(json.dumps({
        "reply": reply,
        "created_at": bot_msg["created_at"],
        "conversation_id": conv["id"]
    }), "200 OK", [("Content-Type", "application/json")])


def _api_chat_save_contact(request: Request) -> Response:
    if request.method != "POST":
        return Response(b"{}", "405 Method Not Allowed", [("Content-Type", "application/json")])
    contact = request.form.get("contact", "").strip() if isinstance(request.form, dict) else ""
    if contact:
        conv = portal_db.get_or_create_conversation(request.visitor_id)
        if "@" in contact:
            portal_db.update_conversation_visitor_details(conv["id"], conv.get("visitor_name", ""), contact)
        else:
            portal_db.update_conversation_visitor_details(conv["id"], contact, conv.get("visitor_email", ""))
    return Response(json.dumps({"ok": True}), "200 OK", [("Content-Type", "application/json")])


def _api_admin_chat_reply(request: Request) -> Response:
    if not request.session or not _is_admin(request):
        return Response(json.dumps({"error": "Unauthorized"}), "403 Forbidden", [("Content-Type", "application/json")])
    if request.method != "POST":
        return Response(b"{}", "405 Method Not Allowed", [("Content-Type", "application/json")])
    form = request.form if isinstance(request.form, dict) else {}
    conv_id = form.get("conversation_id", "").strip()
    text = form.get("text", "").strip()
    if not conv_id or not text:
        return Response(json.dumps({"error": "Missing conversation_id or text"}), "400 Bad Request", [("Content-Type", "application/json")])
    admin_name = request.session.get("name") or request.session.get("email", "").split("@")[0].capitalize()
    msg = portal_db.add_chat_message(conv_id, "admin", text, f"{admin_name} (Founder)")
    return Response(json.dumps({"ok": True, "message": msg}), "200 OK", [("Content-Type", "application/json")])


def _api_admin_chat_messages(request: Request) -> Response:
    if not request.session or not _is_admin(request):
        return Response(json.dumps({"error": "Unauthorized"}), "403 Forbidden", [("Content-Type", "application/json")])
    conv_id = request.query.get("conversation_id", [""])[0]
    after = request.query.get("after", [""])[0]
    msgs = portal_db.list_chat_messages(conv_id, after_time=after) if conv_id else []
    return Response(json.dumps({"messages": msgs}), "200 OK", [("Content-Type", "application/json")])



def _page_help(request: Request) -> Response:
    body = """<section class="help-hero">
<div class="eyebrow">Documentation &amp; Support</div>
<h1>Agent Daemon Help Centre</h1>
<p>Guides, architecture workflows, video demonstration, framework setup, and troubleshooting playbooks to keep your production Python services self-healing.</p>

<div class="help-search-bar">
  <span class="help-search-icon" aria-hidden="true">&#128269;</span>
  <input id="help-search" class="help-search-input" type="search" placeholder="Search guides, errors, tokens, GitHub setup, auto-fix, offline..." oninput="filterHelp(this.value)">
</div>

<nav class="help-pills">
  <a class="help-pill active" href="javascript:void(0)" onclick="filterCategory('all', this)">All Topics</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('video', this)">Video Demo</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('modes', this)">Remediation Modes</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('setup', this)">GitHub &amp; Setup</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('frameworks', this)">Frameworks</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('troubleshooting', this)">Troubleshooting</a>
  <a class="help-pill" href="javascript:void(0)" onclick="filterCategory('faq', this)">FAQ</a>
</nav>
</section>

<!-- 1. Video Demo Section -->
<section class="video-card help-section" id="video" data-category="video">
  <div class="video-frame-wrap">
    <iframe src="https://www.youtube.com/embed/Y3neE_B2d-M?rel=0" title="Agent Daemon Demo &amp; Walkthrough" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>
  </div>
  <div class="video-info">
    <div>
      <h3>Full Video Walkthrough &amp; Live Demo</h3>
      <p>Watch how Agent Daemon monitors a live Python app (Coffee Shop API), catches a real-world checkout bug deployed to Render, diagnoses the root cause, generates a verified fix PR, and auto-merges it without human intervention.</p>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <a class="button primary" href="https://www.youtube.com/watch?v=Y3neE_B2d-M" target="_blank" rel="noopener">Watch on YouTube &#8599;</a>
      <a class="button" href="/contact">Ask Questions</a>
    </div>
  </div>
  <div style="padding:16px 26px 22px;background:#11091a;border-top:1px solid #28142e">
    <div style="font-size:12px;font-weight:700;letter-spacing:.08em;color:#ff8a7a;text-transform:uppercase;margin-bottom:8px">Video Key Moments &amp; Chapters</div>
    <div class="chapter-list">
      <div class="chapter-item"><b>0:00 &ndash; 0:45</b> What Agent Daemon is &amp; the autonomous on-call AI engineer mission.</div>
      <div class="chapter-item"><b>0:45 &ndash; 1:15</b> Google sign-in &amp; plans: Monthly (&#8377;100), Yearly (&#8377;1,000), or 1-day free trial.</div>
      <div class="chapter-item"><b>1:15 &ndash; 2:00</b> Connecting a repository via GitHub PAT and zero-touch monitoring installer.</div>
      <div class="chapter-item"><b>2:00 &ndash; 2:40</b> Live demo: production coffee shop API running with healthy payments.</div>
      <div class="chapter-item"><b>2:40 &ndash; 3:15</b> Inducing a live checkout failure &amp; deploying to Render. Error alerted immediately!</div>
      <div class="chapter-item"><b>3:15 &ndash; 3:50</b> AI diagnosis: stack trace analyzed, culprit lines traced, and safe patch generated.</div>
      <div class="chapter-item"><b>3:50 &ndash; 4:25</b> Fix pull request opened on GitHub &amp; GitHub Actions CI test suite runs.</div>
      <div class="chapter-item"><b>4:25 &ndash; 4:55</b> Autonomous auto-merge: checks pass, PR squashes into main, Render redeploys fixed app!</div>
      <div class="chapter-item"><b>4:55 &ndash; 5:15</b> Incident post-mortem report, cause explanation, unified diff, &amp; admin console.</div>
    </div>
  </div>
</section>

<!-- 2. Remediation Modes Section -->
<section class="help-section" id="modes" data-category="modes">
  <h2 class="help-section-title">Remediation Modes: How Much Autonomy Do You Want?</h2>
  <p class="muted">You control the degree of autonomy for each connected repository. Switch modes at any time on your project settings page:</p>
  
  <div class="modes-grid">
    <article class="mode-card">
      <div style="margin-bottom:8px"><span class="badge-tag mode" style="background:#163229;color:#6fe0b0;border-color:#235c4b">Fully Autonomous</span></div>
      <h4>Automatic Mode (<code>auto</code>)</h4>
      <p>The complete self-healing loop shown in the demo video. When an incident occurs, Agent Daemon diagnoses the cause, writes a surgical patch, creates a branch, opens a PR, waits for your GitHub Actions CI tests to pass, and automatically squash-merges into your base branch. Requires a private repository.</p>
    </article>

    <article class="mode-card">
      <div style="margin-bottom:8px"><span class="badge-tag mode" style="background:#231a3b;color:#b98aff;border-color:#432e6e">Recommended Default</span></div>
      <h4>Pull Request Only (<code>pr_only</code>)</h4>
      <p>Human-in-the-loop remediation. Agent Daemon analyzes the failure, generates a syntax-validated patch, and opens a GitHub Pull Request with the unified diff and incident explanation. Merging is left to your developers. Ideal for production teams requiring manual review.</p>
    </article>

    <article class="mode-card">
      <div style="margin-bottom:8px"><span class="badge-tag mode">Triage &amp; Observability</span></div>
      <h4>Report Only (<code>report_only</code>)</h4>
      <p>Non-intrusive error monitoring. Clusters repeated exceptions into incidents, explains the likely root cause and culprit commits, and suggests manual fix recommendations on your dashboard. Does not create branches or open pull requests.</p>
    </article>
  </div>
</section>

<!-- 3. GitHub & Setup Guides -->
<section class="help-section" id="setup" data-category="setup">
  <h2 class="help-section-title">Getting Started &amp; GitHub Configuration</h2>
  <div class="accordion-group">

    <details class="accordion-item" open>
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Step 1</span> How to generate a classic GitHub Personal Access Token (PAT)</span>
      </summary>
      <div class="accordion-body">
        <p>Agent Daemon interacts with GitHub using a <b>classic personal access token</b>. Here is how to create one in 60 seconds:</p>
        <ol>
          <li>On <b>github.com</b>, click your profile avatar in the top right &rarr; <b>Settings</b>.</li>
          <li>In the left sidebar, scroll to the bottom and click <b>Developer settings</b>.</li>
          <li>Click <b>Personal access tokens</b> &rarr; <b>Tokens (classic)</b>.</li>
          <li>Click <b>Generate new token</b> &rarr; <b>Generate new token (classic)</b>.</li>
          <li>Set Note to <code>Agent Daemon</code> and choose an expiration duration (e.g. 90 days or no expiration).</li>
          <li>Check exactly two permission scopes:
            <ul>
              <li><code>repo</code> &mdash; Full control of private repositories (to read source evidence, create fix branches, and open pull requests).</li>
              <li><code>workflow</code> &mdash; Update GitHub Action workflows (used to install automated test validation).</li>
            </ul>
          </li>
          <li>Click <b>Generate token</b> at the bottom. <b>Copy your token immediately</b> &mdash; GitHub will not show it again.</li>
        </ol>
        <p><b>Security note:</b> Tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC) using <code>TOKEN_ENCRYPTION_KEY</code> and are never logged or stored in plain text. You can revoke the token on GitHub at any time to cut off access.</p>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Step 2</span> Connecting your repository &amp; Zero-Touch Installer</span>
      </summary>
      <div class="accordion-body">
        <p>Once you have access (via trial or plan), navigate to <b><a href="/projects/new">Projects &rarr; Connect repository</a></b>:</p>
        <ol>
          <li>Enter the repository <b>Owner / Name</b> (e.g. <code>my-org/backend-api</code>).</li>
          <li>Select your base branch (e.g. <code>main</code> or leave empty for default).</li>
          <li>Choose your remediation mode (<code>Automatic</code>, <code>Pull request</code>, or <code>Report only</code>).</li>
          <li>Paste your classic GitHub token and click <b>Connect project</b>.</li>
        </ol>
        <p><b>What the Zero-Touch Installer does automatically:</b></p>
        <ul>
          <li>Opens a pull request that adds <code>incident_agent_monitor.py</code> (the lightweight client).</li>
          <li>Inserts <code>import incident_agent_monitor</code> at the top of your app entry point (e.g. <code>app.py</code>, <code>main.py</code>, <code>wsgi.py</code>).</li>
          <li>Creates <code>incident_agent_config.json</code> with your project's ingest URL and unique ingest key.</li>
          <li>Adds <code>.github/workflows/agent-daemon-tests.yml</code> so PRs have test validation checks.</li>
          <li>Auto-merges the PR if repository permissions allow, or provides a direct link to merge on GitHub.</li>
        </ul>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Step 3</span> Repository Privacy &amp; Public vs. Private Repos</span>
      </summary>
      <div class="accordion-body">
        <p>Agent Daemon treats public and private repositories differently for strict security reasons:</p>
        <ul>
          <li><b>Private repositories:</b> Support all three modes (<code>Automatic</code>, <code>Pull request</code>, <code>Report only</code>). Your ingest key and source files remain confidential.</li>
          <li><b>Public repositories:</b> Automatically locked to <b>Pull request only</b> mode. Because ingest keys in public repositories are visible to anyone, auto-merge is prohibited to prevent malicious error injections from pushing unauthorized code into production. A human must always review and merge PRs in public repos.</li>
        </ul>
      </div>
    </details>

  </div>
</section>

<!-- 4. Framework Integration Guides -->
<section class="help-section" id="frameworks" data-category="frameworks">
  <h2 class="help-section-title">Framework Setup &amp; Manual Integration</h2>
  <p class="muted">If you prefer manual setup rather than the automated PR, or use custom entrypoints, simply drop <code>incident_agent_monitor.py</code> into your project root and add one line to your app:</p>

  <div class="accordion-group">

    <details class="accordion-item" open>
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Framework</span> Flask, FastAPI, Django, &amp; WSGI Integration</span>
      </summary>
      <div class="accordion-body">
        <p><b>Flask (<code>app.py</code> or <code>wsgi.py</code>):</b></p>
        <div class="code-box">import incident_agent_monitor  # noqa: F401 (Agent Daemon error monitoring)
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Hello Production"</div>

        <p><b>FastAPI / Starlette / ASGI (<code>main.py</code>):</b></p>
        <div class="code-box">import incident_agent_monitor  # Starts error hook &amp; heartbeat thread
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "ok"}</div>

        <p><b>Django (<code>wsgi.py</code> or <code>asgi.py</code>):</b></p>
        <div class="code-box">import incident_agent_monitor  # Place before get_wsgi_application()
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
application = get_wsgi_application()</div>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Config</span> Configuration file: <code>incident_agent_config.json</code></span>
      </summary>
      <div class="accordion-body">
        <p>Place this file in the working directory of your app (the same folder where your Python command is executed):</p>
        <div class="code-box">{
  "ingest_url": "https://incident-agent-portal.onrender.com/ingest",
  "ingest_key": "YOUR_PROJECT_INGEST_KEY"
}</div>
        <p>The client will automatically load this config, spawn a daemonized heartbeat thread that reports health every 5 minutes, and attach an uncaught exception hook (<code>sys.excepthook</code>) and root logging handler.</p>
      </div>
    </details>

  </div>
</section>

<!-- 5. Troubleshooting Playbooks -->
<section class="help-section" id="troubleshooting" data-category="troubleshooting">
  <h2 class="help-section-title">Troubleshooting Playbooks &amp; Failure Modes</h2>
  <p class="muted">Direct solutions for common issues based on Agent Daemon's architecture and safety gates:</p>

  <div class="accordion-group">

    <details class="accordion-item" open>
      <summary class="accordion-summary">
        <span><span class="badge-tag bug">Issue 1</span> Project shows "Offline" / No Heartbeat Received</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> The dashboard project badge says <code>Offline</code> or "Last check-in: Never / 3 hours ago".</p>
        <p><b>Root Causes &amp; Solutions:</b></p>
        <ol>
          <li><b>App has not restarted since monitoring was merged:</b> Deploy or restart your application so the new <code>import incident_agent_monitor</code> line is executed.</li>
          <li><b>Free tier hosting is sleeping:</b> Services on Render, Railway, or Fly.io free tiers sleep after 15 minutes without web requests. Once asleep, the background heartbeat stops. Send a request to your app or configure a free pinger (e.g. UptimeRobot) hitting your app's health route every 10 minutes.</li>
          <li><b>Missing <code>incident_agent_config.json</code>:</b> Confirm that <code>incident_agent_config.json</code> is located in the working directory of your running Python process.</li>
          <li><b>Outbound network restriction:</b> Verify that your hosting environment permits outbound HTTPS connections to <code>https://incident-agent-portal.onrender.com</code>.</li>
        </ol>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag git">Issue 2</span> GitHub Installation PR Fails (401 / 403 / 404)</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> When connecting a repository or clicking "Install monitoring", the portal displays a GitHub API error.</p>
        <p><b>Resolution by Error Code:</b></p>
        <ul>
          <li><b>HTTP 401 Bad credentials:</b> The GitHub Personal Access Token was entered with extra spaces, has expired, or was revoked on GitHub. Go to GitHub &rarr; Developer Settings &rarr; Tokens (classic), generate a fresh token with <code>repo</code> and <code>workflow</code> scopes, and click <b>Update GitHub token</b> on your project page.</li>
          <li><b>HTTP 403 Forbidden:</b> The token is missing the <code>repo</code> scope, or the repository belongs to an organization that requires <b>SSO authorization</b> for personal access tokens. Click "Configure SSO" next to the token in your GitHub settings to approve your organization.</li>
          <li><b>HTTP 404 Not Found:</b> GitHub cannot locate the repository or branch. Confirm that the <code>owner/repository</code> spelling is exact (case-sensitive) and that the default branch (e.g. <code>main</code> instead of <code>master</code>) exists.</li>
        </ul>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag bug">Issue 3</span> Auto-Fix Skipped or Marked "Needs Human"</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> An incident appears in the dashboard, but its status changes to <code>needs_human</code> without opening a fix pull request.</p>
        <p><b>Why this happens (Built-in Safety Gates):</b></p>
        <p>Agent Daemon will NEVER perform automated code changes unless all 5 safety gates pass:</p>
        <ol>
          <li><b>Category is not a code bug:</b> If the failure is classified as a database outage, third-party API downtime, missing environment variable, or server out-of-memory, Agent Daemon refuses to alter source code.</li>
          <li><b>Confidence is not "high":</b> If the AI diagnostic engine has any doubt about the root cause, it safely escalates to human review.</li>
          <li><b>Bug is already resolved:</b> If the bug is no longer present in the latest commit on your base branch, the fix is skipped.</li>
          <li><b>Safety flag:</b> The diagnostic LLM explicitly marked <code>safe_to_auto_fix = False</code>.</li>
          <li><b>Maximum attempts exceeded:</b> Agent Daemon limits automated fixes to 2 attempts per incident to prevent endless loops.</li>
        </ol>
        <p><b>Action:</b> Click into the incident to read the full root cause analysis, timeline, and recommended manual fix.</p>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag git">Issue 4</span> Fix PR Opened on GitHub but Not Auto-Merging</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> The fix branch and PR were created on GitHub, but status remains <code>pending</code> or <code>failed</code> on the portal.</p>
        <p><b>Troubleshooting Checklist:</b></p>
        <ul>
          <li><b>CI checks must pass:</b> Auto-merge requires at least one completed GitHub Actions check with conclusion <code>success</code>. If tests failed in CI, Agent Daemon safely halts and leaves the PR open for inspection.</li>
          <li><b>Branch protection rules:</b> If your repository enforces required code reviews (e.g. "Require at least 1 approval before merging"), GitHub's API blocks automated merges. You can either authorize bot merges or merge manually with one click on GitHub.</li>
          <li><b>Public repository restriction:</b> As a strict security measure, public repositories never auto-merge.</li>
          <li><b>Merge conflicts:</b> If other commits were pushed to your base branch while CI was running, the PR will await human rebasing.</li>
        </ul>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag bug">Issue 5</span> Errors Occurring in App Not Appearing on Dashboard</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> You triggered an error in your application, but no incident was created on the dashboard.</p>
        <p><b>Verification Steps:</b></p>
        <ol>
          <li><b>Is the exception caught?</b> Bare <code>try ... except: pass</code> or <code>try ... except Exception as e: print(e)</code> blocks swallow errors before they reach <code>sys.excepthook</code>. Use <code>logging.exception("Failed processing")</code> to ship handled exceptions.</li>
          <li><b>Check Ingest Key:</b> If you rotated your ingest key on the dashboard, make sure to update <code>incident_agent_config.json</code> with the new key.</li>
          <li><b>Test Ingestion directly via cURL:</b> Run this in your terminal to verify network connectivity to the portal:
            <div class="code-box">curl -X POST https://incident-agent-portal.onrender.com/ingest \
  -H "Content-Type: application/json" \
  -H "X-Ingest-Key: YOUR_KEY" \
  -d '{"message":"Test diagnostic error","traceback":"Traceback: line 42 ZeroDivisionError","service":"test"}'</div>
            A successful response returns <code>{"status":"accepted","incident_id":"..."}</code>.
          </li>
        </ol>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">
        <span><span class="badge-tag setup">Issue 6</span> Render Free Tier Sleep &amp; Background Worker</span>
      </summary>
      <div class="accordion-body">
        <p><b>Symptom:</b> Cold starts take 30-50 seconds or background tasks take longer to trigger on free tier.</p>
        <p><b>Explanation:</b> Render's free tier spins down web instances after 15 minutes of inactivity. When a new error occurs, the instance wakes up automatically, but ingestion may take 30 seconds for the first request.</p>
        <p><b>Tip:</b> You can set up a free uptime monitor (such as UptimeRobot, BetterStack, or cron-job.org) targeting <code>https://incident-agent-portal.onrender.com/health</code> every 10 minutes to keep the worker continuously warm.</p>
      </div>
    </details>

  </div>
</section>

<!-- 6. FAQ Section -->
<section class="help-section" id="faq" data-category="faq">
  <h2 class="help-section-title">Frequently Asked Questions</h2>
  <div class="accordion-group">

    <details class="accordion-item">
      <summary class="accordion-summary">Does Agent Daemon run my proprietary code on its servers?</summary>
      <div class="accordion-body">
        <p><b>No.</b> Agent Daemon only reads source code files as text evidence via GitHub API to diagnose problems and construct minimal AST-checked diffs. Customer code and test suites are never executed on Agent Daemon servers.</p>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">Can Agent Daemon accidentally break my database or infrastructure?</summary>
      <div class="accordion-body">
        <p><b>No.</b> Auto-fix is strictly confined to Python source code bugs. Database migrations, credentials, environment variables, Docker configurations, and infrastructure errors are strictly escalated to human engineers with <code>needs_human</code> status.</p>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">Can I disconnect a project or revoke access?</summary>
      <div class="accordion-body">
        <p>Yes. You can pause monitoring or permanently delete a project from your dashboard with one click. To instantly revoke all permissions on GitHub, simply delete the Personal Access Token in your GitHub account.</p>
      </div>
    </details>

    <details class="accordion-item">
      <summary class="accordion-summary">How does the 1-day free trial work?</summary>
      <div class="accordion-body">
        <p>Every customer is eligible for one 1-day free trial. Submit a request on the <a href="/billing">Billing page</a>, and our founders (Abhay &amp; Pranav) will approve it promptly, activating 24 hours of unrestricted autonomous incident response.</p>
      </div>
    </details>

  </div>
</section>

<!-- 7. Need More Help CTA -->
<section class="card mission-card" style="margin-top:40px;text-align:center">
  <h3>Still Need Help or Have a Complex Setup?</h3>
  <p>Our co-founders and support engineers are available to assist with custom frameworks, private VPCs, and enterprise on-call requirements.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/contact">Contact Support &amp; Founders</a>
    <a class="button" href="/about">About Co-Founders</a>
    <a class="button" href="https://github.com/Samuel777822/incident-agent" target="_blank" rel="noopener">GitHub Project</a>
  </div>
</section>

<script>
function filterHelp(query) {
  var q = (query || "").toLowerCase().trim();
  var items = document.querySelectorAll(".accordion-item, .mode-card, .chapter-item");
  items.forEach(function(el) {
    var txt = el.textContent.toLowerCase();
    if (!q || txt.indexOf(q) !== -1) {
      el.style.display = "";
      if (q && el.tagName.toLowerCase() === "details") {
        el.open = true;
      }
    } else {
      el.style.display = "none";
    }
  });
}

function filterCategory(cat, btn) {
  document.querySelectorAll(".help-pills .help-pill").forEach(function(p) { p.classList.remove("active"); });
  if (btn) btn.classList.add("active");
  var sections = document.querySelectorAll(".help-section");
  sections.forEach(function(s) {
    if (cat === "all" || s.getAttribute("data-category") === cat || s.id === cat) {
      s.style.display = "";
    } else {
      s.style.display = "none";
    }
  });
}
</script>
"""
    return _response(body, request)


def _page_contact(request: Request) -> Response:
    prefill_email = request.session.get("email", "") if request.session else ""
    prefill_name = request.session.get("name", "") if request.session else ""

    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Please refresh and try again.</div>", request, "403 Forbidden")
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            error_html = "<div class='alert'>Please provide your name, email, and message.</div>"
            return _render_contact_page(request, error_html, name, email, subject, message)

        if not EMAIL_RE.fullmatch(email):
            error_html = "<div class='alert'>Please provide a valid email address.</div>"
            return _render_contact_page(request, error_html, name, email, subject, message)

        # Save to database
        portal_db.create_support_message(name, email, subject or "General Support Inquiry", message)

        # Notify admins
        email_subj = f"[Agent Daemon Support] {subject or 'New Inquiry'} from {name}"
        email_body = (
            f"You received a new message from the Agent Daemon Contact & Support page:\n\n"
            f"From: {name} ({email})\n"
            f"Subject: {subject or 'General Support Inquiry'}\n"
            f"Time: {_now()}\n\n"
            f"Message:\n{message}\n\n"
            f"View in Admin Operations:\n{_base_url()}/admin#support-inquiries"
        )
        notifications.notify_admins(email_subj, email_body, "support_inquiry")

        success_html = (
            "<section class='card form-card' style='text-align:center'>"
            "<div class='eyebrow'>Message Received</div>"
            "<h1>Thanks for reaching out!</h1>"
            f"<p class='muted'>We've delivered your message to our founders and support team. We will get back to you at <b>{_escape(email)}</b> shortly.</p>"
            "<div class='actions' style='justify-content:center;margin-top:24px'>"
            "<a class='button primary' href='/'>Return to Home</a>"
            "<a class='button' href='/about'>Meet the Team</a>"
            "</div>"
            "</section>"
        )
        return _response(success_html, request)

    return _render_contact_page(request, "", prefill_name, prefill_email, "", "")


def _render_contact_page(request: Request, flash: str = "", name: str = "", email: str = "", subject: str = "", message: str = "") -> Response:
    body = (
        "<section class='about-hero' style='padding-bottom:10px'>"
        "<div class='eyebrow'>Support &amp; Inquiries</div>"
        "<h1>Contact Our Team</h1>"
        "<p>Have questions about Agent Daemon, need help setting up monitoring on your repository, or want to discuss enterprise features? Reach out directly to our founders and engineering team.</p>"
        "</section>"
        f"<section class='card form-card' style='margin-top:20px;max-width:580px'>"
        f"{flash}"
        "<form method='post' action='/contact'>"
        f"<input type='hidden' name='csrf' value='{_csrf(request)}'>"
        "<div class='field'>"
        "<label for='name'>Your Name</label>"
        f"<input id='name' name='name' type='text' placeholder='e.g. Alex Morgan' value='{_escape(name)}' required maxlength='100'>"
        "</div>"
        "<div class='field'>"
        "<label for='email'>Your Work Email</label>"
        f"<input id='email' name='email' type='email' placeholder='name@company.com' value='{_escape(email)}' required maxlength='120'>"
        "</div>"
        "<div class='field'>"
        "<label for='subject'>Subject</label>"
        f"<input id='subject' name='subject' type='text' placeholder='e.g. Question about private repository auto-remediation' value='{_escape(subject)}' maxlength='150'>"
        "</div>"
        "<div class='field'>"
        "<label for='message'>Message</label>"
        f"<textarea id='message' name='message' rows='5' style='width:100%;padding:12px 13px;border-radius:9px;border:1px solid #34425e;background:#0b1324;color:var(--text);font:inherit;resize:vertical' placeholder='Tell us what you need help with...' required maxlength='3000'>{_escape(message)}</textarea>"
        "</div>"
        "<div class='actions' style='margin-top:22px'>"
        "<button class='button primary' type='submit'>Send Message to Support</button>"
        "<a class='button' href='/about'>About Founders</a>"
        "</div>"
        "</form>"
        "<div style='margin-top:28px;padding-top:20px;border-top:1px solid #28182f;font-size:13px;color:var(--muted)'>"
        "Direct founder inboxes: <a href='mailto:pranavvrao1@gmail.com'>pranavvrao1@gmail.com</a> · <a href='mailto:naveenachandra371@gmail.com'>naveenachandra371@gmail.com</a>"
        "</div>"
        "</section>"
    )
    return _response(body, request)


def _page_home(request):
    if request.session:
        return _redirect("/admin" if _is_admin(request) else "/dashboard")
    return _response(homepage.render_homepage_html(), request)


def _page_signup(request):
    # Accounts are created through Google sign-in only. Old email links land on the sign-in page.
    return _redirect("/login")


def _page_login(request):
    if request.method != "GET":
        return _redirect("/login")
    body = ("<section class='card form-card'><h1>Sign in to Agent Daemon</h1>"
            "<p class='muted'>Agent Daemon turns your app's error logs into incident reports and, if you allow it, reviewable pull requests with fixes. "
            "Sign in with your Google account. New accounts are created automatically.</p>"
            "<div class='actions'><a class='button primary' href='/auth/google'>Continue with Google</a></div>"
            "<p class='muted'><small>We only use your verified Google email address. We never see your Google password.</small></p></section>")
    return _response(body, request)


_ADMIN_MESSAGES = {
    "trial_approved": ("green", "Trial approved. The customer has access for 1 day, starting now."),
    "trial_rejected": ("amber", "Trial request rejected."),
    "payment_confirmed": ("green", "Payment confirmed. The customer's paid access is active now."),
    "payment_rejected": ("amber", "Payment rejected."),
    "access_granted": ("green", "Access granted."),
    "access_revoked": ("amber", "Access revoked. The customer's projects are paused until access is granted again."),
    "already_done": ("amber", "That request was already handled by someone else. The list below is up to date."),
    "not_found": ("red", "That customer no longer exists."),
    "bad_request": ("red", "That action was not valid."),
    "test_email_ok": ("green", "Test email accepted by the provider for every admin. Check both inboxes."),
    "test_email_failed": ("red", "Test email failed. See the Email status table below for the exact reason."),
}


def _page_admin(request):
    if not request.session:
        return _redirect("/login")
    if not _is_admin(request):
        return _response("<h1>Not found</h1>", request, "404 Not Found")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        return _admin_action(request)
    return _admin_view(request)


def _admin_action(request):
    form = request.form
    actor = request.session["email"]
    action = form.get("action", "")
    done = lambda key: _redirect("/admin?msg=" + key)
    if action == "approve_trial":
        trial = portal_db.approve_trial_request(form.get("request_id", ""), actor)
        if not trial:
            return done("already_done")
        notifications.notify_customer(
            trial["email"], "Your Agent Daemon trial is approved",
            f"Your 1-day free trial is active until {_fmt_time(trial['active_until'])}.\nConnect your project: {_base_url()}/dashboard",
            "trial_approved")
        return done("trial_approved")
    if action == "reject_trial":
        trial = portal_db.admin_review_trial_request(form.get("request_id", ""), "rejected", actor)
        if not trial:
            return done("already_done")
        notifications.notify_customer(trial["email"], "Update on your Agent Daemon trial request",
                                      "Your trial request was not approved this time. You can pick a plan any time: "
                                      f"{_base_url()}/billing", "trial_rejected")
        return done("trial_rejected")
    if action == "confirm_payment":
        try:
            payment = portal_db.approve_manual_payment(form.get("payment_id", ""), actor)
        except ValueError:
            return done("bad_request")
        if not payment:
            return done("already_done")
        notifications.notify_customer(
            payment["email"], "Agent Daemon payment confirmed",
            f"We confirmed your payment. Your paid access is active until {_fmt_time(payment['active_until'])}.\n{_base_url()}/dashboard",
            "payment_confirmed")
        return done("payment_confirmed")
    if action == "reject_payment":
        payment = portal_db.admin_review_manual_payment(form.get("payment_id", ""), "rejected", actor)
        if not payment:
            return done("already_done")
        notifications.notify_customer(
            payment["email"], "Agent Daemon payment could not be confirmed",
            "We could not find your payment, so access was not activated. If you did pay, reply to this email with a screenshot "
            "of the successful UPI receipt.", "payment_rejected")
        return done("payment_rejected")
    if action in ("grant", "revoke"):
        user_id = form.get("user_id", "")
        email = portal_db.get_user_email(user_id)
        if not email:
            return done("not_found")
        if action == "revoke":
            portal_db.admin_revoke_access(user_id)
            return done("access_revoked")
        kind, _, days = form.get("grant", "").partition(":")
        if kind not in ("trial", "paid") or not days.isdigit() or not 1 <= int(days) <= 3650:
            return done("bad_request")
        until = portal_db.admin_grant_access(user_id, int(days), kind, actor)
        notifications.notify_customer(email, "Your Agent Daemon access is active",
                                      f"Access is active until {_fmt_time(until)}.\n{_base_url()}/dashboard", "access_granted")
        return done("access_granted")
    if action == "send_test_email":
        results = notifications.send_test_to_admins()
        return done("test_email_ok" if results and all(ok for _, ok, _ in results) else "test_email_failed")
    return done("bad_request")


def _admin_view(request):
    csrf = _escape(_csrf(request))
    admins = _admin_emails()
    stats = portal_db.admin_stats(admins)
    trials = portal_db.admin_list_trial_requests()
    payments = portal_db.admin_list_manual_payments()
    users = [u for u in portal_db.admin_list_users() if u["email"].lower() not in admins]
    projects = portal_db.admin_projects()
    now = _now().isoformat(timespec="seconds")
    states = [_project_state(p) for p in projects]
    live = sum(1 for state, _ in states if state in ("Live", "Connected"))
    flash = ""
    message = _ADMIN_MESSAGES.get(request.query.get("msg", [""])[0])
    if message:
        flash = f"<div class='{'pill ' if message[0] != 'red' else 'alert '}{message[0]}'>{_escape(message[1])}</div>"

    def card(value, label):
        return f"<div class='stat'><b>{_escape(value)}</b><span>{_escape(label)}</span></div>"
    cards = "".join([
        card(stats["customers"], "customers"),
        card(f"{stats['active']}", f"active ({stats['paid_active']} paid, {stats['trial_active']} trial)"),
        card(stats["inactive"], "without access"),
        card(stats["pending_trials"], "trial requests to review"),
        card(stats["pending_payments"], "UPI payments to confirm"),
        card(f"{live}/{stats['projects']}", "apps live / connected"),
        card(stats["open_incidents"], f"open incidents ({stats['needs_human']} need a human)"),
    ])

    pending_trials = [t for t in trials if t["status"] == "pending"]
    trial_rows = []
    for t in pending_trials:
        c_name = t.get("user_name") or t.get("name") or ""
        c_phone = t.get("user_phone") or t.get("phone") or ""
        c_ref = t.get("user_referral") or t.get("referral_source") or ""
        c_org = t.get("user_organization") or t.get("organization") or ""
        cust_cell = f"<b>{_escape(c_name)}</b><br><small class='muted'>{_escape(t['email'])}</small>" if c_name else _escape(t['email'])
        phone_cell = f"<a href='tel:{_escape(c_phone)}' style='color:#75a7ff'>{_escape(c_phone)}</a>" if c_phone else "<span class='muted'>—</span>"
        info_parts = []
        if c_ref:
            info_parts.append(f"<b>Via:</b> {_escape(c_ref)}")
        if c_org:
            info_parts.append(f"<b>Org:</b> {_escape(c_org)}")
        info_cell = "<br>".join(info_parts) if info_parts else "<span class='muted'>—</span>"
        trial_rows.append(
            f"<tr><td>{cust_cell}</td><td>{phone_cell}</td><td>{info_cell}</td>"
            f"<td>{_escape(_fmt_time(t['requested_at']))}</td><td>"
            f"<form method='post' action='/admin' class='actions'><input type='hidden' name='csrf' value='{csrf}'>"
            f"<input type='hidden' name='request_id' value='{_escape(t['id'])}'>"
            "<button class='button primary' name='action' value='approve_trial' type='submit'>Approve 1-day trial</button>"
            "<button class='button danger' name='action' value='reject_trial' type='submit'>Reject</button></form></td></tr>"
        )

    pending_payments = [p for p in payments if p["status"] == "pending"]
    payment_rows = []
    for p in pending_payments:
        p_name = p.get("user_name") or p.get("name") or ""
        p_phone = p.get("user_phone") or p.get("phone") or ""
        p_ref = p.get("user_referral") or p.get("referral_source") or ""
        p_org = p.get("user_organization") or p.get("organization") or ""
        cust_cell = f"<b>{_escape(p_name)}</b><br><small class='muted'>{_escape(p['email'])}</small>" if p_name else _escape(p['email'])
        phone_cell = f"<a href='tel:{_escape(p_phone)}' style='color:#75a7ff'>{_escape(p_phone)}</a>" if p_phone else "<span class='muted'>—</span>"
        info_parts = []
        if p_ref:
            info_parts.append(f"<b>Via:</b> {_escape(p_ref)}")
        if p_org:
            info_parts.append(f"<b>Org:</b> {_escape(p_org)}")
        info_cell = "<br>".join(info_parts) if info_parts else "<span class='muted'>—</span>"
        payment_rows.append(
            f"<tr><td>{cust_cell}</td><td>{phone_cell}</td><td>{info_cell}</td>"
            f"<td>₹{_escape(p['amount'])} · {_escape(p['plan'])}</td>"
            f"<td><code>{_escape(p['transaction_ref'])}</code><br><small class='muted'>{_escape(_fmt_time(p['created_at']))}</small></td><td>"
            f"<form method='post' action='/admin' class='actions'><input type='hidden' name='csrf' value='{csrf}'>"
            f"<input type='hidden' name='payment_id' value='{_escape(p['id'])}'>"
            f"<button class='button primary' name='action' value='confirm_payment' type='submit'>I received ₹{_escape(p['amount'])} · grant {30 if p['plan'] == 'monthly' else 365} days</button>"
            "<button class='button danger' name='action' value='reject_payment' type='submit'>Not received</button></form></td></tr>"
        )
    attention = ""
    if trial_rows:
        attention += "<h2>Trial requests</h2>" + _table(["Customer", "Mobile / WhatsApp", "Found Via / Org", "Requested", "Decision"], trial_rows)
    if payment_rows:
        attention += ("<h2>UPI payments to confirm</h2><p class='muted'>Open your Paytm app, find this exact reference and amount, "
                      "then confirm. Confirm only money you can see.</p>" + _table(["Customer", "Mobile / WhatsApp", "Found Via / Org", "Claimed", "Reference", "Decision"], payment_rows))
    if not attention:
        attention = "<h2>Needs your attention</h2><div class='empty'>Nothing waiting. New trial requests and UPI payments show up here.</div>"

    pending_trial_users = {t["user_id"] for t in pending_trials}
    pending_payment_users = {p["user_id"] for p in pending_payments}
    users.sort(key=lambda u: (0 if (u['id'] in pending_trial_users or u['id'] in pending_payment_users) else 1 if (u.get('active_until') or '') > now else 2))
    customer_rows = []
    for user in users:
        until = user.get("active_until") or ""
        active = bool(until and until > now)
        if active:
            kind = "Paid" if user.get("grant_type") == "paid" else "Trial"
            status = _pill(f"{kind} · {_remaining(until)}", "green") + f"<br><small class='muted'>until {_escape(_fmt_time(until))}</small>"
            action = (f"<form method='post' action='/admin'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='user_id' value='{_escape(user['id'])}'>"
                      "<button class='button danger' name='action' value='revoke' type='submit'>Revoke access</button></form>")
        else:
            if user["id"] in pending_trial_users:
                status = _pill("Trial requested", "amber")
            elif user["id"] in pending_payment_users:
                status = _pill("Payment to confirm", "amber")
            elif until:
                status = _pill("Expired", "red") + f"<br><small class='muted'>{_escape(_fmt_time(until))}</small>"
            else:
                status = _pill("No access")
            action = (f"<form method='post' action='/admin' class='inline'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='user_id' value='{_escape(user['id'])}'>"
                      "<select name='grant' aria-label='Access to grant'><option value='trial:1'>Free trial · 1 day</option>"
                      "<option value='paid:30'>Paid · 30 days</option><option value='paid:365'>Paid · 365 days</option></select>"
                      "<button class='button primary' name='action' value='grant' type='submit'>Grant access</button></form>")
        u_name = user.get('name') or ""
        u_phone = user.get('phone') or ""
        u_ref = user.get('referral_source') or ""
        u_org = user.get('organization') or ""
        cust_label = f"<b>{_escape(u_name)}</b><br><small class='muted'>{_escape(user['email'])}</small>" if u_name else _escape(user['email'])
        contact_parts = []
        if u_phone:
            contact_parts.append(f"<a href='tel:{_escape(u_phone)}' style='color:#75a7ff'>{_escape(u_phone)}</a>")
        if u_ref:
            contact_parts.append(f"<small class='muted'>Via: {_escape(u_ref)}</small>")
        if u_org:
            contact_parts.append(f"<small class='muted'>Org: {_escape(u_org)}</small>")
        contact_cell = "<br>".join(contact_parts) if contact_parts else "<span class='muted'>—</span>"
        customer_rows.append(f"<tr><td>{cust_label}<br><small class='muted'>Joined {_escape(_fmt_time(user['created_at']))}</small></td><td>{contact_cell}</td><td>{status}</td><td>{action}</td></tr>")

    project_rows = []
    for project, (state, css) in zip(projects, states):
        project_rows.append(f"<tr><td>{_escape(project['name'])}<br><small class='muted'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}</small></td>"
                            f"<td>{_escape(project['owner_email'])}</td><td>{_pill(state, css)}</td>"
                            f"<td>{_escape(_ago(project.get('last_heartbeat_at')))}</td><td>{_escape(project['open_incidents'])}</td></tr>")
    incident_rows = []
    for item in portal_db.admin_recent_incidents(10):
        pr = f"<a href='{_escape(item['pr_url'])}' target='_blank' rel='noopener'>PR · CI {_escape(item['ci_status'])}</a>" if item.get("pr_url") else ""
        incident_rows.append(f"<tr><td><span title='{_escape(_fmt_time(item['last_seen']))}'>{_escape(_ago(item['last_seen']))}</span><br><small class='muted'>{_escape(_fmt_time(item['last_seen']))}</small></td><td>{_escape(item['project_name'])}<br><small class='muted'>{_escape(item['owner_email'])}</small></td>"
                             f"<td>{_escape(item['signature'])}</td><td>{_escape(_incident_label(item['status']))}</td><td>{pr}</td></tr>")

    worker_seen = portal_db.worker_last_seen()
    worker_ok = bool(worker_seen and (_now() - _parse_iso(worker_seen)).total_seconds() < 180)
    worker = (_pill(f"Worker running · seen {_ago(worker_seen)}", "green") if worker_ok else
              _pill(f"Worker not seen recently ({_ago(worker_seen)})", "amber"))
    provider = notifications.provider()
    email_state = (_pill(f"Email: {provider}, from {notifications.sender()}", "green") if notifications.configured() else
                   _pill("Email not configured. Set BREVO_API_KEY and EMAIL_FROM in Render", "red"))
    payments_state = _pill("Instant payments on (Razorpay)", "green") if _gateway_ready() else _pill("Instant payments off: manual UPI confirmation", "amber")
    notif_rows = []
    for item in portal_db.recent_notifications(10):
        result = _pill("accepted", "green") if item["ok"] else _pill("failed", "red")
        notif_rows.append(f"<tr><td><span title='{_escape(_fmt_time(item['created_at']))}'>{_escape(_ago(item['created_at']))}</span><br><small class='muted'>{_escape(_fmt_time(item['created_at']))}</small></td><td>{_escape(item['recipient'])}</td><td>{_escape(item['kind'])}</td>"
                          f"<td>{result}<br><small class='muted'>{_escape(item['detail'])}</small></td></tr>")
    system = (f"<h2>System</h2><div class='stats'>{worker}{email_state}{payments_state}{_pill('Database: ' + portal_db.database_kind())}</div>"
              f"<form method='post' action='/admin' style='margin-top:12px'><input type='hidden' name='csrf' value='{csrf}'>"
              "<button class='button' name='action' value='send_test_email' type='submit'>Send test email to both admins</button></form>"
              "<h3>Email status</h3><p class='muted'>Accepted means the email provider took the message. It does not guarantee inbox delivery.</p>"
              + _table(["When", "To", "Kind", "Result"], notif_rows, "No emails sent yet."))

    # Live visitor chat conversations
    chat_convs = portal_db.admin_list_chat_conversations(15)
    chat_rows = []
    for c in chat_convs:
        c_title = _escape(c.get("visitor_name") or c.get("visitor_email") or f"Visitor {c['visitor_id'][:8]}")
        last_m = _escape(c.get("last_message") or "(No messages)")
        tag_cls = "pill green" if c.get("last_sender") == "visitor" else "pill"
        tag_txt = "New message" if c.get("last_sender") == "visitor" else "Responded"
        chat_rows.append(f"<tr><td><b>{c_title}</b><br><small class='muted'>{_escape(_fmt_time(c['updated_at']))}</small></td>"
                         f"<td><span class='{tag_cls}'>{tag_txt}</span></td>"
                         f"<td>{last_m}</td>"
                         f"<td><button class='button' type='button' onclick='openAdminChat(\"{_escape(c['id'])}\", \"{c_title}\")'>Open Chat</button></td></tr>")
    chat_table = _table(["Visitor", "Status", "Latest Message", "Action"], chat_rows, "No visitor conversations yet.")
    chat_section = f"<h2 id='live-chats'>Live visitor conversations &amp; inquiries</h2>{chat_table}"

    # Support messages
    support_msgs = portal_db.admin_list_support_messages(20)
    support_rows = []
    for s in support_msgs:
        support_rows.append(f"<tr><td><b>{_escape(s['name'])}</b><br><small class='muted'>{_escape(s['email'])}</small></td>"
                            f"<td><b>{_escape(s['subject'])}</b><br><span style='font-size:13px;color:var(--muted)'>{_escape(s['message'])}</span></td>"
                            f"<td><small class='muted'>{_escape(_fmt_time(s['created_at']))}</small></td>"
                            f"<td><a class='button' href='mailto:{_escape(s['email'])}?subject=Re:%20{quote(s['subject'])}'>Reply by Email</a></td></tr>")
    support_table = _table(["From", "Inquiry", "Time", "Action"], support_rows, "No support inquiries submitted yet.")
    support_section = f"<h2 id='support-inquiries'>Support Inquiries (Contact Form)</h2>{support_table}" 

    admin_chat_modal = """
<div id="admin-chat-modal" style="display:none;position:fixed;bottom:20px;right:20px;width:380px;height:520px;background:#120a1b;border:1px solid #ff4a3a66;border-radius:14px;box-shadow:0 15px 50px #000;z-index:99999;flex-direction:column;overflow:hidden">
  <div style="padding:12px 16px;background:#1e0f2c;border-bottom:1px solid #3a2338;display:flex;justify-content:space-between;align-items:center">
    <b id="admin-chat-header" style="color:#fff;font-size:14px">Visitor Chat</b>
    <button onclick="document.getElementById('admin-chat-modal').style.display='none'" style="background:none;border:none;color:#aaa;cursor:pointer;font-size:18px">&times;</button>
  </div>
  <div id="admin-chat-msgs" style="flex:1;padding:14px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;background:#09060d"></div>
  <div style="padding:10px;border-top:1px solid #3a2338;display:flex;gap:8px;background:#120a1b">
    <input id="admin-reply-input" type="text" placeholder="Type a reply as Founder / Admin..." style="flex:1;padding:8px 10px;border-radius:6px;border:1px solid #3a2338;background:#060408;color:#fff">
    <button id="admin-reply-btn" onclick="sendAdminReply()" class="button primary" style="padding:6px 14px">Reply</button>
  </div>
</div>
<script>
var currentConvId = null;
var adminLastPoll = "";
function openAdminChat(convId, title) {
  currentConvId = convId;
  adminLastPoll = "";
  document.getElementById('admin-chat-header').textContent = "Chat: " + title;
  document.getElementById('admin-chat-msgs').innerHTML = "";
  document.getElementById('admin-chat-modal').style.display = 'flex';
  pollAdminMessages();
}
function pollAdminMessages() {
  if (!currentConvId) return;
  fetch('/api/admin/chat/messages?conversation_id=' + encodeURIComponent(currentConvId) + (adminLastPoll ? '&after=' + encodeURIComponent(adminLastPoll) : ''))
    .then(r => r.json())
    .then(data => {
      if (data && data.messages) {
        var box = document.getElementById('admin-chat-msgs');
        data.messages.forEach(m => {
          var div = document.createElement('div');
          var isMe = m.sender === 'admin';
          div.style.cssText = 'padding:8px 12px;border-radius:10px;font-size:13px;max-width:85%;word-break:break-word;' + 
            (isMe ? 'align-self:flex-end;background:#5b1fa8;color:#fff;' : 'align-self:flex-start;background:#211432;border:1px solid #3a2338;color:#eee;');
          var tStr = '';
          if (m.created_at) {
            try {
              var d = new Date(m.created_at);
              tStr = ' <span style="font-size:10px;opacity:0.6;font-weight:normal;float:right">' + d.toLocaleTimeString('en-IN', {timeZone: 'Asia/Kolkata', hour: '2-digit', minute:'2-digit'}) + ' IST</span>';
            } catch(e) {}
          }
          div.innerHTML = (m.sender_name ? '<div style="font-size:10px;font-weight:700;color:#ff8a7a;margin-bottom:3px">' + m.sender_name + tStr + '</div>' : (tStr ? '<div style="margin-bottom:2px">' + tStr + '</div>' : '')) + m.text;
          box.appendChild(div);
          adminLastPoll = m.created_at;
        });
        box.scrollTop = box.scrollHeight;
      }
    });
}
function sendAdminReply() {
  var input = document.getElementById('admin-reply-input');
  var text = input.value.trim();
  if (!text || !currentConvId) return;
  input.value = "";
  fetch('/api/admin/chat/reply', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({conversation_id: currentConvId, text: text})
  }).then(r => r.json()).then(() => pollAdminMessages());
}
setInterval(() => {
  if (document.getElementById('admin-chat-modal').style.display === 'flex') pollAdminMessages();
}, 4000);
</script>
"""

    body = (f"<section class='section'><div class='eyebrow'>Administrator</div><h1>Operations</h1>"
            f"<p class='muted'>Signed in as {_escape(request.session['email'])}</p>{flash}<div class='statgrid'>{cards}</div>{attention}"
            f"<h2>Customers</h2>{_table(['Customer', 'Contact & Referral', 'Access', 'Action'], customer_rows, 'No customer accounts yet.')}"
            f"<h2>Applications</h2>{_table(['App', 'Owner', 'State', 'Last check-in', 'Open incidents'], project_rows, 'No applications connected yet.')}"
            f"<h2>Recent incidents and fixes</h2>{_table(['When', 'App', 'Error', 'Agent status', 'Fix'], incident_rows, 'No incidents yet.')}"
            f"{chat_section}"
            f"{support_section}"
            f"{system}</section>" + admin_chat_modal)
    return _response(body, request)


def _page_trial_request(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    name = str(request.form.get("name", "")).strip()
    phone = str(request.form.get("phone", "")).strip()
    referral_source = str(request.form.get("referral_source", "")).strip()
    organization = str(request.form.get("organization", "")).strip()
    try:
        trial = portal_db.create_trial_request(
            request.session["user_id"],
            name=name,
            phone=phone,
            referral_source=referral_source,
            organization=organization
        )
    except ValueError as exc:
        return _response(f"<section class='card form-card'><h1>Trial not available</h1><p>{_escape(exc)}</p><a class='button primary' href='/billing'>Choose a plan</a></section>", request, "409 Conflict")
    if trial.get("created"):
        user_name = name or trial.get("name") or request.session.get("name") or "User"
        user_phone = phone or trial.get("phone") or "Not provided"
        user_ref = referral_source or trial.get("referral_source") or "Not specified"
        user_org = organization or trial.get("organization") or "Not specified"
        email_body = (
            f"New 1-day free trial request from {request.session['email']}.\n\n"
            f"Customer Details:\n"
            f"  - Name: {user_name}\n"
            f"  - Email: {request.session['email']}\n"
            f"  - Mobile / WhatsApp: {user_phone}\n"
            f"  - How they found us: {user_ref}\n"
            f"  - Organization / Project: {user_org}\n"
            f"  - Requested At: {_fmt_time(trial.get('requested_at'))}\n\n"
            f"Review and approve or reject on the admin page:\n{_base_url()}/admin"
        )
        notifications.notify_admins(
            f"New trial request: {request.session['email']}",
            email_body, "trial_request")
    return _response("<section class='card form-card'><h1>Request received</h1>"
                     "<p>Your request is saved and waiting for approval. When an admin approves it your 1-day trial starts immediately; "
                     "you will see it on your dashboard and get an email.</p>"
                     "<a class='button primary' href='/billing'>Back to plan &amp; billing</a></section>", request)

def _page_dashboard(request):
    if request.method != "GET":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    user_id = request.session["user_id"]
    access = _access_state(user_id)
    projects = portal_db.list_projects_with_activity(user_id)
    if access["active"]:
        label = "Paid plan" if access["kind"] == "paid" else "Free trial"
        banner = (f"<article class='card'><div class='row'><div><div class='eyebrow'>Your plan</div><h3>{label}</h3>"
                  f"<p class='muted'>{_escape(access['remaining'])} · active until {_escape(_fmt_time(access['until']))}</p></div>"
                  "<a class='button' href='/billing'>Plan &amp; billing</a></div></article>")
    else:
        if access["trial"] == "pending":
            message, cta = "Your trial request is waiting for approval. Your projects stay paused until then.", "See request status"
        elif access["until"]:
            message, cta = "Your access has ended, so monitoring is paused. Choose a plan to switch it back on.", "Choose a plan"
        else:
            message, cta = "You do not have access yet. Request a free 1-day trial or pick a plan to start monitoring.", "Get access"
        banner = (f"<article class='card'><div class='row'><div><div class='eyebrow'>Access needed</div><h3>Monitoring is off</h3>"
                  f"<p class='muted'>{_escape(message)}</p></div><a class='button primary' href='/billing'>{cta}</a></div></article>")
    cards = []
    for project in projects:
        state, css = _project_state(project, access["active"])
        latest = project.get("latest_incident")
        if latest:
            pr = (f" · <a href='{_escape(latest['pr_url'])}' target='_blank' rel='noopener'>PR</a>" if latest.get("pr_url") else "")
            activity = (f"<p class='muted'>Latest: <a href='/projects/{_escape(project['id'])}/incidents/{_escape(latest['id'])}'>{_escape(latest['signature'])}</a>"
                        f" · {_escape(_incident_label(latest['status']))}{pr}</p>")
        else:
            activity = "<p class='muted'>No incidents yet. The agent is watching for errors.</p>" if css == "green" else ""
        hint = ""
        if state == "Setup needed":
            hint = "<p class='muted'>Open the project to finish setup.</p>"
        elif state == "Waiting for monitoring to deploy":
            hint = "<p class='muted'>Monitoring was added to your repository. It starts when your app redeploys.</p>"
        cards.append(f"<a class='card' href='/projects/{_escape(project['id'])}'><div class='row'><h3>{_escape(project['name'])}</h3>{_pill(state, css)}</div>"
                     f"<p class='muted'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])} · {_escape(project['branch'])} · {_escape(project['mode'])} mode</p>"
                     f"<p class='muted'>Last check-in: {_escape(_ago(project.get('last_heartbeat_at')))} · Open incidents: {project['incident_open']} of {project['incident_total']}</p>"
                     f"{activity}{hint}</a>")
    listing = "".join(cards) or "<div class='empty'>No projects yet. Connect a Python app to start monitoring it.</div>"
    connect = "<a class='button primary' href='/projects/new'>Connect a project</a>" if access["active"] else ""
    feed_rows = []
    for item in portal_db.recent_activity(user_id, 8):
        pr = f"<a href='{_escape(item['pr_url'])}' target='_blank' rel='noopener'>Open PR</a>" if item.get("pr_url") else ""
        feed_rows.append(f"<tr><td><span title='{_escape(_fmt_time(item['last_seen']))}'>{_escape(_ago(item['last_seen']))}</span><br><small class='muted'>{_escape(_fmt_time(item['last_seen']))}</small></td><td>{_escape(item['project_name'])}</td>"
                         f"<td><a href='/projects/{_escape(item['project_id'])}/incidents/{_escape(item['id'])}'>{_escape(item['signature'])}</a></td>"
                         f"<td>{_escape(_incident_label(item['status']))}</td><td>{pr}</td></tr>")
    feed = _table(["When", "Project", "Error", "What the agent did", "Fix"], feed_rows,
                  "Nothing to report yet. When your app raises an error, the agent's diagnosis and fix appear here.")
    name_val = request.session.get('name', '').strip()
    signed_label = f"Signed in as <b>{_escape(name_val)}</b> ({_escape(request.session['email'])}) · <a href='/onboarding/name'>Edit name</a>" if name_val else f"Signed in as {_escape(request.session['email'])} · <a href='/onboarding/name'>Add your name</a>"
    body = (f"<section class='section'><div class='row'><div><div class='eyebrow'>Workspace</div><h1>Your projects</h1>"
            f"<p class='muted'>{signed_label}</p></div>{connect}</div>{banner}"
            f"<div class='grid'>{listing}</div><h2>Agent activity</h2>{feed}</section>")
    return _response(body, request)


def _encrypt_token(token: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii")).encrypt(token.encode("utf-8")).decode("ascii")
    except ImportError as exc:
        raise RuntimeError("Token encryption requires cryptography") from exc
    except Exception as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc


def _decrypt_token(ciphertext: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to use saved GitHub credentials")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise RuntimeError("Saved GitHub credential could not be decrypted") from exc


def _page_new_project(request):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method == "GET":
        fields = """<div class='field'><label>Project name</label><input name='name' required maxlength='80' placeholder='Checkout service'></div>
<div class='field'><label>GitHub repository</label><input name='repo' required placeholder='owner/repository'><small>Make sure this repository is private first. The steps are at the top of this page.</small></div>
<div class='field'><label>GitHub token</label><input name='github_token' type='password' autocomplete='off' required><small>Stored encrypted. It is never displayed after saving. Paste a <b>classic</b> token with the <code>repo</code> and <code>workflow</code> scopes ticked. Fine-grained tokens are not supported.</small></div>
<div class='field'><label>Branch (optional)</label><input name='branch' value='' placeholder='Leave empty to use your repository default' maxlength='100'></div>
<div class='field'><label>Agent mode</label><select name='mode'><option value='report' selected>Report only</option><option value='pr'>Pull request</option><option value='auto'>Auto (merge only after passing CI)</option></select><small>Pull request mode opens a reviewable PR. Auto mode also merges only after GitHub reports at least one completed passing check and no failing or pending checks. With no checks, the PR stays open.</small></div>
<div class='field'><label>App URL (optional)</label><input name='app_url' type='url' placeholder='https://app.example.com'></div>
<div class='field'><label class='checkbox'><input name='allow_install' type='checkbox' value='yes' required><span>I authorize Agent Daemon to add its monitoring code to this repository through a reviewable pull request.</span></label></div>
<div class='field'><label class='checkbox'><input name='allow_ai_processing' type='checkbox' value='yes' required><span>I understand that selected error logs, tracebacks, and relevant repository source files will be sent to Groq for AI diagnosis.</span></label></div>
<div class='field'><label class='checkbox'><input name='allow_remediation' type='checkbox' value='yes'><span>For Pull request or Auto mode, I authorize small, high-confidence Python fixes as pull requests. The agent will not run my code or tests. Auto mode may merge only after all GitHub checks it can see pass; no checks, failed checks, or unavailable checks leave the PR open.</span></label></div>"""
        body = _github_setup_guide() + _form("Connect a project", "We only monitor after you authorize the installation.", fields,
                     "/projects/new", "<button class='button primary' type='submit'>Save project</button>", _csrf(request))
        return _response(body, request)
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    if request.form.get("allow_install") != "yes" or request.form.get("allow_ai_processing") != "yes":
        return _response("<div class='alert'>Authorize monitoring installation and AI diagnosis data processing before continuing.</div>", request, "400 Bad Request")
    repo_match = REPO_RE.fullmatch(request.form.get("repo", "").strip())
    token = request.form.get("github_token", "").strip()
    mode = request.form.get("mode", "report")
    name = request.form.get("name", "").strip()
    branch = request.form.get("branch", "").strip()
    if not repo_match or not token or not name or mode not in ("report", "pr", "auto"):
        return _response("<div class='alert'>Check the repository, token, project name, branch, and mode.</div>", request, "400 Bad Request")
    if mode in ("pr", "auto") and request.form.get("allow_remediation") != "yes":
        return _response("<div class='alert'>Authorize pull request remediation before selecting Pull request or Auto mode.</div>", request, "400 Bad Request")
    try:
        ciphertext = _encrypt_token(token)
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}. Set it before connecting projects.</div>", request, "503 Service Unavailable")
    owner, repo = repo_match.group(1), repo_match.group(2)
    try:
        repo_info = validate_repository_access(owner=owner, repo=repo.removesuffix(".git"), token=token)
    except GitHubInstallError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request")
    branch = resolve_branch(owner=owner, repo=repo.removesuffix(".git"), token=token, requested=branch, repo_info=repo_info)
    mode_note = ""
    if mode == "auto" and not repo_info.get("private"):
        mode = "pr"
        mode_note = ("<div class='alert'>This repository is public, so fixes are opened as pull requests for a person to review "
                     "instead of merging automatically.</div>")
    ingest_key = secrets.token_urlsafe(32)
    ingest_hash = hashlib.sha256(ingest_key.encode()).hexdigest()
    project_id = portal_db.create_project(request.session["user_id"], name=name,
        repo_owner=owner, repo_name=repo.removesuffix(".git"), branch=branch, mode=mode,
        token_ciphertext=ciphertext, ingest_key_hash=ingest_hash,
        app_url=request.form.get("app_url", "").strip(), ai_consent_at=portal_db._now(),
        ingest_key_ciphertext=_encrypt_token(ingest_key))
    portal_db.audit(project_id, "project_connected", {"repo": f"{owner}/{repo}", "mode": mode})
    portal_db.audit(project_id, "ai_diagnosis_consent", {"scope": "selected logs, tracebacks, and repository source sent to Groq"})
    if mode in ("pr", "auto"):
        portal_db.audit(project_id, "remediation_consent", {"mode": mode, "auto_merge_requires_passing_github_checks": mode == "auto"})
    project = {"repo_owner": owner, "repo_name": repo.removesuffix(".git"), "branch": branch}
    result = _install_monitoring(project_id, request.session["user_id"], project, token, ingest_key)
    summary = _install_summary(result, project_id) + mode_note
    return _response(f"<section class='card'><h1>Project saved</h1><p class='muted'>{_escape(name)} is connected. The agent starts watching as soon as monitoring is live.</p></section>{summary}"
                     f"<p><a class='button primary' href='/projects/{_escape(project_id)}'>View project</a></p>", request, "201 Created")


def _page_project(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        paused = request.form.get("paused") == "yes"
        conn = portal_db.get_connection()
        try:
            portal_db._execute(conn, "UPDATE projects SET paused=? WHERE id=? AND user_id=?",
                               (1 if paused else 0, project_id, request.session["user_id"]))
            conn.commit()
        finally:
            conn.close()
        portal_db.audit(project_id, "project_paused" if paused else "project_resumed")
        return _redirect(f"/projects/{project_id}")
    incidents = portal_db.list_incidents(project_id)
    table = incident_board.render_board_section(project_id, incidents, project["mode"])
    paused = bool(project["paused"])
    button = ("Resume agent" if paused else "Pause agent")
    install_card = (f"<article class='card'><h3>Monitoring pull request</h3><p class='muted'>Monitoring was added through this pull request. If it is not merged yet, merge it to switch monitoring on.</p><a class='button primary' href='{_escape(project['install_pr_url'])}'>View installation PR</a></article>" if project.get("install_pr_url") else f"<article class='card'><h3>Install monitoring</h3><p class='muted'>Adds monitoring to your repository through a pull request and merges it automatically when it can.</p><form method='post' action='/projects/{_escape(project_id)}/install'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button primary' type='submit'>Install monitoring</button></form></article>")
    if project.get("ci_workflow") == "missing" and project.get("mode") == "auto":
        install_card = _workflow_fix_card(project_id, request) + install_card
    body = f"<section class='section'><p><a href='/dashboard'>← Projects</a></p><div class='row'><div><div class='eyebrow'>Project</div><h1>{_escape(project['name'])}</h1><p class='muted'><a href='https://github.com/{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}</a> · {_escape(project['branch'])} · {_escape(project['mode']).title()} mode</p></div><form method='post'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='paused' value='{'no' if paused else 'yes'}'><button class='button {'primary' if paused else 'danger'}' type='submit'>{button}</button></form></div><div class='stats'><span class='pill {'amber' if paused else 'green'}'>{'Paused' if paused else _escape(project['status'].replace('_',' ').title())}</span><span class='pill'>Mode · {_escape(project['mode'])}</span><span class='pill'>Last check-in · {_escape(_ago(project.get('last_heartbeat_at')))}</span></div><h2>Incident history</h2>{table}<section class='grid'>{install_card}<article class='card'><h3>Update GitHub token</h3><p class='muted'>Use a classic token with the repo and workflow scopes ticked. The new token replaces the saved one and is never shown again.</p><form method='post' action='/projects/{_escape(project_id)}/github-token'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>New GitHub token</label><input name='github_token' type='password' autocomplete='new-password' required minlength='20' maxlength='500'></div><button class='button primary' type='submit'>Validate and save token</button></form></article><article class='card'><h3>Ingest key</h3><p class='muted'>Rotate the project key if it is exposed. The new key appears once.</p><form method='post' action='/projects/{_escape(project_id)}/rotate-key'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button' type='submit'>Rotate key</button></form></article><article class='card'><h3>Delete project data</h3><p class='muted'>Remove this project, its incidents, logs, fixes, and stored GitHub token.</p><form method='post' action='/projects/{_escape(project_id)}/delete'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>Type DELETE to confirm</label><input name='confirm' required autocomplete='off'></div><button class='button danger' type='submit'>Delete project</button></form></article></section></section>"
    return _response(body, request)


def _workflow_fix_steps() -> str:
    """Why Auto mode cannot merge without a workflow, and how the customer fixes it."""
    return ("<p class='muted'>Auto mode merges a fix only after a GitHub check passes. This repository has no GitHub Actions workflow, "
            "so there is no check to pass and fixes stay as open pull requests. We could not add a workflow because your GitHub token "
            "is not allowed to write workflow files. Monitoring itself is installed and working.</p>"
            "<ol class='muted'>"
            "<li>On GitHub open <b>Settings</b>, then <b>Developer settings</b>, then <b>Personal access tokens</b>, then <b>Tokens (classic)</b>, "
            "and open the token you gave us.</li>"
            "<li>Tick the <code>workflow</code> scope and save. If you make a brand new token, tick <code>repo</code> and <code>workflow</code>, "
            "then use <b>Update GitHub token</b> on this page first.</li>"
            "<li>Come back to this project page and press <b>Install monitoring</b>. We will add the test workflow in a new pull request "
            "and merge it.</li></ol>")


def _workflow_fix_card(project_id: str, request) -> str:
    return ("<article class='card'><h3>Auto mode needs a test workflow</h3>" + _workflow_fix_steps() +
            f"<form method='post' action='/projects/{_escape(project_id)}/install'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'>"
            "<button class='button primary' type='submit'>Install monitoring</button></form></article>")


def _install_monitoring(project_id: str, user_id: str, project: dict, token: str, ingest_key: str) -> dict:
    """Add monitoring to the customer's repository with no steps for the customer.

    The connection details go into the repository through the install pull request, which is merged
    automatically when GitHub allows it. If the branch name was wrong, the repository's default is used and saved.
    """
    try:
        result = open_monitoring_pr(
            owner=project["repo_owner"], repo=project["repo_name"], base_branch=project["branch"],
            project_id=project_id, token=token, ingest_url=_base_url() + "/ingest",
            ingest_key=ingest_key, auto_merge=True)
    except (GitHubInstallError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    if result.get("base_branch") and result["base_branch"] != project["branch"]:
        portal_db.update_project_branch(project_id, user_id, result["base_branch"])
    ci_state = "added" if result.get("workflow_added") else ("existing" if result.get("had_ci") else "missing")
    if result.get("unchanged"):
        portal_db.set_ci_workflow(project_id, user_id, ci_state)
        portal_db.audit(project_id, "monitoring_reinstall_unchanged", {"ci_workflow": ci_state})
        return dict(result, ok=True)
    portal_db.record_install_pr(project_id, user_id, result["url"], ci_state)
    portal_db.audit(project_id, "monitoring_pr_opened", {"pr_url": result["url"], "merged": result["merged"],
                                                          "patched_file": result["patched_file"], "key_embedded": result["embedded_key"],
                                                          "workflow_added": result.get("workflow_added"), "had_ci": result.get("had_ci")})
    return dict(result, ok=True)


def _install_summary(result: dict, project_id: str) -> str:
    """Plain-language outcome of an install attempt. The customer is never asked to do technical chores."""
    if not result.get("ok"):
        return ("<div class='alert'>Your project is saved, but monitoring could not be added yet: "
                f"{_escape(result.get('error', 'unknown error'))} Nothing was changed in your repository. "
                "Fix the problem, then press <b>Install monitoring</b> on the project page.</div>")
    notes = []
    if result.get("unchanged"):
        if result.get("had_ci"):
            return "<div class='card'><h3>Monitoring setup</h3><p class='muted'>Everything is already installed, and this repository already has a GitHub Actions workflow.</p></div>"
        return ("<div class='card'><h3>Nothing changed yet</h3><p class='muted'>GitHub still does not let this token write workflow files.</p>"
                + _workflow_fix_steps() + "</div>")
    if result.get("patched_file"):
        notes.append(f"One line was added to <code>{_escape(result['patched_file'])}</code> so monitoring starts with your app.")
    elif not result.get("entry_file"):
        notes.append("We could not find your app's main file, so add <code>import incident_agent_monitor</code> as the first import of it.")
    if result.get("workflow_added"):
        notes.append("A GitHub Actions workflow was added that checks your code and runs your tests on every pull request. "
                     "Auto mode merges a fix only after that check passes.")
    if result.get("merged"):
        notes.append("The change was merged automatically. Monitoring starts the next time your app deploys. Nothing else to configure.")
    else:
        notes.append(f"Merge <a href='{_escape(result['url'])}' target='_blank' rel='noopener'>this pull request</a> to turn monitoring on "
                     "(automatic merge was not possible, often because of branch protection). Nothing else to configure.")
    card = "<div class='card'><h3>Monitoring setup</h3><p class='muted'>" + "</p><p class='muted'>".join(notes) + "</p></div>"
    if not result.get("workflow_added") and not result.get("had_ci"):
        card += "<div class='card'><h3>Auto mode needs a test workflow</h3>" + _workflow_fix_steps() + "</div>"
    return card


def _page_install_monitoring(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    if project.get("install_pr_url") and project.get("ci_workflow") != "missing":
        return _redirect(f"/projects/{project_id}")
    back = f"<p><a class='button primary' href='/projects/{_escape(project_id)}'>Back to project</a></p>"
    try:
        token = _decrypt_token(project["github_token_ciphertext"])
        ingest_key = _decrypt_token(project["ingest_key_ciphertext"]) if project.get("ingest_key_ciphertext") else ""
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>{back}", request, "503 Service Unavailable")
    if not ingest_key:
        return _response("<div class='alert'>This project has no stored connection key. Press <b>Rotate key</b> on the project page, then try again.</div>" + back,
                         request, "409 Conflict")
    result = _install_monitoring(project_id, request.session["user_id"], project, token, ingest_key)
    status = "200 OK" if result.get("ok") else "502 Bad Gateway"
    return _response(_install_summary(result, project_id) + back, request, status)






def _page_update_github_token(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    user_id = request.session["user_id"]
    project = portal_db.get_project(project_id, user_id)
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    token = request.form.get("github_token", "").strip()
    if len(token) < 20 or len(token) > 500:
        return _response("<div class='alert'>Enter the complete GitHub token.</div><p><a href='/projects/" + _escape(project_id) + "'>Back to project</a></p>", request, "400 Bad Request")
    try:
        validate_repository_access(owner=project["repo_owner"], repo=project["repo_name"], token=token)
        ciphertext = _encrypt_token(token)
    except GitHubInstallError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/projects/{_escape(project_id)}'>Back to project</a></p>", request, "400 Bad Request")
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "503 Service Unavailable")
    if not portal_db.update_project_github_token(project_id, user_id, ciphertext):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    portal_db.audit(project_id, "github_token_updated", {"repository": f"{project['repo_owner']}/{project['repo_name']}"})
    return _response("<div class='pill green'>GitHub token validated and updated. You can retry the monitoring pull request.</div><p><a class='button primary' href='/projects/" + _escape(project_id) + "'>Back to project</a></p>", request)


def _page_rotate_ingest_key(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    user_id = request.session["user_id"]
    if not portal_db.get_project(project_id, user_id):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if not portal_db.rotate_project_ingest_key(project_id, user_id, key_hash, _encrypt_token(key)):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    portal_db.audit(project_id, "ingest_key_rotated")
    body = f"<section class='card form-card'><h1>New ingest key</h1><p class='muted'>The previous key is invalid now. Copy this value into your app environment; it will not be shown again.</p><div class='alert'><code>{_escape(key)}</code></div><a class='button primary' href='/projects/{_escape(project_id)}'>Back to project</a></section>"
    return _response(body, request)


def _page_delete_project(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    if request.form.get("confirm") != "DELETE":
        return _response("<div class='alert'>Type DELETE exactly to confirm removal.</div>", request, "400 Bad Request")
    deleted = portal_db.delete_project(project_id, request.session["user_id"])
    if not deleted:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    return _redirect("/dashboard")


def _page_incident(request, project_id, incident_id):
    gate = _require_access(request)
    if gate:
        return gate
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    conn = portal_db.get_connection()
    try:
        row = portal_db._execute(conn, "SELECT * FROM incidents WHERE id=? AND project_id=?", (incident_id, project_id)).fetchone()
        incident = dict(row) if row else None
        fixes = portal_db._execute(conn, "SELECT * FROM fixes WHERE incident_id=? ORDER BY created_at DESC", (incident_id,)).fetchall() if incident else []
    finally:
        conn.close()
    if not incident:
        return _response("<h1>Incident not found</h1>", request, "404 Not Found")
    diff = "".join(f"<article class='card'><div class='row'><strong>{_escape(f['file_path'])}</strong><span class='pill'>{_escape(f['ci_result'])}</span></div><pre style='overflow:auto;white-space:pre-wrap;color:#c7d2e4'>{_escape(f['diff'])}</pre></article>" for f in fixes) or "<div class='empty'>No proposed fix has been saved yet.</div>"
    pr_link = (f"<p><a class='button primary' href='{_escape(incident['pr_url'])}' target='_blank' rel='noopener'>Open fix pull request</a></p>"
               if incident.get("pr_url") else "")
    body = f"<section class='section'><p><a href='/projects/{_escape(project_id)}'>← {_escape(project['name'])}</a></p><div class='eyebrow'>Incident</div><h1>{_escape(incident['signature'])}</h1><div class='stats'><span class='pill'>{_escape(incident_board.stage_for(incident, project['mode'])['headline'])}</span><span class='pill'>Occurrences · {_escape(incident['occurrences'])}</span><span class='pill'>CI · {_escape(incident['ci_status'])}</span><span class='pill'>Last seen · {_escape(_fmt_time(incident.get('last_seen')))}</span></div>{pr_link}<article class='card'><h2>What happened</h2><p>{_escape(incident['root_cause']) or 'Diagnosis is pending.'}</p><p class='muted' style='white-space:pre-wrap'>{_escape(incident['report'])}</p></article><h2>Proposed changes</h2>{diff}</section>"
    return _response(body, request)




def _live_gate(request: Request):
    """Gate for the background refresh calls: plain status codes, never a redirect page."""
    plain = [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")]
    if not request.session:
        return Response("Sign in required", "401 Unauthorized", plain)
    if not (_is_admin(request) or portal_db.user_has_active_access(request.session["user_id"])):
        return Response("Plan required", "403 Forbidden", plain)
    return None


def _page_incident_board_live(request, project_id):
    """HTML fragment of the incident board. The browser re-fetches it every few seconds."""
    if request.method != "GET":
        return Response("Method not allowed", "405 Method Not Allowed", [("Content-Type", "text/plain; charset=utf-8")])
    gate = _live_gate(request)
    if gate:
        return gate
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return Response("Project not found", "404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    body = incident_board.render_board(project_id, portal_db.list_incidents(project_id), project["mode"])
    return Response(body, "200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                                     ("X-Content-Type-Options", "nosniff")])


ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ASSET_TYPES = {".webp": "image/webp", ".woff": "font/woff"}
ASSET_FILES = {"daemon-bg.webp", "daemon-crest.webp", "daemon-gloock.woff", "daemon-sans-400.woff", "daemon-sans-700.woff", "daemon-founder-abhay.webp", "daemon-founder-pranav.webp"}


def _page_asset(request):
    name = request.path.rsplit("/", 1)[-1]
    if request.method not in ("GET", "HEAD") or name not in ASSET_FILES:
        return Response(b"Not found", "404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    try:
        with open(os.path.join(ASSET_DIR, name), "rb") as handle:
            data = handle.read()
    except OSError:
        return Response(b"Not found", "404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return Response(data, "200 OK", [("Content-Type", ASSET_TYPES[os.path.splitext(name)[1]]), ("Cache-Control", "public, max-age=604800"),
                                     ("X-Content-Type-Options", "nosniff")])


def _page_live_js(request):
    return Response(incident_board.LIVE_JS, "200 OK",
                    [("Content-Type", "application/javascript; charset=utf-8"),
                     ("Cache-Control", "public, max-age=300"), ("X-Content-Type-Options", "nosniff")])


def _fetch_razorpay_payment(payment_id: str, key_id: str, secret: str):
    if not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
        return None
    basic = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    req = UrlRequest(f"https://api.razorpay.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Basic {basic}", "Accept": "application/json", "User-Agent": "AgentDaemon/1.0"},
        method="GET")
    try:
        with urlopen(req, timeout=12) as result:
            return json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None


def _page_billing(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    user_id = request.session["user_id"]
    access = _access_state(user_id)
    csrf = _escape(_csrf(request))
    gateway = _gateway_ready()
    banner = "<div class='pill green'>Payment received. Your access is active.</div>" if request.query.get("success") == ["1"] else ""
    if access["active"]:
        label = "Paid plan" if access["kind"] == "paid" else "Free trial"
        current = (f"<article class='card'><div class='eyebrow'>Current plan</div><h2>{label}</h2>"
                   f"<p class='muted'>Active until {_escape(_fmt_time(access['until']))} · {_escape(access['remaining'])}</p>"
                   "<a class='button' href='/dashboard'>Go to my projects</a></article>")
    else:
        current = ("<article class='card'><div class='eyebrow'>Current plan</div><h2>No active access</h2>"
                   "<p class='muted'>Monitoring is paused. Your connected projects come back as soon as access starts.</p></article>")
    trial = access["trial"]
    trial_card = ""
    if not (access["active"] and access["kind"] == "paid") and not access["active"]:
        if trial == "pending":
            trial_card = "<article class='card'><div class='eyebrow'>Free trial</div><h3>Waiting for approval</h3><p class='muted'>The admins have your request. Access starts the moment they approve it and you will see it here and on your dashboard.</p></article>"
        elif trial == "approved":
            trial_card = "<article class='card'><div class='eyebrow'>Free trial</div><h3>Trial used</h3><p class='muted'>Your 1-day trial has ended. Pick a plan below to continue.</p></article>"
        else:
            note = "<p class='muted'>Your last request was not approved. You can ask again.</p>" if trial == "rejected" else "<p class='muted'>Try everything for one day. Please provide your details below.</p>"
            user_info = portal_db.get_user_by_id(user_id) or {}
            prefill_name = user_info.get("name") or request.session.get("name") or ""
            prefill_phone = user_info.get("phone") or ""
            prefill_ref = user_info.get("referral_source") or ""
            prefill_org = user_info.get("organization") or ""
            ref_opts = [
                ("YouTube", "YouTube Demo / Video"),
                ("GitHub", "GitHub / Open Source"),
                ("LinkedIn / X", "LinkedIn / X (Twitter)"),
                ("Google Search", "Google Search"),
                ("Friend / Colleague", "Friend / Colleague recommendation"),
                ("College / Hackathon", "College / Hackathon"),
                ("Other", "Other"),
            ]
            opts_html = "".join(f"<option value='{_escape(val)}'{' selected' if prefill_ref == val else ''}>{_escape(lbl)}</option>" for val, lbl in ref_opts)
            trial_card = (
                f"<article class='card'><div class='eyebrow'>Free trial</div><h3>1 day, free</h3>{note}"
                f"<form method='post' action='/billing/trial-request' style='display:flex;flex-direction:column;gap:10px;margin-top:12px'>"
                f"<input type='hidden' name='csrf' value='{csrf}'>"
                f"<div class='field' style='margin-bottom:0'><label style='font-size:12px'>Your Name</label>"
                f"<input name='name' value='{_escape(prefill_name)}' placeholder='Full name' maxlength='100'></div>"
                f"<div class='field' style='margin-bottom:0'><label style='font-size:12px'>Mobile / WhatsApp Number</label>"
                f"<input name='phone' type='tel' value='{_escape(prefill_phone)}' placeholder='+91 98765 43210' maxlength='30'></div>"
                f"<div class='field' style='margin-bottom:0'><label style='font-size:12px'>How did you find out about us?</label>"
                f"<select name='referral_source'><option value=''>Select an option...</option>{opts_html}</select></div>"
                f"<div class='field' style='margin-bottom:0'><label style='font-size:12px'>Company / Project Name <small class='muted'>(optional)</small></label>"
                f"<input name='organization' value='{_escape(prefill_org)}' placeholder='e.g. Acme Inc' maxlength='100'></div>"
                "<button class='button primary' type='submit' style='margin-top:4px'>Request free trial</button></form></article>"
            )
    plan_cards = []
    for key, plan in PLANS.items():
        if gateway:
            action = (f"<form method='post' action='/billing/order'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='plan' value='{key}'><button class='button primary' type='submit'>Pay ₹{plan['rupees']:,}</button></form>"
                      "<p class='muted'>UPI (Paytm, PhonePe, GPay), cards or netbanking. Access starts instantly.</p>")
        else:
            action = (f"<a class='button primary' href='/billing/pay?plan={key}'>Pay ₹{plan['rupees']:,} by UPI</a>"
                      "<p class='muted'>After you pay, wait 1 to 2 hours. We check our Paytm account and switch your access on.</p>")
        period = "month" if key == "monthly" else "year"
        plan_cards.append(f"<article class='card'><div class='eyebrow'>{plan['label']}</div><h2>₹{plan['rupees']:,} <small class='muted'>/ {period}</small></h2>"
                          f"<p class='muted'>{plan['days']} days of access.</p>{action}</article>")
    payments = portal_db.user_manual_payments(user_id)
    history = ""
    if payments:
        rows = [f"<tr><td>{_escape(_fmt_time(p['created_at']))}</td><td>₹{_escape(p['amount'])} {_escape(p['plan'])}</td><td>{_escape(p['transaction_ref'])}</td><td>{_escape(p['status'].title())}</td></tr>" for p in payments]
        history = "<h2>Your UPI submissions</h2>" + _table(["Submitted", "Plan", "Reference", "Status"], rows)
    body = (f"<section class='section'><div class='eyebrow'>Account</div><h1>Plan &amp; billing</h1>{banner}"
            f"<div class='grid'>{current}{trial_card}</div><h2>Plans</h2><div class='grid'>{''.join(plan_cards)}</div>{history}</section>")
    return _response(body, request)


def _page_manual_payment(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request) or _gateway_ready():
        return _redirect("/admin" if _is_admin(request) else "/billing")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        plan = str(request.form.get("plan", ""))
        if plan not in PLANS:
            return _response("<div class='alert'>Choose a valid plan.</div>", request, "400 Bad Request")
        ref = str(request.form.get("transaction_ref", "")).strip()
        name = str(request.form.get("name", "")).strip()
        phone = str(request.form.get("phone", "")).strip()
        referral_source = str(request.form.get("referral_source", "")).strip()
        organization = str(request.form.get("organization", "")).strip()
        try:
            payment = portal_db.create_manual_payment_request(
                request.session["user_id"], PLANS[plan]["rupees"], plan, ref,
                name=name, phone=phone, referral_source=referral_source, organization=organization
            )
        except ValueError as exc:
            return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/billing/pay?plan={plan}'>Back</a></p>", request, "400 Bad Request")
        if payment.get("created_at") and payment["status"] == "pending":
            user_name = name or payment.get("name") or request.session.get("name") or "User"
            user_phone = phone or payment.get("phone") or "Not provided"
            user_ref = referral_source or payment.get("referral_source") or "Not specified"
            user_org = organization or payment.get("organization") or "Not specified"
            email_body = (
                f"UPI payment to confirm: INR {PLANS[plan]['rupees']} from {request.session['email']}.\n\n"
                f"Customer Details:\n"
                f"  - Name: {user_name}\n"
                f"  - Email: {request.session['email']}\n"
                f"  - Mobile / WhatsApp: {user_phone}\n"
                f"  - How they found us: {user_ref}\n"
                f"  - Company / Project: {user_org}\n\n"
                f"Payment Details:\n"
                f"  - Plan: {plan.title()} (INR {PLANS[plan]['rupees']})\n"
                f"  - UPI Reference (UTR): {ref}\n"
                f"  - Submitted: {_fmt_time(payment.get('created_at'))}\n\n"
                f"Open your Paytm app and look for a payment of INR {PLANS[plan]['rupees']} with this reference. "
                f"If you see it, confirm it here: {_base_url()}/admin"
            )
            notifications.notify_admins(
                f"UPI payment to confirm: INR {PLANS[plan]['rupees']} from {request.session['email']}",
                email_body, "payment_submitted")
            notifications.notify_customer(
                request.session["email"], "We received your payment details",
                f"Thanks {user_name}! You told us you paid INR {PLANS[plan]['rupees']} (reference {ref}).\n"
                "Please wait 1 to 2 hours. We check our Paytm account and switch your access on as soon as we see the payment. "
                "You will get another email when it is active.", "payment_received")
        return _response("<section class='card form-card'><h1>Payment submitted</h1>"
                         "<p>Thanks! Please wait 1 to 2 hours. We check our Paytm account for your payment and your access starts as soon as we see it. "
                         "You will see the status under Plan &amp; billing and get an email.</p>"
                         "<p class='muted'>Do not pay again unless an admin asks you to.</p>"
                         "<a class='button primary' href='/billing'>Back to plan &amp; billing</a></section>", request)
    plan = request.query.get("plan", ["monthly"])[0]
    if plan not in PLANS:
        plan = "monthly"
    rupees = PLANS[plan]["rupees"]
    uri = _upi_uri(plan)
    qr = _qr_data_uri(uri)
    vpa = os.getenv("UPI_ID", "7975291636@ptsbi").strip()
    qr_html = f"<img src='{_escape(qr)}' alt='UPI QR code for ₹{rupees}' width='260' height='260'>" if qr else "<p style='color:#222'>QR code unavailable. Use the button below.</p>"
    plain_uri = "upi://pay?" + "&".join(f"{key}={quote(value, safe='@')}" for key, value in
                                       {"pa": vpa, "pn": os.getenv("UPI_PAYEE_NAME", "Pranav V Rao").strip(), "cu": "INR"}.items())
    plain_qr = _qr_data_uri(plain_uri)
    plain_html = f"<img src='{_escape(plain_qr)}' alt='UPI QR code without an amount' width='220' height='220'>" if plain_qr else ""

    user_info = portal_db.get_user_by_id(request.session["user_id"]) or {}
    prefill_name = user_info.get("name") or request.session.get("name") or ""
    prefill_phone = user_info.get("phone") or ""
    prefill_ref = user_info.get("referral_source") or ""
    prefill_org = user_info.get("organization") or ""

    ref_opts = [
        ("YouTube", "YouTube Demo / Video"),
        ("GitHub", "GitHub / Open Source"),
        ("LinkedIn / X", "LinkedIn / X (Twitter)"),
        ("Google Search", "Google Search"),
        ("Friend / Colleague", "Friend / Colleague recommendation"),
        ("College / Hackathon", "College / Hackathon"),
        ("Other", "Other"),
    ]
    opts_html = "".join(f"<option value='{_escape(val)}'{' selected' if prefill_ref == val else ''}>{_escape(lbl)}</option>" for val, lbl in ref_opts)

    body = (f"<section class='card form-card'><div class='eyebrow'>Pay by UPI</div><h1>Pay ₹{rupees:,}</h1>"
            f"<p class='muted'>{PLANS[plan]['label']} plan · {PLANS[plan]['days']} days. On a phone tap the button to open your UPI app (Paytm, PhonePe, GPay). On a computer scan the QR code with your phone.</p>"
            f"<div class='qr'><a href='{_escape(uri)}' aria-label='Open UPI app'>{qr_html}</a><p>{_escape(vpa)}</p>"
            f"<a class='button primary' style='margin-top:12px' href='{_escape(uri)}'>Open UPI app and pay ₹{rupees:,}</a></div>"
            f"<details><summary>Your app will not accept the amount? Scan this QR and type ₹{rupees:,} yourself.</summary><div class='qr'>{plain_html}<p>{_escape(vpa)}</p></div></details>"
            f"<div class='alert'>Check that your UPI app shows exactly ₹{rupees:,}.00 before you pay. After you pay, enter the UPI reference number (UTR) and your contact details below and press the button. Then please wait 1 to 2 hours: we check our Paytm account for your payment and switch your access on. You will get an email.</div>"
            f"<form method='post' action='/billing/pay'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='plan' value='{plan}'>"
            f"<div class='field'><label>Your Name</label><input name='name' value='{_escape(prefill_name)}' placeholder='Full name' maxlength='100'></div>"
            f"<div class='field'><label>Mobile / WhatsApp Number</label><input name='phone' type='tel' value='{_escape(prefill_phone)}' placeholder='+91 98765 43210' maxlength='30'></div>"
            f"<div class='field'><label>How did you find out about us?</label><select name='referral_source'><option value=''>Select an option...</option>{opts_html}</select></div>"
            f"<div class='field'><label>Company / Project Name <small class='muted'>(optional)</small></label><input name='organization' value='{_escape(prefill_org)}' placeholder='e.g. Acme Inc' maxlength='100'></div>"
            "<div class='field'><label>UPI reference number (UTR)</label><input name='transaction_ref' maxlength='40' required autocomplete='off' placeholder='12-digit number from your payment receipt'>"
            "<small>Only submit after your UPI app shows the payment as successful. Fake references are rejected when an admin checks.</small></div>"
            "<button class='button primary' type='submit'>I have paid ₹" + f"{rupees:,}" + "</button></form></section>")
    return _response(body, request)


def _page_create_order(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    plan = str(request.form.get("plan", ""))
    if plan not in PLANS:
        return _response("<div class='alert'>Choose a valid subscription plan.</div>", request, "400 Bad Request")
    try:
        key_id, secret, amount = _razorpay_settings(plan)
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/billing/pay?plan={plan}'>Pay by UPI QR instead</a></p>", request, "503 Service Unavailable")
    user_id = request.session["user_id"]
    cust_name = str(request.form.get("name", "")).strip()
    cust_phone = str(request.form.get("phone", "")).strip()
    cust_ref = str(request.form.get("referral_source", "")).strip()
    cust_org = str(request.form.get("organization", "")).strip()
    if any([cust_name, cust_phone, cust_ref, cust_org]):
        portal_db.update_user_details(user_id, name=cust_name, phone=cust_phone, referral_source=cust_ref, organization=cust_org)
    payload = json.dumps({"amount": amount, "currency": "INR",
                          "receipt": "ad-" + secrets.token_hex(8),
                          "notes": {"user_id": user_id, "plan": plan}}).encode("utf-8")
    basic = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    api_request = UrlRequest("https://api.razorpay.com/v1/orders", data=payload,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json", "User-Agent": "AgentDaemon/1.0"}, method="POST")
    try:
        with urlopen(api_request, timeout=12) as result:
            order = json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return _response("<div class='alert'>The payment provider could not start the payment. Nothing was charged. Try again in a minute.</div>", request, "502 Bad Gateway")
    order_id = str(order.get("id", ""))
    if not re.fullmatch(r"order_[A-Za-z0-9]+", order_id) or order.get("amount") != amount:
        return _response("<div class='alert'>The payment provider returned an invalid order. Nothing was charged.</div>", request, "502 Bad Gateway")
    portal_db.create_payment_order(user_id, order_id, amount, plan)
    nonce = secrets.token_urlsafe(18)
    rupees = amount // 100
    test_banner = "<div class='alert'>Test mode: no real money moves. Use Razorpay's test UPI id <code>success@razorpay</code>.</div>" if key_id.startswith("rzp_test_") else ""
    script = r"""const options={key:__KEY__,amount:__AMOUNT__,currency:'INR',name:'Agent Daemon',description:__DESC__,order_id:__ORDER__,prefill:{email:__EMAIL__},theme:{color:'#75a7ff'},
handler:async function(r){const out=document.getElementById('result');out.textContent='Confirming your payment...';try{const response=await fetch('/billing/verify',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({csrf:__CSRF__,order_id:r.razorpay_order_id,payment_id:r.razorpay_payment_id,signature:r.razorpay_signature})});const data=await response.json();if(response.ok){location.href='/billing?success=1';}else{out.textContent=data.error||'Payment verification failed.';}}catch(e){out.textContent='Could not confirm yet. If money was taken, your access switches on automatically within a minute.';}},
modal:{ondismiss:function(){document.getElementById('result').textContent='Checkout closed. You have not been charged.';}}};
const rzp=new Razorpay(options);rzp.on('payment.failed',function(r){document.getElementById('result').textContent=(r.error&&r.error.description)||'Payment failed. You can try again.';});
document.getElementById('pay').addEventListener('click',function(){rzp.open();});rzp.open();"""
    def js(value):
        return json.dumps(value).replace("</", "<\\/")
    for token, value in (("__KEY__", key_id), ("__AMOUNT__", amount), ("__DESC__", f"Agent Daemon {plan}"), ("__ORDER__", order_id),
                         ("__EMAIL__", request.session["email"]), ("__CSRF__", _csrf(request))):
        script = script.replace(token, js(value))
    body = (f"<section class='card form-card'><div class='eyebrow'>Secure payment</div><h1>Pay ₹{rupees:,}</h1>"
            f"<p class='muted'>{PLANS[plan]['label']} plan · {PLANS[plan]['days']} days. The amount is fixed by the server, so you can only pay ₹{rupees:,}. "
            "Pay with any UPI app (Paytm, PhonePe, GPay), card or netbanking. Access starts the moment the payment succeeds.</p>"
            f"{test_banner}<button class='button primary' id='pay' type='button'>Pay ₹{rupees:,}</button><p id='result' class='muted'></p></section>"
            f"<script src='https://checkout.razorpay.com/v1/checkout.js'></script><script nonce='{nonce}'>{script}</script>")
    headers = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"),
        ("Content-Security-Policy", f"default-src 'self'; script-src 'self' https://checkout.razorpay.com 'nonce-{nonce}'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.razorpay.com; frame-src https://checkout.razorpay.com https://api.razorpay.com; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
    return Response(_layout("Checkout", body, request), "200 OK", headers)


def _page_verify_payment(request):
    if request.method != "POST" or not request.session:
        return Response(json.dumps({"error": "Sign in is required."}), "401 Unauthorized", [("Content-Type", "application/json")])
    if not _csrf_valid(request):
        return Response(json.dumps({"error": "Request expired; reload checkout."}), "403 Forbidden", [("Content-Type", "application/json")])
    order_id = str(request.form.get("order_id", ""))
    payment_id = str(request.form.get("payment_id", ""))
    signature = str(request.form.get("signature", ""))
    try:
        key_id, secret, _ = _razorpay_settings()
    except RuntimeError:
        return Response(json.dumps({"error": "Test checkout is unavailable."}), "503 Service Unavailable", [("Content-Type", "application/json")])
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not re.fullmatch(r"order_[A-Za-z0-9]+", order_id) or not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id) or not hmac.compare_digest(signature, expected):
        return Response(json.dumps({"error": "Payment signature could not be verified."}), "400 Bad Request", [("Content-Type", "application/json")])
    conn = portal_db.get_connection()
    try:
        order = portal_db._execute(conn, "SELECT amount FROM payment_orders WHERE razorpay_order_id=? AND user_id=?",
                                   (order_id,request.session["user_id"])).fetchone()
    finally:
        conn.close()
    if not order:
        return Response(json.dumps({"error": "The order is invalid for this account."}), "404 Not Found", [("Content-Type", "application/json")])
    payment = _fetch_razorpay_payment(payment_id, key_id, secret)
    if not payment or payment.get("status") != "captured" or payment.get("order_id") != order_id or int(payment.get("amount", 0)) != int(order["amount"]) or payment.get("currency") != "INR":
        return Response(json.dumps({"error": "Payment is not captured yet. Wait for confirmation and retry."}), "409 Conflict", [("Content-Type", "application/json")])
    activated = portal_db.complete_payment_order(order_id, payment_id, int(payment["amount"]))
    if not activated:
        return Response(json.dumps({"error": "This payment was already processed or the order is invalid."}), "409 Conflict", [("Content-Type", "application/json")])
    _after_payment(order_id, payment_id)
    return Response(json.dumps({"status": "active"}), "200 OK", [("Content-Type", "application/json"), ("Cache-Control", "no-store")])


def _json_response(payload: dict, status="200 OK"):
    return Response(json.dumps(payload, separators=(",", ":")), status,
                    [("Content-Type", "application/json; charset=utf-8"),
                     ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])


def _incident_signature(message: str, traceback: str, payload: dict) -> str:
    frames = re.findall(r'File "([^"\n]+)", line (\d+)', traceback)
    app_frames = [(path, line) for path, line in frames if "site-packages" not in path.replace("\\", "/")]
    error_type = str(payload.get("exception_type", "")).strip() or message.split(":", 1)[0].strip() or "Error"
    if app_frames:
        path, line = app_frames[-1]
        return f"{error_type}:{PurePosixPath(path.replace('\\', '/')).name}:{line}"[:250]
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    return f"{error_type}:unknown:{digest}"


def _authorized_ingest_project(request: Request):
    raw_key = request.environ.get("HTTP_X_INGEST_KEY", "").strip()
    if len(raw_key) < 24 or len(raw_key) > 256:
        return None
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return portal_db.get_project_by_ingest_hash(key_hash)


def _page_ingest(request):
    if request.method != "POST" or not request.raw_body:
        return _json_response({"error": "POST a JSON error event."}, "400 Bad Request")
    if request.environ.get("CONTENT_TYPE", "").split(";", 1)[0].lower() != "application/json":
        return _json_response({"error": "Content-Type must be application/json."}, "415 Unsupported Media Type")
    project = _authorized_ingest_project(request)
    if not project:
        return _json_response({"error": "Invalid ingest key."}, "401 Unauthorized")
    if project["paused"] or not portal_db.user_has_active_access(project["user_id"]):
        return _json_response({"accepted": False, "reason": "access_not_active"}, "202 Accepted")
    if not portal_db.allow_ingest(project["id"]):
        return _json_response({"error": "Ingest rate limit exceeded."}, "429 Too Many Requests")
    data = request.form
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return _json_response({"error": "message is required."}, "400 Bad Request")
    message = message.strip()[:10000]
    traceback = data.get("traceback", "")
    if not isinstance(traceback, str):
        traceback = ""
    traceback = traceback[:30000]
    level = str(data.get("level", "ERROR")).upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return _json_response({"error": "level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."}, "400 Bad Request")
    timestamp = str(data.get("timestamp") or data.get("ts") or "")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None:
            parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
        timestamp = parsed_timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        timestamp = _now().isoformat(timespec="seconds")
    signature = _incident_signature(message, traceback, data)
    incident_id, inserted = portal_db.ingest_event(project["id"], timestamp=timestamp,
        level=level, message=message, traceback=traceback, signature=signature)
    portal_db.set_project_connected(project["id"])
    return _json_response({"accepted": inserted, "duplicate": not inserted,
                           "incident_id": incident_id}, "202 Accepted" if inserted else "200 OK")


def _page_heartbeat(request):
    if request.method != "POST":
        return _json_response({"error": "POST required."}, "405 Method Not Allowed")
    project = _authorized_ingest_project(request)
    if not project:
        return _json_response({"error": "Invalid ingest key."}, "401 Unauthorized")
    if project["paused"] or not portal_db.user_has_active_access(project["user_id"]):
        return _json_response({"status": "access_not_active"}, "403 Forbidden")
    if not portal_db.allow_ingest(project["id"], maximum=60):
        return _json_response({"error": "Heartbeat rate limit exceeded."}, "429 Too Many Requests")
    portal_db.set_project_connected(project["id"])
    return _json_response({"status": "connected"})


def _razorpay_webhook(request):
    if request.method != "POST":
        return Response(b"method not allowed", "405 Method Not Allowed", [("Content-Type", "text/plain")])
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    provided = request.environ.get("HTTP_X_RAZORPAY_SIGNATURE", "")
    if not secret or not provided:
        return Response(b"not configured", "503 Service Unavailable", [("Content-Type", "text/plain")])
    expected = hmac.new(secret.encode(), request.raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        return Response(b"invalid signature", "401 Unauthorized", [("Content-Type", "text/plain")])
    try:
        event = json.loads(request.raw_body.decode("utf-8"))
        payment = event["payload"]["payment"]["entity"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return Response(b"invalid event", "400 Bad Request", [("Content-Type", "text/plain")])
    if event.get("event") == "payment.captured" and payment.get("status") == "captured" and payment.get("currency") == "INR":
        order_id, payment_id = str(payment.get("order_id", "")), str(payment.get("id", ""))
        if re.fullmatch(r"order_[A-Za-z0-9]+", order_id) and re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
            try:
                amount = int(payment.get("amount", 0))
            except (TypeError, ValueError):
                amount = 0
            # Safe to repeat: complete_payment_order applies each captured payment only once.
            if portal_db.complete_payment_order(order_id, payment_id, amount):
                _after_payment(order_id, payment_id)
    return Response(b"ok", "200 OK", [("Content-Type", "text/plain"), ("Cache-Control", "no-store")])


def _page_logout(request):
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not request.session or not _csrf_valid(request):
        return _response("<div class='alert'>Sign-in expired. Please sign in again.</div>", request, "403 Forbidden")
    portal_db.delete_session(request.session["id"])
    return _redirect("/", [_cookie(SESSION_COOKIE, "", max_age=0), _cookie(CSRF_COOKIE, "", max_age=0, http_only=False)])


def _dispatch(request: Request) -> Response:
    if request.path == "/assets/chat.js":
        return _page_chat_js(request)
    if request.path == "/assets/home.js":
        return Response(homepage.HOME_JS, "200 OK",
                        [("Content-Type", "application/javascript; charset=utf-8"),
                         ("Cache-Control", "public, max-age=300"), ("X-Content-Type-Options", "nosniff")])
    if request.path == "/api/visitor/track":
        return _api_visitor_track(request)
    if request.path == "/api/chat/messages":
        return _api_chat_messages(request)
    if request.path == "/api/chat/send":
        return _api_chat_send(request)
    if request.path == "/api/chat/save-contact":
        return _api_chat_save_contact(request)
    if request.path == "/api/admin/chat/reply":
        return _api_admin_chat_reply(request)
    if request.path == "/api/admin/chat/messages":
        return _api_admin_chat_messages(request)
    if request.method == "GET" and request.path == "/":
        return _page_home(request)
    if request.method == "GET" and request.path in ("/about", "/about-us"):
        return _page_about(request)
    if request.method == "GET" and request.path in ("/help", "/docs", "/help-center", "/troubleshooting"):
        return _page_help(request)
    if request.method == "GET" and request.path == "/features":
        return _response(footer_pages.features_page_html(), request, status="200 OK")
    if request.method == "GET" and request.path == "/pricing":
        return _response(footer_pages.pricing_page_html(signed_in=bool(request.session)), request, status="200 OK")
    if request.method == "GET" and request.path == "/changelog":
        return _response(footer_pages.changelog_page_html(), request, status="200 OK")
    if request.method == "GET" and request.path in ("/faq", "/questions"):
        return _response(footer_pages.faq_page_html(), request, status="200 OK")
    if request.method == "GET" and request.path in ("/privacy", "/privacy-policy"):
        return _response(footer_pages.privacy_policy_page_html(), request, status="200 OK")
    if request.method == "GET" and request.path in ("/terms", "/terms-of-service", "/tos"):
        return _response(footer_pages.terms_of_service_page_html(), request, status="200 OK")
    if request.path in ("/contact", "/support"):
        return _page_contact(request)
    if request.path in ("/onboarding/name", "/profile/name"):
        return _page_onboarding_name(request)
    if request.path == "/auth/google":
        if request.method != "GET":
            return _response("Method not allowed", request, "405 Method Not Allowed")
        return _google_begin(request)
    if request.path == GOOGLE_CALLBACK_PATH:
        return _google_callback(request)
    if request.path in ("/signup", "/login") and request.method in ("GET", "POST"):
        return _page_signup(request) if request.path == "/signup" else _page_login(request)
    if request.path == "/logout":
        return _page_logout(request)
    if request.path == "/admin":
        return _page_admin(request)
    if request.path == "/dashboard":
        return _page_dashboard(request)
    if request.path == "/billing":
        return _page_billing(request)
    if request.path == "/billing/trial-request":
        return _page_trial_request(request)
    if request.path == "/billing/pay":
        return _page_manual_payment(request)
    if request.path == "/billing/order":
        return _page_create_order(request)
    if request.path == "/billing/verify":
        return _page_verify_payment(request)
    if request.path == "/webhooks/razorpay":
        return _razorpay_webhook(request)
    if request.path == "/ingest":
        return _page_ingest(request)
    if request.path == "/heartbeat":
        return _page_heartbeat(request)
    if request.path == "/projects/new":
        return _page_new_project(request)
    if request.path == "/assets/live.js":
        return _page_live_js(request)
    if re.fullmatch(r"/assets/daemon-[a-z0-9-]+\.(?:webp|woff)", request.path):
        return _page_asset(request)
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/incidents/live", request.path)
    if match:
        return _page_incident_board_live(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/github-token", request.path)
    if match:
        return _page_update_github_token(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/rotate-key", request.path)
    if match:
        return _page_rotate_ingest_key(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/install", request.path)
    if match:
        return _page_install_monitoring(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/delete", request.path)
    if match:
        return _page_delete_project(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})", request.path)
    if match:
        return _page_project(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/incidents/([0-9a-f-]{36})", request.path)
    if match:
        return _page_incident(request, *match.groups())
    if request.path == "/health":
        return Response(b"ok", "200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return _response("<h1>Page not found</h1><p class='muted'>That route does not exist.</p>", request, "404 Not Found")


def application(environ, start_response):
    try:
        request = Request(environ)
        if request.method == "POST" and request.path not in ("/login", "/signup", "/contact", "/support", "/webhooks/razorpay", "/ingest", "/heartbeat", "/api/visitor/track", "/api/chat/send", "/api/chat/save-contact") and not request.session:
            response = _redirect("/login")
        else:
            response = _dispatch(request)
    except ValueError as exc:
        response = Response(_escape(exc), "400 Bad Request", [("Content-Type", "text/plain; charset=utf-8")])
    except RuntimeError as exc:
        response = Response(_escape(exc), "503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")])
    if os.getenv("APP_ENV", "development").lower() == "production":
        response.headers.extend([
            ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
            ("X-Frame-Options", "DENY"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ])
    start_response(response.status, response.headers)
    return [response.body]


def main():
    portal_db.init_db()
    # Validate startup configuration before accepting traffic.
    _secret()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    with make_server(host, port, application, server_class=ThreadingWSGIServer) as server:
        print(f"{APP_NAME} web app listening on http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()

