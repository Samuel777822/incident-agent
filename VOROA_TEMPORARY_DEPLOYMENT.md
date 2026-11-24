# AgentDaemon: temporary Voroa bridge until 1 December 2026

Status: **prepared, not deployed.** Nothing here has been run on Voroa yet. Tick each check only after you have seen it pass.

Branch: `deploy/voroa-temporary-bridge`, based on `origin/main` commit `c6786e8704b4e3fc4aa26c16fa083d1f3b8bf00a`.
`render.yaml` is unchanged. Do not use it on Voroa.

## 1. Architecture

| Part | Voroa type | Runs |
|---|---|---|
| `agentdaemon` | Web service, Docker, Nano, Mumbai | `python run_portal.py`: Gunicorn plus exactly one embedded worker |
| Database | Free PostgreSQL, 1 GB | Production data, after the backup and restore checks in section 6 |

### Why the worker is embedded

Voroa's 750 free hours are shared, and each running service and database counts separately.
From 18 Nov 19:24 IST to 1 Dec 00:00 IST is about **293 hours**.

| Layout | Hours used | Result |
|---|---:|---|
| Web + separate worker + Voroa Postgres | 3 x 293 = **879** | **Over by 129 h. Everything stops around 29 Nov 05:00 IST** |
| **Web with embedded worker + Voroa Postgres** | 2 x 293 = **586** | **Fits, with 164 h spare** |
| Web + separate worker + Render Postgres | 2 x 293 = 586 | Fits only if the Render database is reachable, which is unconfirmed |

Each hour of delay before go-live saves 2 to 3 hours. Staging also uses hours. Check the dashboard for hours already used this month.

Voroa documents that Dockerfile-built services do not idle-sleep, so the embedded worker keeps running without keep-alive requests.
**Confirm this after deployment.** If the service does sleep, stop and reassess.

## 2. Service settings

| Setting | Value |
|---|---|
| Repository and branch | `Samuel777822/incident-agent`, `deploy/voroa-temporary-bridge` |
| Root directory | `/` |
| Runtime | Docker (Dockerfile) |
| Dockerfile path | `/Dockerfile` (cannot be changed later) |
| Region and size | Mumbai, Nano (512 MB, 0.1 vCPU) |
| Start command | None. The Dockerfile `CMD` runs `python run_portal.py` |
| Port | Set by Voroa through `PORT`. Gunicorn binds `0.0.0.0:$PORT`. Never set `PORT` yourself |
| Health check path | `/health` |
| Auto deploy | Off, if the option is offered |

## 3. Environment variables

Enter values only in Voroa's **Environment** tab. Never paste secrets into chat, commits or logs.

### Same on staging and production

| Name | Value |
|---|---|
| `APP_ENV` | `production` |
| `PORTAL_RUN_WORKER` | `0` for the first web check, then `1` |
| `WEB_CONCURRENCY` | `1` |
| `GUNICORN_THREADS` | `2` |
| `WORKER_CASE_THREADS` | `1` |
| `FIXENGINE_SANDBOX_MODE` | `github` |
| `FIXENGINE_ENABLED` | `0` until you approve automated fixes |
| `AGENT_DIRECT_PUSH` | `0` |
| `AUTO_MERGE_ENABLED` | `0` |
| `AGENT_AUTO_REVERT` | `0` |
| `TEMP_CLEANUP_ENABLED` | `1` |
| `TEMP_CLEANUP_DRY_RUN` | `1` at first, then `0` once the logs look right |
| `TEMP_CLEANUP_MAX_AGE_HOURS` | `24` |

### Different per environment

