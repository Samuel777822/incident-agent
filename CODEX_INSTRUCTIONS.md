# Codex instructions: deploy and verify Agent Daemon (code is already written and tested)

You are NOT here to redesign or rewrite this project. The code in this folder was written and tested by Claude:
**75 automated tests pass** and a real-server smoke test passed (sign-up, trial request, admin approval, dashboard).
Your job is to put it into the GitHub repo, configure Render, and verify it works live. Follow the steps in order.
Do not skip verification. Do not claim something works unless you saw it work.

Repository: https://github.com/Samuel777822/incident-agent (branch `main`)
Production portal: https://incident-agent-portal.onrender.com (Render, free plan, UptimeRobot pings it)
Demo customer app: https://cofee-shop-q36h.onrender.com, repo https://github.com/Samuel777822/cofee-shop
Admins (the only two): naveenachandra371@gmail.com and pranavvrao1@gmail.com

## 0. Ground rules (read first)

**YOU MUST NOT WRITE OR EDIT ANY CODE.** Do not create or change any `.py` file, `requirements*.txt`, `Dockerfile`, workflow or test.
Your whole job is: copy the files, install what the project needs, run the tests, commit, push, configure Render, and verify. If anything fails,
report the exact error and STOP. Do not "fix" it with new code, stubs, try/except wrappers, deleted tests or edited requirements.
Install whatever packages are needed with pip. Installing packages is allowed and expected; writing code is not.

DO NOT:
- redesign the UI or change layout/colours yet. A UI pass comes later, and only after everything works.
- delete, skip, or weaken any test to make things pass. If a test fails, report the failure and the cause.
- print, log, commit, or paste any secret (API keys, passwords, tokens, `.env`). Secrets go only into Render's
  environment settings. Never ask the user to paste secrets into chat.
- change prices (₹100 / 30 days, ₹1000 / 365 days) or let the browser send an amount. Amounts are decided on the server.
- make `/dashboard` redirect inactive users again, or merge Dashboard and Plan & billing back into one page.
- put the QR image back on an external site. The QR is generated on the server as an inline image.
- send email over SMTP on Render's free plan (it is blocked). Use the HTTPS provider (Brevo) already built in.
- auto-approve manual UPI payments. A typed reference proves nothing. Only an admin confirms those.
- loosen CSRF, cookies, or the Content-Security-Policy.
- change `DATABASE_URL` or touch the production database without asking the user.
- touch the separate legacy `agent-daemon` Render service (it runs `server.py` for the coffee-shop demo).

## 1. Put the code in the repo

1. `git clone https://github.com/Samuel777822/incident-agent` and `git checkout -b portal-overhaul`.
2. Copy everything from this folder into the clone, replacing files. Keep the clone's `.git`. Do not copy any `.env`.
   Delete `fake.log` from the repo if it exists (it is a committed runtime log).
3. Check `python --version`. **It must be Python 3.10 or newer; use 3.12 or 3.13.** Python 3.9 or older cannot install this project
   (`render>=1.2.0` fails with "Could not find a version that satisfies the requirement render" and the code needs 3.10+).
   If your Python is older, install Python 3.12 or 3.13 and use that. Then create a FRESH virtual environment:
   `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`), then install **the test requirements**:
   `python -m pip install -r requirements-test.txt` and run `python -m pytest -q`. **Expected: `75 passed`.**
   - `requirements-test.txt` is everything the tests need. `requirements.txt` is the PRODUCTION list that Render installs, in a Python 3.13 image. Never edit it.
     If you also install `requirements.txt` and only the `render` line fails on a Python that IS 3.10+, ignore that package: only the legacy
     `workflows.py` imports it and no test needs it. Install the rest and go on.
   - A `ModuleNotFoundError` / `ImportError` (for example `No module named 'segno'`, `'httpx'`, `'cryptography'`) is an ENVIRONMENT problem,
     not a code bug: install the requirements into the same Python that runs pytest (`which python`, `python -m pip list`). Do NOT edit code.
   - The two QR tests (`test_manual_upi_page_has_inline_qr_and_fixed_amounts` and `test_customer_is_told_to_wait_and_admins_are_emailed`)
     fail ONLY when `segno` is missing from that Python. `tests/test_environment.py` names the missing package. Install it and re-run.
     Verified: with the test requirements installed, all 75 tests pass on Python 3.12 and 3.13.
   - `agent_daemon.py` and `resolve.py` start with a byte-order mark. That is harmless; do not touch them.
   - If the sandbox has no internet and `pip` cannot install, say so plainly and stop. Report the Python version, `python -m pip list`, and the exact
     pytest output. Do not claim the tests pass.
   - Any other failure: stop and report the exact test name and traceback. Do not change code.
4. `git add -A`, commit with message `Portal overhaul: trials, instant payments, admin dashboard, email, auto-install`,
   push the branch, and open a pull request into `main`. Wait for the GitHub Action "tests" to go green, then merge.
   Render redeploys automatically. Database changes are applied automatically at startup (`init_db` is safe to repeat).

## 2. Render environment variables (portal web service)

Open the portal service on dashboard.render.com, Environment tab. Check/add these. Never print values back.

