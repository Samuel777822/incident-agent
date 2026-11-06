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

1. Unzip `agent-daemon-v3.zip`. You get a folder `agent-daemon-v3`.
2. In your existing local clone of `Samuel777822/incident-agent`:
   ```
   git checkout main && git pull
   git checkout -b v3-push-guard
   ```
3. Delete everything in the clone **except the hidden `.git` folder**, then copy all files from `agent-daemon-v3` into it
   (on Windows, Explorer's "show hidden items" helps; do not copy any `.env`).
4. Check and commit:
   ```
   python -m pip install -r requirements-test.txt
   python -m pytest -q            # expect: 328 passed (a few may be skipped if Node or Java is not installed)
   git add -A
   git commit -m "v3: push guard, multi-language repos, live dashboard, project slots"
   git push -u origin v3-push-guard
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
| `PORTAL_BASE_URL` | `https://incident-agent-portal.onrender.com` (or your domain, see step 5) | **must be right**: GitHub sends push webhooks to this address |
| `PUSH_CHECKS_ENABLED` | `1` | push guard on |
| `PUSH_POLL_SECONDS` | `180` | how often the worker looks for pushes the webhook missed |
| `FIXENGINE_SANDBOX_MODE` | `remote` | the sandbox is the separate server |
| `FIXENGINE_SANDBOX_URL` | `https://sandbox.agentdaemon.xyz` (after step 3) | |
| `FIXENGINE_SANDBOX_SECRET` | a long random string (same one as on the sandbox server) | signs every request to the sandbox |
| `FIXENGINE_ENABLED` | `1` once step 3 works (keep `0` until then) | turns on automatic fixing |
| `OPENROUTER_API_KEY` and/or `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | your keys | the AI modes |
| `FIXENGINE_BUDGET_INR` / `FIXENGINE_CREDITS_INR` | e.g. `1600` / `2000` | global spend cap (80% of what you deposited) |

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

## Step 6. First real test (15 minutes)

1. Make a throw-away **private** GitHub repo with a tiny app and a test, e.g. `app.py` + `test_app.py`, plus a `frontend/` with a
   `package.json` to see a mixed repo.
2. Create a classic token with `repo` and `workflow`. Connect the repo on `/projects/new`, choose **On every push** and **Auto**.
3. The page says "Push guard is on". On GitHub → repo → *Settings* → *Webhooks* you see the webhook with a green tick (ping).
4. Within a minute the project page shows the first check (your latest commit) and GitHub shows a ✓ next to the commit.
5. Break a test and push. Watch the dashboard: *Push check: broken* → *Reproducing* → *Normal mode is writing a fix* → *Testing the fix*
   → *Pushing the fix to GitHub* → *Fix proven · merging* → *Fixed · the fixed version is on GitHub*. Your `main` branch now has a merge
   commit "Merge Agent Daemon fix #N [agent-daemon]" and the next push check is green.
6. Try a second project: you get the ₹30 page. Pay with UPI, confirm it on `/admin` ("I received ₹30 · add 1 project slot").

## Existing customers
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
| A fix stays as a PR in Auto mode | it was not proven (no failing check reproduced it) or a GitHub check is red. That is on purpose |
| "That commit was already checked" | each commit is checked once; push a new commit |