| Name | Staging | Production |
|---|---|---|
| `DATABASE_URL` (secret) | Staging database | Production database |
| `SESSION_SECRET` (secret) | New test-only value | **Exact value from Render** |
| `TOKEN_ENCRYPTION_KEY` (secret) | New test-only value | **Exact value from Render** |
| `PORTAL_BASE_URL` | `https://<service>.onvoroa.com` | `https://agentdaemon.xyz` |
| `COOKIE_DOMAIN` | Leave unset | Same as Render |
| `GOOGLE_REDIRECT_URI` | Leave unset | Same as Render |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Leave unset | Same as Render |
| `ADMIN_EMAILS` | Your test admin address | Same as Render |
| `ADMIN_PASSWORD_<NORMALIZED_EMAIL>` (secret) | New test-only value | Same as Render |
| `PUSH_CHECKS_ENABLED` | `0` until the test repo is connected | `1` |
| `BREVO_API_KEY`, `EMAIL_FROM` | Leave unset | Same as Render |
| `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | Only if testing diagnosis | Same as Render |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `UPI_ID`, `UPI_PAYEE_NAME` | Leave unset | Same as Render |
| `SUPPORT_EMAIL`, `FIXENGINE_BUDGET_INR`, `FIXENGINE_CREDITS_INR` | Leave unset | Same as Render |

Make test-only values on your own computer:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Never generate these for production.** A different `TOKEN_ENCRYPTION_KEY` makes saved GitHub tokens and webhook secrets unreadable.

## 4. Automated remediation

`origin/main` can change customer repositories without review. This branch starts with all of that off.

| Behaviour | Control | Bridge default |
|---|---|---|
| Merge auto-mode pull requests | `AUTO_MERGE_ENABLED` (added on this branch) | Off |
| Push fixes straight to a customer's branch | `AGENT_DIRECT_PUSH` | Set to `0` |
| Revert a pushed fix automatically | `AGENT_AUTO_REVERT` | Set to `0` |
| AI fix engine | `FIXENGINE_ENABLED` | Set to `0` |

Known effects while these are off:
- Auto-mode pull requests stay open for a person to merge, although some page text still says they merge automatically.
- Retired-AI-model fixes still run without the fix engine and open a pull request.
- **Not covered by these gates:** when a customer connects a repository and authorizes the monitor install, `web_app.py` still merges that monitoring pull request automatically. It adds monitoring code only, and the customer ticks a consent box first.

PR #15's review-only work is **not** on `origin/main`, and its 42-file change conflicts with `main`. This branch adds only the gates above and does not merge PR #15.

## 5. Staging

Use test data only. Never restore production data into staging.

1. Create the free Postgres database. Voroa allows **one per account**.
2. Create a separate logical database named `agentdaemon_staging` inside it, if Voroa permits `CREATE DATABASE`. Otherwise tell Claude before continuing.
3. Deploy the web service with staging values and `PORTAL_RUN_WORKER=0`.
4. Verify:
   - [ ] `https://<service>.onvoroa.com/health` returns `ok`
   - [ ] `/health?deep=1` shows `"ok": true` and `"database": "postgresql"`
   - [ ] Sign-up, login, logout and dashboard work
   - [ ] Restart the service and repeat the health checks
   - [ ] Metrics show memory comfortably below 512 MB
5. Set `PORTAL_RUN_WORKER=1` and redeploy. Verify:
   - [ ] `worker_last_seen` in `/health?deep=1` keeps advancing
   - [ ] Logs show `Portal incident worker started` exactly once
   - [ ] A test repository incident is detected and diagnosed
   - [ ] Memory stays below about 430 MB (85%) while a case runs
   - [ ] The service stays awake after 20 idle minutes
6. Delete the staging service before production go-live, so it stops using hours.

## 6. Production database

Fill this in from the Render dashboard before choosing:

| Question | Answer |
|---|---|
| Running? | |
| Plan and expiry date | |
| PostgreSQL version | |
| Storage used (must fit 1 GB) | |
| External access enabled? | |

Back up outside the Git repository, with a client version at least as new as the server:

```bash
pg_dump "$SOURCE_DATABASE_URL" --format=custom --no-owner --no-acl --file="$HOME/agentdaemon-backups/render-final.dump"
```

