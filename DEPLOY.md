# Deploying Agent Daemon v3, step by step (no experience needed)

There are **three machines** in this story. Keep them apart in your head:

| Machine | What it does | Where |
| --- | --- | --- |
| **Render** (you already have it) | the website, the database, the worker that runs jobs | render.com |
| **Sandbox server** (new, about ₹400–800/month) | runs customers' code safely inside Docker containers | any small Linux VPS |
| **GitHub** | your code, and your customers' code | github.com |

Render cannot run Docker, which is why the sandbox lives on its own little server. Without it, push checks and fixes wait in the
queue and the dashboard honestly says "Waiting for the test sandbox". Everything else (site, billing, tickets, chat) works without it.

Time needed: about 1.5 hours the first time.

---

## Step 1. Put the new code on GitHub (10 minutes)

1. Unzip the release zip. You get a folder `incident-agent-main`.
2. In your existing local clone of `Samuel777822/incident-agent`:
   ```
   git checkout main && git pull
   git checkout -b monitoring-v2
   ```
3. Delete everything in the clone **except the hidden `.git` folder**, then copy all files from `incident-agent-main` into it
   (on Windows, Explorer's "show hidden items" helps; do not copy any `.env`).
4. Check and commit:
   ```
   python -m pip install -r requirements-test.txt
   python -m pytest -q            # expect: 378 passed (a few may be skipped if Node, Java or Playwright is not installed)
   python scripts/simulate_monitoring.py   # optional: a 15-second local run of monitors -> heartbeats -> error -> fix PR (prints PASS)
   git add -A
   git commit -m "Monitoring v2: every-language monitors, 30s check-ins, public-repo gate, first scan, retired-model fixes, diagrams"
   git push -u origin monitoring-v2
   ```
5. On GitHub open a pull request into `main`, wait for the green "tests" check, merge. Render redeploys by itself.
   The database upgrades itself on start (new tables and columns are added automatically; no data is lost).

## Step 2. Render environment (15 minutes)

Open dashboard.render.com → your portal service → **Environment**. If you use the blueprint (`render.yaml`), the shared group is
`incident-agent-core`; change variables there so the web service and the worker both get them.

**Change / add:**

| Name | Value | Why |
| --- | --- | --- |
| `ADMIN_EMAILS` | `pranavvrao@agentdaemon.xyz,abhaysamuel@agentdaemon.xyz` | the only two admins. This **removes the old admins** (or delete the variable: these two are the default) |
| `SUPPORT_EMAIL` | `contact@agentdaemon.xyz` | shown in the footer, contact page, chatbot |
| `ADMIN_PASSWORD_PRANAVVRAO_AGENTDAEMON_XYZ` | a long password you choose | password sign-in for Pranav (skip if you sign in with Google on that address) |
| `ADMIN_PASSWORD_ABHAYSAMUEL_AGENTDAEMON_XYZ` | a long password you choose | password sign-in for Abhay |
| `COOKIE_DOMAIN` | `agentdaemon.xyz` | shares secure login/OAuth cookies between apex and `www` hosts |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | values from Google Cloud OAuth client | Google sign-in credentials |
| `GOOGLE_REDIRECT_URI` | `https://agentdaemon.xyz/auth/google/callback` | must exactly match an Authorized redirect URI in Google Cloud Console |
| `PORTAL_BASE_URL` | `https://incident-agent-portal.onrender.com` (or your domain, see step 5) | **must be right**: GitHub sends push webhooks here, and every monitor installed into customer apps sends its 30-second check-ins and error reports here |
| `PUSH_CHECKS_ENABLED` | `1` | push guard on |
| `PUSH_POLL_SECONDS` | `180` | how often the worker looks for pushes the webhook missed |
| `FIXENGINE_SANDBOX_MODE` | `remote` | the sandbox is the separate server |
| `FIXENGINE_SANDBOX_URL` | `https://sandbox.agentdaemon.xyz` (after step 3) | |
| `FIXENGINE_SANDBOX_SECRET` | a long random string (same one as on the sandbox server) | signs every request to the sandbox |
| `FIXENGINE_ENABLED` | `1` once step 3 works (keep `0` until then) | turns on automatic fixing |
| `OPENROUTER_API_KEY` and/or `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | your keys | the AI modes |
| `FIXENGINE_BUDGET_INR` / `FIXENGINE_CREDITS_INR` | e.g. `1600` / `2000` | global spend cap (80% of what you deposited) |

**New in this release (all optional, defaults are fine):**

| Name | Default | Why |
| --- | --- | --- |
| `MONITOR_OFFLINE_SECONDS` | `120` | a server monitor silent this long shows **Monitor offline** (monitors check in every 30 s) |
| `MONITOR_FIRST_CHECKIN_GRACE_SECONDS` | `1800` | installed but never checked in after this long shows **Never checked in** and emails the owner once |
| `VISIBILITY_CHECK_SECONDS` | `600` | how often the worker re-checks that connected repositories are still private |
| `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`, `CHATBOT_MODEL`, `FIXENGINE_MODEL_GROQ/HAIKU/SONNET/OPUS` | see `.env.example` | change an AI model id without a code change |
| `MODEL_REGISTRY_JSON` | empty (uses `model_registry.json`) | the list of retired AI models and their replacements |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | empty | only used to double-check a replacement model name; OpenRouter's public model list is used otherwise |

**The app now refuses to start** (with one clear message in the Render log) if `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY` or, for
the web service, `SESSION_SECRET` is missing or invalid. Missing `PORTAL_BASE_URL`, `BREVO_API_KEY` or AI keys only log a warning.

**Delete:** the old `ADMIN_PASSWORD_<OLD_EMAIL>` variables and the old single `ADMIN_EMAIL` / `ADMIN_PASSWORD` if they point at the
old addresses.

Make a random secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

**One service or two?** `render.yaml` describes a web service plus a separate worker (paid "starter" plans). If you run only one free
web service, set `PORTAL_RUN_WORKER=1` on it so the worker runs inside it, and keep UptimeRobot pinging `/health` every 5 minutes
(a sleeping free service misses webhooks; the poller then catches the push a few minutes later).

## Step 3. The sandbox server (45 minutes)

### 3a. Rent a small server
Any of these works: **Hetzner CX22** (cheapest), **DigitalOcean / Vultr** Bangalore or Mumbai, **AWS Lightsail** Mumbai.
Pick **Ubuntu 24.04**, **2 GB RAM** (4 GB if many Java projects), and add your SSH key. Note its public IP, e.g. `203.0.113.10`.
This machine must hold **nothing of value**: customer code runs on it (inside containers, but still).

### 3b. Point a name at it
At your domain registrar (where `agentdaemon.xyz` lives) add a DNS record: type **A**, name **sandbox**, value **the server IP**.

### 3c. Install Docker and the service
```
ssh root@203.0.113.10
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
apt -y install python3-pip git caddy ufw
adduser --disabled-password --gecos "" sandbox && usermod -aG docker sandbox
su - sandbox
git clone https://github.com/Samuel777822/incident-agent.git app && cd app
pip install --break-system-packages httpx cryptography
docker build -f sandbox/Dockerfile.python -t fixengine-sandbox-python:1 sandbox
docker build -f sandbox/Dockerfile.node   -t fixengine-sandbox-node:1   sandbox
docker build -f sandbox/Dockerfile.java   -t fixengine-sandbox-java:1   sandbox
exit
```
(If the repository is private, use `git clone https://<a read-only token>@github.com/...` or a deploy key.)

### 3d. Keep it running (systemd)
As root create `/etc/systemd/system/fx-sandbox.service`:
```
[Unit]
Description=Agent Daemon sandbox
After=docker.service
[Service]
User=sandbox
WorkingDirectory=/home/sandbox/app
Environment=FIXENGINE_SANDBOX_SECRET=PASTE_THE_SAME_SECRET_AS_IN_RENDER
Environment=PORT=8099
ExecStart=/usr/bin/python3 sandbox_service.py
Restart=always
[Install]
WantedBy=multi-user.target
```
Then: `systemctl daemon-reload && systemctl enable --now fx-sandbox && systemctl status fx-sandbox`.

### 3e. HTTPS in front of it (Caddy gets the certificate by itself)
Put this in `/etc/caddy/Caddyfile`:
```
sandbox.agentdaemon.xyz {
    reverse_proxy 127.0.0.1:8099
}
```
`systemctl reload caddy`. Firewall: `ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable` (port 8099 stays closed).

### 3f. Test it
`curl https://sandbox.agentdaemon.xyz/health` → `{"ok": true}`. Then on the server, as `sandbox`:
`cd app && python3 bench/sandbox_abuse_check.py` (proves bad code stays inside the container).
Now set `FIXENGINE_SANDBOX_URL` in Render (step 2) and, when you are ready, `FIXENGINE_ENABLED=1`.

**Updating later:** `su - sandbox; cd app; git pull; docker build ...` (only when `sandbox/` changed), then `sudo systemctl restart fx-sandbox`.

## Step 4. Email for the new addresses (20 minutes)

1. **Receive mail** at `contact@`, `pranavvrao@`, `abhaysamuel@agentdaemon.xyz`: the easiest free way is **Cloudflare Email Routing**
   (forward each address to your Gmail) or **Zoho Mail** free plan. Google Workspace also works and lets the admins use "Sign in with Google".
2. **Send mail**: in Brevo → *Senders, Domains & Dedicated IPs* → *Domains* → add `agentdaemon.xyz` and add the DNS records Brevo shows
   (DKIM, DMARC). Then set `EMAIL_FROM=contact@agentdaemon.xyz` in Render.
3. Sign in at `/login` as an admin, open `/admin`, press **Send test email to both admins**, check *Email status* says `accepted`, and
   look in both inboxes (and spam).

## Step 5. Optional: your own domain for the site
Render → service → *Settings* → *Custom Domains* → add `app.agentdaemon.xyz`, create the CNAME it shows, wait for the certificate, then
set `PORTAL_BASE_URL=https://app.agentdaemon.xyz` and Google OAuth's redirect URI to `https://app.agentdaemon.xyz/auth/google/callback`.
Existing projects: press **Reconnect webhook** on each project page so GitHub uses the new address.

## How a project gets connected now (read once)

1. The customer pastes the repository and a **classic** token (`repo` + `workflow` scopes; `repo` also lets us read whether
   the repository is private). Nothing else is asked.
2. **Public-repo gate.** We ask GitHub whether the repository is private.
   * **Public:** nothing is installed, no webhook, no scan. The customer sees a simple screen ("your repository is public…") with
     numbered steps for computer and phone, a warning if the site is on GitHub Pages, and the button
     **I've made it private, install now**, which asks GitHub again. The project shows **Waiting for private repo** on the
     dashboard until then.
   * **Private:** we continue immediately.
3. **Monitor install, every language.** We read the repository's file list and add the right monitor to each part in one pull
   request for human review:
   * Python (Flask, FastAPI, Django, plain): `incident_agent_monitor.py` + one import line in the entry file.
   * Java main entry points: a dependency-free uncaught-exception handler and a 30-second heartbeat monitor.
   * Node.js (Express, Fastify, NestJS, plain, compiled TypeScript): `incident-agent-monitor.cjs`, loaded by `node -r` in the
     start script (or one `require` line). Next.js: `instrumentation.js` (server) and `instrumentation-client.js` (browser).
   * Web pages (plain HTML/JS, React with Vite or Create React App, Flask templates): `incident-agent-monitor.js` as the first
     `<script>` of each page.
   * Mixed repos get one monitor per part. Each monitor checks in every **30 seconds** and reports crashes, unhandled promise
     rejections, console errors and failed API calls (for example "model not found" from an AI provider) with the full message.
   * Only a **project-scoped key** goes into the repository: it can only send check-ins and error reports for that one project,
     is stored hashed, and **Replace key** on the project page revokes it and commits the new one for the customer.
4. **First scan right away.** The latest commit is checked at once (no push needed), including a scan for retired AI model ids.
   Anything it finds goes through the same fix pipeline. After that, every push is checked as before.
5. **Never silent.** The project page shows "Last check-in at …", or **Never checked in** / **Monitor offline** with steps to
   fix it, and the owner gets one email. If a repository later becomes public, Agent Daemon's repository writes pause, the
   old key is revoked, and the owner is emailed the steps again.

## Step 6. First real test (15 minutes)

1. Make a throw-away **private** GitHub repo with a tiny app and a test, e.g. `app.py` + `test_app.py`, plus a `frontend/` with a
   `package.json` to see a mixed repo.
2. Create a classic token with `repo` and `workflow`. Connect the repo on `/projects/new` and choose **Pull Request** mode.
3. The page lists every part it found ("Flask app ✅", "Front-end (Vite) ✅") and says "Push guard is on". On GitHub → repo →
   *Settings* → *Webhooks* you see the webhook with a green tick (ping), and a pull request "Add Agent Daemon error monitoring" waiting for review.
4. Within a minute the project page shows the first check (your latest commit) and GitHub shows a ✓ next to the commit.
   Deploy the app; within 30 seconds the project page says **Live** and "Last check-in at …".
5. Optional, the incident from November: put `model: "gpt-3.5-turbo"` in a chatbot call and push. The scan opens an incident,
   and a pull request "fix: switch retired AI model gpt-3.5-turbo to …" appears without using any AI tries.
6. Optional, the gate: connect a **public** repo and check that nothing is committed and the "make it private" screen appears.
7. Break a test and push. Watch the dashboard: *Push check: broken* → *Reproducing* → *Normal mode is writing a fix* → *Testing the fix*
   → *Pushing the fix to GitHub* → *Pull request ready for review*. Review the proposed fix on GitHub and merge it yourself; the next push check runs on the merged commit.
8. Try a second project: you get the ₹30 page. Pay with UPI, confirm it on `/admin` ("I received ₹30 · add 1 project slot").

## Existing customers
After this deploy the worker checks every existing project's repository visibility within about 10 minutes. Private ones carry on as
before. Public ones switch to **Waiting for private repo**: nothing more is committed to them, their monitor key is revoked, and the
owner gets the "make it private" email. Existing Python-only installs keep working; pressing **Reinstall monitoring** on the project
page upgrades them to the new monitors (30-second check-ins, failed API calls, every language in the repo).

Existing projects get `watch_mode = both` automatically: their pushes are picked up by the poller (every 3 minutes) from the first deploy.
For instant checks they press **Reconnect webhook** on the project page. Everyone already has one project included; if someone had more
than one project before, nothing is removed, they just cannot add another without a slot.

## If something goes wrong

| You see | Do this |
| --- | --- |
| "Waiting for the test sandbox" on checks | `FIXENGINE_SANDBOX_URL`/`SECRET` missing in Render, or the sandbox server is down: `systemctl status fx-sandbox`, `curl …/health` |
| "No webhook: checked every few minutes" | the token is not an admin of the repo or lacks `repo`; fix the token, press **Reconnect webhook** |
| GitHub webhook deliveries show 401 | the webhook secret changed: press **Reconnect webhook** |
| Checks never start | the worker is not running (`/admin` → System shows "Worker not seen"); free plan: `PORTAL_RUN_WORKER=1` |
| A fix stays as a PR | every proposed fix stays open for human review, even when its checks pass |
| "That commit was already checked" | each commit is checked once; push a new commit |
| **Waiting for private repo** | the repository is public. The customer follows the steps on the project page and presses **I've made it private, install now** |
| **Never checked in** | the monitoring PR is still open, or the app was not re-deployed since. Review and merge it, re-deploy, open the app once. Still nothing: **Reinstall monitoring** |
| **Monitor offline** | the app is down or asleep (free hosting), or was deployed without the monitor files. The app log shows lines starting with `[agent-daemon]` that say why |
| A monitor prints `check-in failed (HTTP 401)` | the project key was replaced: press **Reinstall monitoring** (it commits the current key) |
| Render log: `Agent Daemon cannot start; fix these environment variables` | set the variables it lists (step 2) |
