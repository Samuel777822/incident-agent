# AgentDaemon: return from Voroa to Render on 1 December 2026

Every step that changes production needs your approval at the time. **Never run two production workers at once.**

## Before 30 November

- [ ] Find out from Render how the original services will behave when the monthly usage resets.
- [ ] **Stop the Render worker from starting by itself.** Render's docs say services stopped for bandwidth return at the start of the month. If the original worker restarts while Voroa's worker is live, two workers act on customer repositories. Suspend the original Render services by 30 November if the dashboard allows it. Do not delete them.
- [ ] Decide where the returning data will go (step 3). The original database must not be overwritten.
- [ ] Confirm `TOKEN_ENCRYPTION_KEY` and `SESSION_SECRET` on Render are still the original values.

## Return steps

1. **Verify Render's usage reset.** Check that bandwidth and hours show the new month, and that no card is required to resume.
2. **Verify the original PostgreSQL.** Record its status, plan, version, size and expiry date.
3. **Rehearse the backup.** Take a Voroa backup and restore it into a **new, empty** Render database:

   ```bash
   pg_dump "$VOROA_DATABASE_URL" --format=custom --no-owner --no-acl --file="$HOME/agentdaemon-backups/voroa-rehearsal.dump"
   ```

   ```bash
   pg_restore --no-owner --no-acl --exit-on-error --dbname="$NEW_RENDER_DATABASE_URL" "$HOME/agentdaemon-backups/voroa-rehearsal.dump"
   ```

   If the original database is on Render's Free plan, Render allows only one free database per workspace. Stop and decide with Claude before going further.
4. **Compare table counts** using the query in `VOROA_TEMPORARY_DEPLOYMENT.md` section 6.
5. **Verify environment variables** on Render. Encryption keys must be the originals. `DATABASE_URL` must point at the database chosen in step 3.
6. **Start the Render website with its worker disabled.** Set `PORTAL_RUN_WORKER=0` on the web service and keep the separate Render worker suspended. Test it on the `onrender.com` address.
7. **Stop the Voroa production worker.** Set `PORTAL_RUN_WORKER=0` on Voroa, redeploy, and confirm `worker_last_seen` stops advancing.
8. **Take the final backup.** Stop the Voroa service so nothing else is written, then repeat the dump into a freshly emptied **new** database and compare table counts again. The rehearsal copy from step 3 misses anything written since.
9. **Start exactly one Render production worker.** Confirm in logs that only one is running.
10. **Verify health and incident processing.** Check `/health?deep=1`, login, dashboard, the worker heartbeat, and one test incident.
11. **Move DNS back only after verification and your approval.** Change only the apex and `www` records. Leave Zoho MX, SPF, DKIM and DMARC untouched.
12. **Stop Voroa after Render is confirmed.** Keep the Voroa database and final dump until you are satisfied, then decide separately whether to delete them.

## If the return fails

Before step 8, restart Voroa with `PORTAL_RUN_WORKER=1` after confirming no Render worker is running.

After step 9, the Render database holds the newest data. Do not switch back to Voroa without another backup and restore.

Voroa's free allowance resets at midnight IST on the 1st, so the bridge can continue into December if Render is not ready.
