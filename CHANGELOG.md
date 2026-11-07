# Changelog

## Monitoring v2 (7 November 2026)
Monitors for every language with 30-second check-ins, "never checked in" / "offline" states, the public-repo gate, a first scan right after connecting, automatic fixes for retired AI models, and animated architecture diagrams. Full details: [CHANGES.md](CHANGES.md); release checks: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

## v3.1 (6 November 2026): explanations for customers, a course for admins

No prices, model ids, quotas, budgets, protections, routing maths or database tables changed. Only how things are explained and shown.

* **One wording everywhere** (`plans.py`: `TRY_DEFINITION`, `WHY_STRONGER`, `FAILED_FIX`, `HUMAN_NEEDED`, `MODE_SUMMARY`, `TRY_SHORT`), used by
  How it works, Usage, dashboard, billing, pricing, FAQ, Help and the chatbot.
* **/how-it-works**: plain-language "How the agent decides which AI to use" (modes, tries, stronger AI, failed fixes, when a person is needed).
  The calculator now shows *Cost of this AI attempt* and *Estimated total cost to resolve the bug* side by side, the usage adjustment
  separately (marked internal), a "Why are these two costs different?" explainer computed live, a clearly labelled demonstration slider,
  and a note that success chances are starting estimates. Technical names are in a collapsed "Show the formula" box.
* **Dashboard**: the line under "<mode> mode is writing a fix" is now a plain sentence ("Starting with a free attempt", "Moving to a stronger
  AI: the cheaper modes are unlikely to fix this bug") instead of the router's internal reason. "Ask for more tries" now confirms what happened.
* **/admin/fix** redesigned: month at a glance (tracked spend, limit B, forecast, estimated credits, clearly not a live balance), a
  spending-protection table (trigger, action, modes, reason, whether you must act; current level highlighted; spike breaker live numbers;
  per-customer and per-bug limits), provider spending with a tokens explainer, per-customer spending with quota use, readable approval
  cards (usage, spend, forecast, why it was held, consequences of approve/deny) with the raw JSON under "Technical details",
  6-month spending history, the current quota/budget settings and the env var that changes each, confirmations before every action.
* **/admin/architecture**: "How the router decides (learn)" — ten lessons (attempt cost, expected cost, probability, repeat decay, quota
  pressure λ, give-up penalty G, dynamic programming, search depth, memoization, hard rules vs optimizer), each with definition, reason,
  exact formula, symbol table, worked example using live settings, and effect on the product. Parameter glossary. The simulator explains
  whether a business rule or the optimizer decided, and why.

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
