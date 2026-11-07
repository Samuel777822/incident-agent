# Frontend, API & Controls Verification Proof (Proof G)

- **Total Screens, Forms, Buttons & APIs Tested:** **64**
- **All Passed:** `True`

| Category | Control / Screen | Method & Path | HTTP Status | Result | Detail |
|---|---|---|---|---|---|
| Public & Assets | Render / | `GET /` | `200 OK` | `PASS` | contains 'Agent Daemon' |
| Public & Assets | Render /features | `GET /features` | `200 OK` | `PASS` | contains 'Features' |
| Public & Assets | Render /pricing | `GET /pricing` | `200 OK` | `PASS` | contains 'Pricing' |
| Public & Assets | Render /changelog | `GET /changelog` | `200 OK` | `PASS` | contains 'Changelog' |
| Public & Assets | Render /faq | `GET /faq` | `200 OK` | `PASS` | contains 'Frequently' |
| Public & Assets | Render /privacy | `GET /privacy` | `200 OK` | `PASS` | contains 'Privacy' |
| Public & Assets | Render /terms | `GET /terms` | `200 OK` | `PASS` | contains 'Terms' |
| Public & Assets | Render /about | `GET /about` | `200 OK` | `PASS` | contains 'About' |
| Public & Assets | Render /help | `GET /help` | `200 OK` | `PASS` | contains 'Help' |
| Public & Assets | Render /how-it-works | `GET /how-it-works` | `200 OK` | `PASS` | contains 'Agent Daemon general architecture' |
| Public & Assets | Render /contact | `GET /contact` | `200 OK` | `PASS` | contains 'Contact' |
| Public & Assets | Render /login | `GET /login` | `200 OK` | `PASS` | contains 'Sign in' |
| Public & Assets | Render /assets/home.js | `GET /assets/home.js` | `200 OK` | `PASS` | contains 'function' |
| Public & Assets | Render /assets/chat.js | `GET /assets/chat.js` | `200 OK` | `PASS` | contains 'function' |
| Public & Assets | Render /assets/live.js | `GET /assets/live.js` | `200 OK` | `PASS` | contains 'function' |
| Public & Assets | Render /health | `GET /health` | `200 OK` | `PASS` | contains 'ok' |
| Public & Assets | Render /health?deep=1 | `GET /health?deep=1` | `200 OK` | `PASS` | contains '"database"' |
| Public & Assets | Signup redirects to unified Google sign-in | `GET /signup` | `303 See Other` | `PASS` | redirect -> /login |
| Widget API | Track visitor | `POST /api/visitor/track` | `200 OK` | `PASS` | {"ok": true, "count": 13, "last_updated": "04-11-2026"} |
| Widget API | Send chat message | `POST /api/chat/send` | `200 OK` | `PASS` | {"reply": "Agent Daemon checks every push to GitHub in a sandbox, fixes what broke, and pushes the f |
| Widget API | Fetch chat history | `GET /api/chat/messages` | `200 OK` | `PASS` | assistant replied |
| Authentication | Save profile name | `POST /onboarding/name` | `303 See Other` | `PASS` | redirect -> /dashboard |
| Dashboard | Inactive customer dashboard view | `GET /dashboard` | `200 OK` | `PASS` | shows get-access banner |
| Billing & Trial | Request 30-day free trial | `POST /billing/trial-request` | `200 OK` | `PASS` | trial requested |
| Dashboard | Active customer dashboard view | `GET /dashboard` | `200 OK` | `PASS` | active plan shown |
| Project Connection | New project form | `GET /projects/new` | `200 OK` | `PASS` | form rendered |
| Project Connection | Public repo safety gate on connect | `POST /projects/new` | `201 Created` | `PASS` | held safely until private |
| Project Connection | Recheck visibility & activate | `POST /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/recheck-visibility` | `200 OK` | `PASS` | activated + initial scan queued |
| Monitoring API | Receive 30s heartbeat | `POST /heartbeat` | `200 OK` | `PASS` | {"status":"connected","interval":30,"project_id":"92f3bccb-8535-40f3-b55c-7ec1389e488e","fixing":"on"} |
| Monitoring API | Ingest runtime error | `POST /ingest` | `202 Accepted` | `PASS` | {"accepted":true,"duplicate":false,"incident_id":"d0feb0f1-db54-4df4-9f4f-317ed1afc8f6"} |
| Project View | Project page with live monitor, scan & incident | `GET /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e` | `200 OK` | `PASS` | shows project + incident |
| Live Polling | Dashboard live HTML poll | `GET /dashboard/live` | `200 OK` | `PASS` | returns live state |
| Live Polling | Project incident board live poll | `GET /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/incidents/live` | `200 OK` | `PASS` | returns incident board |
| Incident View | Incident detail, diagnosis, diff & PR link | `GET /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/incidents/d0feb0f1-db54-4df4-9f4f-317ed1afc8f6` | `200 OK` | `PASS` | renders root cause, diff, and PR link |
| Fix Engine UI | Usage & quotas page | `GET /usage` | `200 OK` | `PASS` | renders all 4 tiers |
| Fix Engine UI | Switch fix mode (auto/ask/economy) | `POST /usage/mode` | `303 See Other` | `PASS` | updated mode to ask |
| Project Controls | Update watch mode | `POST /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/watch` | `303 See Other` | `PASS` | watch_mode updated |
| Project Controls | Rotate project ingest key | `POST /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/rotate-key` | `200 OK` | `PASS` | rotated ingest key |
| Billing & Trial | Billing & plan overview | `GET /billing` | `200 OK` | `PASS` | renders plan page |
| Billing & Trial | Manual UPI QR payment page | `GET /billing/pay?plan=monthly` | `200 OK` | `PASS` | renders SVG QR codes |
| Admin Controls | Admin console overview | `GET /admin` | `200 OK` | `PASS` | renders admin console |
| Admin Controls | Fix engine budget & kill-switch admin | `GET /admin/fix` | `200 OK` | `PASS` | renders fix engine admin |
| Admin Controls | Admin pause tier action | `POST /admin/fix` | `200 OK` | `PASS` | paused opus tier |
| Admin Controls | Admin resume tier action | `POST /admin/fix` | `200 OK` | `PASS` | resumed opus tier |
| Admin Controls | Admin model adapter architecture view | `GET /admin/architecture` | `200 OK` | `PASS` | renders both architecture diagrams |
| Navigation Crawl | Follow link / | `GET /` | `303 See Other` | `PASS` | status 303 See Other |
| Navigation Crawl | Follow link /about | `GET /about` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /billing | `GET /billing` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /billing/pay | `GET /billing/pay` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /changelog | `GET /changelog` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /contact | `GET /contact` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /dashboard | `GET /dashboard` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /docs | `GET /docs` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /faq | `GET /faq` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /features | `GET /features` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /help | `GET /help` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /how-it-works | `GET /how-it-works` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /login | `GET /login` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /pricing | `GET /pricing` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /privacy | `GET /privacy` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e | `GET /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/incidents/d0feb0f1-db54-4df4-9f4f-317ed1afc8f6 | `GET /projects/92f3bccb-8535-40f3-b55c-7ec1389e488e/incidents/d0feb0f1-db54-4df4-9f4f-317ed1afc8f6` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /terms | `GET /terms` | `200 OK` | `PASS` | status 200 OK |
| Navigation Crawl | Follow link /usage | `GET /usage` | `200 OK` | `PASS` | status 200 OK |
