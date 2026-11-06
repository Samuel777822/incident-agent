# Changelog

## v3.0 (6 November 2026): push guard

**New architecture (the old one is kept).**
* Push guard: GitHub webhook on connect (`/webhooks/github/<project>`, HMAC-signed) plus a poller fallback; every push is tested in the
  sandbox; commit statuses on GitHub; failures open a `push` incident handled by the fix engine; fixes are pushed back as a PR and merged
  in Auto mode once proven (`check_fixed` level). Already-green heads are resolved with no tries spent. Fix-loop protection via `[agent-daemon]`.
* Mixed-language repos: every stack (Python, JS/TS, Java, static HTML) is detected and tested on its own (`detect_profiles`, `run_profile`).
* Live dashboard: tries left per mode, "Agent right now" with stage, working mode and tries left; push checks per project with stack chips.
* Projects: 1 included, ₹30 per extra project (UPI flow, admin confirms; admins can also grant a slot). Packs are now bought by UPI too.
* Plan cards list 30 Normal / 6 High / 3 Extra explicitly.
* Interactive architecture pages: `/how-it-works` (public) and `/admin/architecture` (system, adapters, cost function, router simulator).
* Admins default to `pranavvrao@agentdaemon.xyz` and `abhaysamuel@agentdaemon.xyz`; support `contact@agentdaemon.xyz`.
* Removed: the Java "coming soon" banner, waitlist, unsubscribe page and admin launch controls (Java is supported now); scratch scripts
  (`try_*.py`, `check.py`, `resolve.py`, `add_repo.py`, `check_groq_connection.py`); outdated hand-over docs.
* Copy is language-neutral everywhere (homepage, features, FAQ, help, terms, privacy, chatbot).
* Mobile: nav menus open on tap and stay on screen; every page checked at 390 px and 1366 px with no sideways scrolling.
* Tests: 328 (27 new in `tests/test_push_guard.py`).

## v2 (October–November 2026)
* Merge of the Codex fix engine with the portal work: cost-controlled router, quotas, sandbox, usage pages, plan v2 prices
  (₹200 / ₹1,500), support tickets, visitor counter, IST times, plan text from one source (`plans.py`).

## v1 (October 2026)
* Google sign-in, zero-touch Python monitoring installer, incident grouping, Groq diagnosis, fix PRs, UPI QR billing.