```bash
pg_restore --list "$HOME/agentdaemon-backups/render-final.dump"
```

```bash
pg_restore --no-owner --no-acl --exit-on-error --dbname="$TARGET_DATABASE_URL" "$HOME/agentdaemon-backups/render-final.dump"
```

Compare exact row counts. Run this against both databases and compare the output:

```bash
psql "$DATABASE_TO_CHECK" -At -c "SELECT table_name, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1"
```

The destination must be empty and on the same or a newer PostgreSQL version. **Voroa's free database has no backups**, so take your own after go-live. Dumps count toward bandwidth.

## 7. Monitoring limits

Check **Billing > Monthly Included Usage** every day.

| Meter | Limit | Warn at | If exhausted |
|---|---:|---:|---|
| Instance hours | 750 h | 600 h (Voroa emails at 80%) | Free services and databases stop until 1 Dec |
| Bandwidth | 5 GB | **3.5 GB, act at 4 GB** | All free services stop until 1 Dec |
| Build minutes | 500 | 400 | New deploys pause; running services continue |
| Service disk | 5 GB | Voroa emails at 80% | Service may restart and lose temporary files |

**Bandwidth estimate.** Render's 5 GB ran out by 14 Nov, which is at most about 0.37 GB per day before the gzip and `204` work. Over 12.2 days:

| Scenario | Assumption | Estimate |
|---|---|---:|
| Normal | 40% of the old rate (assumption, not measured) | About 1.8 GB |
| High | Same as the old rate | About 4.5 GB (90%) |

Worker traffic to GitHub and AI providers also counts. Voroa may show bandwidth as "Not measured", which does not mean zero. If so, ask Voroa support how to track it.

## 8. Temporary disk

Service disk is erased on deploy and may be erased at other times. Customer data lives only in PostgreSQL.

`temp_cleanup.py` runs in the worker hourly when `TEMP_CLEANUP_ENABLED=1`. It removes only folders that:
- sit directly in the temp folder or `FIXENGINE_SCRATCH`,
- start with `fx-` or `incident-agent-`,
- are real folders owned by the app's user, and
- have had nothing changed inside for the configured age (minimum 6 hours).

## 9. Domain and integrations (only after your approval)

Staging uses the `onvoroa.com` address. It must not be added to any production webhook, OAuth or payment setting.

Production keeps `https://agentdaemon.xyz`, so GitHub webhooks, customer monitors, Google OAuth and Razorpay webhooks need no change if they already use that domain. **Confirm the Razorpay and Google settings in their dashboards.**

DNS cutover:
1. Export the current DNS zone and keep a copy.
2. Add `agentdaemon.xyz` and `www.agentdaemon.xyz` in Voroa. The Free plan includes two domains.
3. Change only the apex and `www` records to the exact values in Voroa's **View DNS**.
4. **Do not touch** Zoho MX, SPF, DKIM or DMARC records.
5. If Cloudflare proxies the domain, use SSL mode **Full (strict)**. Flexible mode fails.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| Deploy fails at startup | Logs for `Agent Daemon cannot start`, which names the missing setting |
| `/health?deep=1` returns 503 | `DATABASE_URL`, and whether the database is running |
| Saved GitHub tokens fail | `TOKEN_ENCRYPTION_KEY` differs from Render. Restore the exact value |
| Everyone is signed out | `SESSION_SECRET` differs from Render |
| Worker heartbeat stops | Logs for restarts and memory. Set `PORTAL_RUN_WORKER=0` while investigating |
| Restart loop or out of memory | Lower `GUNICORN_THREADS` to `1`. Do not raise case threads |

## 11. Rollback

1. Set `PORTAL_RUN_WORKER=0` on Voroa, or stop the service, and confirm no worker is running.
2. Take a backup of the Voroa database if it received production writes.
3. Restore the previous DNS records from your saved copy.
4. Start Render only when it is available again, following `RENDER_RETURN_PLAN.md`.

The original Render service and database are never deleted or overwritten by this plan.