| Name | Value |
| --- | --- |
| `ADMIN_EMAILS` | `naveenachandra371@gmail.com,pranavvrao1@gmail.com` |
| `ADMIN_PASSWORD_NAVEENACHANDRA371_GMAIL_COM` | a strong random password the user chooses (admin login) |
| `ADMIN_PASSWORD_PRANAVVRAO1_GMAIL_COM` | a strong random password the user chooses |
| `PORTAL_BASE_URL` | `https://incident-agent-portal.onrender.com` |
| `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY`, `DATABASE_URL`, `APP_ENV=production` | must already exist; do not change |
| `BREVO_API_KEY`, `EMAIL_FROM` | see section 3 |
| `RAZORPAY_*` | leave unset |
| `UPI_ID`, `UPI_PAYEE_NAME` | optional; default `7975291636@ptsbi` and `Pranav V Rao` |

If a Google sign-in is configured, leave `GOOGLE_CLIENT_ID/SECRET` alone. Tell the user: an admin who first signs in
with the password cannot later link Google for the same email, so each admin should pick one method.

## 3. Email (must work, the user cares about this)

The user has no email provider yet. Walk them through it, one step at a time:
1. Create a free account at brevo.com.
2. In Brevo: Senders, Domains & Dedicated IPs → Senders → add a sender with one of the admin Gmail addresses and
   confirm it from the verification email Brevo sends.
3. Brevo: SMTP & API → API Keys → create a key. Copy it straight into Render as `BREVO_API_KEY`
   (not into chat). Set `EMAIL_FROM` to the verified sender address exactly.
4. Redeploy, sign in as an admin, open `/admin`, press **Send test email to both admins**.
5. Open **Email status** on the same page. Each row must say `accepted`. Then check both real inboxes (and spam).
   If a row says `failed`, the page shows the provider's reason. Fix that reason, do not work around it.
   "accepted" means the provider took the message; confirm arrival in the inbox yourself.

## 4. Payments (manual Paytm QR, this is the final design)

The user has no payment gateway and does not want one. Payments work like this, and you must not change it:
1. Customer opens Plan & billing and presses **Pay ₹100 by UPI** (or ₹1,000). The page shows the Paytm QR for
   `7975291636@ptsbi` (Pranav V Rao) with the exact amount, an "Open UPI app" button, and a plain QR as a fallback.
2. Customer pays, enters the 12-digit UPI reference (UTR), and presses "I have paid". The page tells them to wait 1 to 2 hours,
   and they get an email saying so.
3. Both admins get an email: customer X says they paid ₹100, with the reference.
4. An admin opens the Paytm app, finds that exact reference and amount, then opens `/admin` and presses
   **I received ₹100 · grant 30 days** (or **Not received**). Only then does access start, and the customer gets an email.
5. `/admin` lists customers needing action first and shows each customer's state: Trial, Paid or No access with the expiry.
Do NOT add automatic approval, SMS reading, or any code that grants access without an admin click. Do not set any
`RAZORPAY_*` variables (the gateway code is dormant and must stay off). Leave `UPI_ID` and `UPI_PAYEE_NAME` unset; the defaults are correct.

Check: pay a real ₹100 from another UPI account, enter the UTR, confirm the customer page says "wait 1 to 2 hours", confirm both
admin inboxes got the email, confirm the customer has NO access yet, press the confirm button, confirm 30 days of access and the customer email.

## 5. Keep it awake

UptimeRobot must ping `https://incident-agent-portal.onrender.com/health` every 5 minutes. The diagnosis worker runs
inside the web service (`PORTAL_RUN_WORKER` default), so it only works while the service is awake.

## 6. Verification checklist (do all, report each as PASS or FAIL with evidence)

1. New customer signs up with email + password: lands on `/dashboard` showing "Monitoring is off". (Sign-up used to crash with a 500.)
2. Nav for a customer shows only **Projects** and **Plan & billing**; the two pages look different.
3. Customer presses **Request free trial**: both admins' inboxes get an email, and `/admin` shows the request under "Trial requests".
4. Admin presses **Approve 1-day trial**: customer immediately sees "Free trial · … left" and the **Connect a project** button.
   The customer can never request a second trial.
5. Admin page: "Customers" shows Grant access for inactive customers and only Revoke access for active ones; revoke then grant resumes the customer's projects.
6. Connect a project using the demo repo `Samuel777822/cofee-shop` with a fine-grained GitHub token (Contents and Pull requests read/write).
   Expected: a PR "Add Agent Daemon error monitoring" is opened and merged automatically; the cofee-shop service redeploys; within about 5 minutes the dashboard
   card shows **Live** with a recent "Last check-in". If the repo is public, expect the page to show the two environment variables to set instead.
7. Break the coffee shop checkout, then watch an incident appear on the dashboard with the agent status and a fix PR link.
8. Payments: run the check at the end of section 4.
9. Run `python -m pytest -q` once more on the deployed commit: 75 passed.

## 7. Known limits to tell the user (do not hide them)

- Render's free PostgreSQL expires after about 30 days. Recommend moving `DATABASE_URL` to Neon or Supabase soon. Ask before changing it.
- Free web services sleep when idle; UptimeRobot mitigates this.
- Automatic fixing supports Python repositories only.
- Payments are confirmed by an admin (1 to 2 hours by design). Nothing can see UPI money arrive by itself.

## 8. Reporting

When finished, send the user a short report: what you changed, which checklist items PASSED, which FAILED and why, and
what only the user can do (Brevo sign-up and API key, choosing the two admin passwords).

## 9. Later: the UI pass (only after section 6 passes)

When the user asks for visual work, change only CSS and markup in the `_page_*` functions of `web_app.py` and the `CSS`
string. Keep every form `action`, input `name`, button `name`/`value`, and the visible button texts, because the tests assert them.
Run the full test suite after every change.
