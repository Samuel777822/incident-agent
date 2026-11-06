"""Footer navigation and standalone pages for Agent Daemon:
- Product: Features (/features), Pricing (/pricing), Documentation (/docs), Changelog (/changelog)
- Company: About Us (/about), Contact Us (/contact)
- Resources: FAQ (/faq), Help Center (/help)
- Legal: Privacy Policy (/privacy), Terms of Service (/terms)
"""

from __future__ import annotations
import os

import plans


WEBSITE_LAST_UPDATED = os.getenv("WEBSITE_LAST_UPDATED", "04-11-2026")


def render_visitor_counter_tiles(count: int) -> str:
    """Format the cumulative visitor count into prominent NIC/government-portal style digit cells."""
    digits = f"{max(count, 0):06d}"
    return "".join(f'<span class="gov-digit-tile">{d}</span>' for d in digits)


def render_footer_html(visitor_count: int | None = None) -> str:
    if visitor_count is None:
        try:
            import portal_db
            visitor_count = portal_db.get_total_unique_visitors()
        except Exception:
            visitor_count = 0

    tiles_html = render_visitor_counter_tiles(visitor_count)
    try:
        import notifications
        support = notifications.support_email()
    except Exception:
        support = "contact@agentdaemon.xyz"
    return f"""<footer class="wrap footer">
  <div class="footer-grid">
    <div class="footer-col">
      <div class="footer-heading">Product</div>
      <ul class="footer-links">
        <li><a href="/how-it-works">How It Works</a></li>
        <li><a href="/features">Features</a></li>
        <li><a href="/#security">Security</a></li>
        <li><a href="/pricing">Pricing</a></li>
        <li><a href="/docs">Documentation</a></li>
        <li><a href="/changelog">Changelog</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Company</div>
      <ul class="footer-links">
        <li><a href="/about">About Us</a></li>
        <li><a href="/contact">Contact Us</a></li>
        <li><a href="mailto:{support}">{support}</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Resources</div>
      <ul class="footer-links">
        <li><a href="/faq">FAQ</a></li>
        <li><a href="/help">Help Center</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Legal</div>
      <ul class="footer-links">
        <li><a href="/privacy">Privacy Policy</a></li>
        <li><a href="/terms">Terms of Service</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Account</div>
      <ul class="footer-links">
        <li><a href="/login">Sign In</a></li>
        <li><a href="/login">Get Started</a></li>
      </ul>
    </div>
  </div>
  
  <!-- NIC-INSPIRED WEBSITE INFORMATION STRIP -->
  <div class="gov-info-strip" aria-label="Website Information and Visitor Statistics">
    <div class="gov-info-container">
      
      <!-- LEFT: VISITOR COUNTER -->
      <div class="gov-info-block gov-visitors-block">
        <div class="gov-info-icon-wrap" aria-hidden="true" title="Visitor Count">
          <svg class="gov-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
            <circle cx="9" cy="7" r="4"></circle>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
          </svg>
        </div>
        <div class="gov-info-content">
          <div class="gov-info-label">TOTAL VISITORS SINCE LAUNCH</div>
          <div class="gov-odometer-wrap" id="gov-visitor-display" data-target="{visitor_count}">
            {tiles_html}
          </div>
        </div>
      </div>

      <!-- CENTER SEPARATING DIVIDER -->
      <div class="gov-info-divider" aria-hidden="true"></div>

      <!-- RIGHT: WEBSITE LAST UPDATED -->
      <div class="gov-info-block gov-updated-block">
        <div class="gov-info-icon-wrap" aria-hidden="true" title="Website Last Updated Date">
          <svg class="gov-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="16" y1="2" x2="16" y2="6"></line>
            <line x1="8" y1="2" x2="8" y2="6"></line>
            <line x1="3" y1="10" x2="21" y2="10"></line>
            <path d="M8 14h.01"></path>
            <path d="M12 14h.01"></path>
            <path d="M16 14h.01"></path>
            <path d="M8 18h.01"></path>
            <path d="M12 18h.01"></path>
            <path d="M16 18h.01"></path>
          </svg>
        </div>
        <div class="gov-info-content">
          <div class="gov-info-label">WEBSITE LAST UPDATED</div>
          <div class="gov-date-badge">
            <span class="gov-date-val">{WEBSITE_LAST_UPDATED}</span>
          </div>
        </div>
      </div>

    </div>
  </div>

  <div class="footer-bottom">
    <div class="footer-brand-line">
      <span class="brand"><span class="brand-mark">A</span>Agent Daemon</span>
      <span class="muted">· Catches the bug when you push, fixes it, and pushes the fix back. Any language your app is written in.</span>
    </div>
    <div class="muted" style="font-size:13px">
      &copy; 2026 Agent Daemon · By Agent Daemon team of engineers · Built for resilient engineering teams.
    </div>
  </div>
</footer>"""


def features_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">What Agent Daemon does</div>
<h1>Push your code. The agent catches what broke, fixes it, and pushes the fix back.</h1>
<p>Built for vibe coders, students and hackathon teams who have no time to debug. Works with Python, JavaScript, TypeScript, Java and plain HTML/CSS sites, including repos that mix them.</p>
<div class="actions" style="justify-content:center"><a class="button primary" href="/how-it-works">See the architecture</a><a class="button" href="/pricing">Plans</a></div>
</section>

<section class="grid" style="margin-top:28px">
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#8593;</div>
    <h3>Push guard (catches bugs before you deploy)</h3>
    <p class="muted">Every push to your branch is installed, built, type-checked, tested and started in a throw-away sandbox within minutes. Green means safe to deploy; red means the agent is already fixing it. You see the result as a status dot on the commit in GitHub.</p>
  </article>
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#9783;</div>
    <h3>Every language in the repo</h3>
    <p class="muted">A Python API in <code>backend/</code>, a React or Next.js app in <code>frontend/</code> and a static landing page at the root? Each one is found and checked on its own, and a fix may touch whichever part is broken.</p>
  </article>
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#8644;</div>
    <h3>Fix pushed back to GitHub</h3>
    <p class="muted">The fix lands on a new <code>agent-daemon/fix-&hellip;</code> branch with a pull request. In Auto mode it is merged into your branch as soon as the same sandbox check proves it works, so the fixed version is on GitHub without you lifting a finger.</p>
  </article>
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#9889;</div>
    <h3>Live error watch (classic)</h3>
    <p class="muted">Already deployed? Keep the classic mode on as well: a tiny client reports crashes from the running app, and the same fix pipeline takes over.</p>
  </article>
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#8721;</div>
    <h3>Cost-aware model router</h3>
    <p class="muted">An expected-cost optimizer (a dynamic program, the same idea as Dijkstra's cheapest path but for uncertain steps) picks the cheapest mode likely to fix each bug, starting free and moving up only when needed.</p>
  </article>
  <article class="card">
    <div class="feat-ico" aria-hidden="true">&#128274;</div>
    <h3>Safe by design</h3>
    <p class="muted">Your code only runs inside an isolated container with no secrets and no network during tests. Models only return text; our code applies the patch. Tests, CI files, build configs and secrets can never be edited by a model. Tokens are encrypted at rest.</p>
  </article>
</section>

<section class="card mission-card" style="margin-top:40px;text-align:center">
  <h3>Ready to stop debugging at 3 AM?</h3>
  <p>Connect a repository in about a minute. Your first push check starts right away.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/login">Continue with Google</a>
    <a class="button" href="/how-it-works">How it works</a>
    <a class="button" href="/pricing">View plans</a>
  </div>
</section>"""


def _plan_quota_list() -> str:
    rows = "".join(f"<li><b>{m}</b> &middot; {amt} <span class='muted'>&middot; {what}</span></li>" for m, amt, what in plans.quota_lines())
    return f"<ul class='quota-list'>{rows}</ul>"


def pricing_page_html(signed_in: bool = False) -> str:
    cta_href = "/billing" if signed_in else "/login"
    cta_text = "Go to plan &amp; billing" if signed_in else "Sign in to subscribe"
    q = plans.quotas()
    quota_list = _plan_quota_list()
    return f"""<section class="about-hero">
<div class="eyebrow">Simple, honest plans</div>
<h1>One price. {q["normal"]} Normal, {q["high"]} High and {q["extra"]} Extra fixes every month.</h1>
<p>Start with a free 1-day trial. Every plan includes push checks on every commit, all languages, and one project. Add more projects for &#8377;{plans.PROJECT_SLOT_PRICE} each.</p>
</section>

<div class="price-grid">
  <article class="price-card">
    <span class="badge-tag setup">Try it</span>
    <h3>1-day free trial</h3>
    <div class="price">&#8377;0</div>
    <p class="muted">The whole product on your own repository for one day. Approved by the team, usually within 1 to 2 hours.</p>
    <ul class="quota-list"><li>Push checks on every commit</li><li>The full fix pipeline</li><li>1 project</li></ul>
    <a class="button" href="{cta_href}">Request free trial</a>
  </article>

  <article class="price-card featured">
    <span class="badge-tag bug">Most popular</span>
    <h3>Monthly</h3>
    <div class="price">&#8377;{plans.PLAN_PRICES["monthly"]:,}<small> / 30 days</small></div>
    <p class="muted">Every month you get:</p>
    {quota_list}
    <ul class="quota-list"><li>Push checks on every commit (fair use: up to 12 an hour per project)</li><li>{plans.INCLUDED_PROJECTS} project included &middot; extra projects &#8377;{plans.PROJECT_SLOT_PRICE} each</li></ul>
    <a class="button primary" href="{cta_href}">{cta_text}</a>
  </article>

  <article class="price-card">
    <span class="badge-tag git">Best value &middot; Save &#8377;{plans.YEARLY_SAVING:,}</span>
    <h3>Yearly</h3>
    <div class="price">&#8377;{plans.PLAN_PRICES["yearly"]:,}<small> / 365 days &middot; about &#8377;{plans.YEARLY_PER_MONTH:,} a month</small></div>
    <p class="muted">Everything in Monthly for a year. The same monthly tries, renewed every month:</p>
    {quota_list}
    <a class="button primary" href="{cta_href}">{cta_text}</a>
  </article>
</div>

<section class="card" style="margin-top:28px">
  <h3>Add-ons</h3>
  <div class="addon-row">
    <div><b>Extra project</b><span class="muted">One-time &#8377;{plans.PROJECT_SLOT_PRICE}. Connect one more repository. The slot stays on your account.</span></div>
    <div><b>High pack</b><span class="muted">A &#8377;{plans.PACK_PRICE} pack adds {plans.PACK_HIGH_TRIES} more High tries this month.</span></div>
    <div><b>Extra pack</b><span class="muted">A &#8377;{plans.PACK_PRICE} pack adds {plans.PACK_EXTRA_TRIES} more Extra tries this month.</span></div>
  </div>
</section>

<section class="card" style="margin-top:28px">
  <h3>What a "try" is</h3>
  <p class="muted">A try is one attempt by the agent to write a fix that passes the sandbox check. The agent starts with Low effort (free), then Normal, and moves up to High or Extra only when the cheaper modes cannot fix the bug. You can also pick a mode yourself or send a bug to human review. You are buying attempts, not a guaranteed fix: no automated system fixes every bug. Quotas reset on the 1st and do not roll over. A technical fault on our side never counts as a try.</p>
</section>

<section class="card" style="margin-top:28px">
  <h3>Paying</h3>
  <p class="muted">Pay with any UPI app (Paytm, Google Pay, PhonePe, BHIM) by scanning our QR, then enter the 12-digit UTR. An admin checks the payment and switches your access on, usually within 1 to 2 hours.</p>
</section>"""


def changelog_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Product Releases</div>
<h1>Agent Daemon Changelog</h1>
<p>Tracking the latest enhancements, model upgrades, and reliability improvements across our platform.</p>
</section>

<div class="accordion-group" style="margin-top:36px">

  <article class="card" style="margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v2.0 &mdash; Push guard: catch it before you deploy</h3>
      <span class="pill green">Latest release &middot; Nov 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Push checks:</b> every push to your branch is installed, built, tested and started in the sandbox. The result shows up on the commit in GitHub.</li>
      <li><b>Fix pushed back:</b> a broken push opens an incident; the agent writes a fix, proves it with the same check, and pushes it as a pull request (merged automatically in Auto mode).</li>
      <li><b>Mixed-language repos:</b> Python, JavaScript/TypeScript, Java and HTML/CSS parts of one repo are each checked on their own.</li>
      <li><b>Live dashboard:</b> see which mode is working on a bug, what it is doing right now (testing in the sandbox, pushing, merging) and how many tries you have left.</li>
      <li><b>Projects:</b> one included, more for &#8377;30 each. Plans list 30 Normal, 6 High and 3 Extra tries a month.</li>
      <li><b>Architecture page:</b> an interactive map of the whole system at <a href="/how-it-works">/how-it-works</a>.</li>
    </ul>
  </article>

  <article class="card" style="margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v1.3 &mdash; Help Centre &amp; Troubleshooting Knowledge Base</h3>
      <span class="pill">Nov 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Embedded Video Walkthrough:</b> Added comprehensive demo screencast with key timestamp chapters.</li>
      <li><b>Troubleshooting Playbooks:</b> 6 actionable guides covering sleeping free containers, GitHub token errors (401/403/404), safety gates, and CI auto-merge prerequisites.</li>
      <li><b>Instant Search Filter:</b> Live client-side keyword search across all documentation sections.</li>
      <li><b>Structured Footer:</b> Added organized 4-column navigation (Product, Company, Resources, Legal).</li>
    </ul>
  </article>

  <article class="card" style="margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v1.2 &mdash; Direct Support &amp; Incident Alerts</h3>
      <span class="pill">Oct 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Contact Us Page (/contact):</b> Dedicated inquiry form with guest submission capability and CSRF protection.</li>
      <li><b>Instant Incident Alerts:</b> Automated Brevo/Resend HTTPS notifications dispatching to the Agent Daemon team of engineers upon form submission.</li>
      <li><b>Admin Inquiries Console:</b> Manage incoming support queries with one-click email reply links.</li>
    </ul>
  </article>

  <article class="card" style="margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v1.1 &mdash; AI Assistant &amp; Live Chat</h3>
      <span class="pill">Oct 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Groq LLM Chatbot:</b> Embedded dark-mode conversational assistant answering visitor queries about features, pricing, and architecture.</li>
      <li><b>Admin Chat Console:</b> Live multi-tab messaging drawer for the Agent Daemon team of engineers to take over chat sessions in real time.</li>
      <li><b>Visitor Telemetry:</b> Anonymous visitor journey tracking with automated alert deduplication.</li>
    </ul>
  </article>

  <article class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v1.0 &mdash; Core Platform Launch</h3>
      <span class="pill">Oct 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Google OAuth2 Authentication:</b> Secure, passwordless sign-in with display name capture.</li>
      <li><b>Zero-Touch Monitoring Installer:</b> One-click GitHub PR installing client, app entrypoint hook, and test workflow.</li>
      <li><b>Autonomous Auto-Fix Engine:</b> Incident grouping, Groq root-cause extraction, AST patch synthesis, and CI-gated auto-merge.</li>
      <li><b>Paytm UPI QR Billing:</b> QR payment generation and UTR verification workflow.</li>
    </ul>
  </article>

</div>"""


def faq_page_html() -> str:
    return f"""<section class="about-hero">
<div class="eyebrow">Frequently Asked Questions</div>
<h1>Everything You Need to Know</h1>
<p>Clear answers to common questions about permissions, security, autonomous pull requests, and pricing.</p>
</section>

<div class="accordion-group" style="margin-top:36px">

  <details class="accordion-item" open>
    <summary class="accordion-summary">How does Agent Daemon catch a bug before I deploy?</summary>
    <div class="accordion-body">
      <p>When you connect a repository we add a GitHub webhook. Every push to your branch is downloaded into a fresh, throw-away sandbox where we install the dependencies, build, type-check, run your tests and start the app. If anything fails, the commit gets a red status on GitHub, an incident opens on your dashboard, and the agent starts writing a fix. If the webhook cannot be added, the worker checks your branch every few minutes instead.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">Does my code run on your servers?</summary>
    <div class="accordion-body">
      <p>Only inside the sandbox: an isolated container with no secrets, no access to our servers, memory and time limits, and no network while tests run (network is allowed only while dependencies install). It is deleted after every run. The web portal itself never runs customer code. AI models only ever receive text and return text.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">My repo mixes languages (Python backend, React frontend, HTML pages). Does that work?</summary>
    <div class="accordion-body">
      <p>Yes. Each part is found by its own marker file (<code>requirements.txt</code>/<code>.py</code>, <code>package.json</code>, <code>pom.xml</code>/<code>build.gradle</code>, <code>.html</code>) and checked separately. The commit is green only when every part passes, and a fix can touch whichever part is broken.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How does Auto mode push the fixed version to GitHub?</summary>
    <div class="accordion-body">
      <p>The fix is committed to a new <code>agent-daemon/fix-&hellip;</code> branch and opened as a pull request into your branch. When the sandbox proves the fix (the check that failed now passes), the fix commit gets a green status and Auto mode squash-merges it, so your branch on GitHub holds the fixed version. In Pull request mode it waits for you to merge. Nothing is ever pushed straight to your branch without a pull request.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How many projects can I connect?</summary>
    <div class="accordion-body">
      <p>Every plan includes one project. Each extra project is a one-time &#8377;{plans.PROJECT_SLOT_PRICE}. Your monthly tries are shared by all your projects.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">What if I want a human to approve all code changes?</summary>
    <div class="accordion-body">
      <p>Select <b>Pull Request Only (<code>pr_only</code>)</b> mode. Agent Daemon will diagnose the issue and open a clean GitHub Pull Request with the unified diff and explanation, but leaves the final merge decision entirely to your team.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How are my GitHub Personal Access Tokens stored?</summary>
    <div class="accordion-body">
      <p>Tokens are encrypted at rest using Fernet symmetric encryption (AES-128 in CBC mode with PKCS7 padding and HMAC-SHA256 authentication). Tokens are never logged or exposed in plain text. You can revoke the token on GitHub at any time to instantly revoke all access.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">What happens if a patch fails tests in CI?</summary>
    <div class="accordion-body">
      <p>Agent Daemon will <b>never</b> merge a failing PR. If tests fail, the PR is left open with the CI failure status recorded, and the incident status is escalated to <code>needs_human</code> so an engineer can inspect the situation.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">Can Agent Daemon fix infrastructure or database issues?</summary>
    <div class="accordion-body">
      <p>No. Auto-fix is confined to application source code (Python, JavaScript, TypeScript, Java, HTML and CSS). Database migrations, credentials, environment variables, network outages, and infrastructure errors are strictly escalated to human engineers.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How does the 1-day free trial work?</summary>
    <div class="accordion-body">
      <p>Every customer is eligible for one 1-day free trial. Submit a request on the <a href="/billing">Billing page</a>, and the Agent Daemon team of engineers will approve it promptly, activating 24 hours of unrestricted autonomous incident response.</p>
    </div>
  </details>

</div>

<section class="card mission-card" style="margin-top:40px;text-align:center">
  <h3>Have a Question Not Answered Here?</h3>
  <p class="muted">Check out our complete <a href="/help">Help Centre</a> or reach out to our team directly.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/contact">Contact Support</a>
    <a class="button" href="/help">Visit Help Centre</a>
  </div>
</section>"""


def privacy_policy_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Data Privacy &amp; Protection</div>
<h1>Privacy Policy</h1>
<p class="muted">Last updated: November 2026 &middot; Agent Daemon Security &amp; Compliance</p>
</section>

<section class="card" style="margin-top:36px;padding:32px;line-height:1.7;color:#d1c4df">
  <h3 style="color:var(--silver);margin-bottom:8px">1. Introduction</h3>
  <p>Agent Daemon ("we", "us", or "our"), operated by the Agent Daemon team of engineers, is committed to safeguarding the privacy and security of developers and organizations using our autonomous on-call monitoring and remediation platform.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">2. Information We Collect</h3>
  <ul>
    <li><b>Account Information:</b> When you sign in via Google OAuth, we receive your email address, display name, and unique Google subject identifier. We do not store Google passwords.</li>
    <li><b>GitHub Integration Data:</b> To interact with your repository, you provide a classic Personal Access Token. This token is encrypted at rest using AES-128 Fernet keys and is used solely to inspect source files for bug diagnosis and open fix pull requests.</li>
    <li><b>Application Telemetry &amp; Logs:</b> When an error occurs in your application, the monitoring client transmits the exception message, stack traceback, timestamp, service name, and execution environment.</li>
  </ul>

  <h3 style="color:var(--silver);margin:24px 0 8px">3. How We Use and Protect Source Code</h3>
  <p>Source files are read through GitHub's API as evidence for diagnosis. When our auto-fix engine is turned on for your project, a temporary copy of the repository is downloaded to a scratch folder so that a proposed fix can be built and tested in an isolated sandbox. The sandbox holds none of our keys, has limited memory, CPU and time, has network access only while dependencies install, and runs on a separate machine from our database. The temporary copy is deleted when the run ends. We do not use your code to train machine learning models, and fixes are only ever proposed as pull requests on a new branch.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">3a. Push checks</h3>
  <p>When push checks are on, GitHub tells us about every push to your tracked branch through a signed webhook. We download that commit into a temporary, isolated sandbox, install, build, test and start it, record the result (pass or fail, and the error output) and post a status on the commit. The copy is deleted after the run. You can switch push checks off per project at any time.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">4. Third-Party AI Providers</h3>
  <p>To diagnose and fix a bug, selected error logs, tracebacks and the relevant source files are sent to third-party AI providers: Groq for Low effort mode, Anthropic's Claude models for Normal, High and Extra modes, and OpenRouter where we route requests through it. Environment files and secret-looking content are excluded or redacted before anything is sent, but you should only connect repositories whose code you are allowed to share with these providers. The free Low effort tier may come with weaker privacy guarantees than paid provider tiers. Each provider handles data under its own terms, which we encourage you to read.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">5. Data Retention &amp; Deletion</h3>
  <p>You may delete any connected project at any time through your dashboard. Deletion permanently purges all stored incidents, decrypted tokens, and telemetry associated with that project. You may also revoke the GitHub Personal Access Token directly from GitHub at any time.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">6. Contact Information</h3>
  <p>If you have questions regarding your data privacy or would like to request data deletion, contact us through our <a href="/contact">Contact Page</a>.</p>
</section>"""


def terms_of_service_page_html() -> str:
    return f"""<section class="about-hero">
<div class="eyebrow">Terms &amp; Agreements</div>
<h1>Terms of Service</h1>
<p class="muted">Effective date: November 2026 &middot; Agent Daemon Platform Agreement</p>
</section>

<section class="card" style="margin-top:36px;padding:32px;line-height:1.7;color:#d1c4df">
  <h3 style="color:var(--silver);margin-bottom:8px">1. Acceptance of Terms</h3>
  <p>By accessing or using Agent Daemon (https://incident-agent-portal.onrender.com), you agree to be bound by these Terms of Service. If you are entering into this agreement on behalf of a company or legal entity, you represent that you have the authority to bind such entity.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">2. Autonomous Pull Requests &amp; Customer Responsibility</h3>
  <p>Agent Daemon provides autonomous error diagnosis and software patch synthesis. While our system implements strict AST validation, test suite gates, and confidence thresholds, <b>the customer retains ultimate responsibility for reviewing and validating any code pushed or merged into their production repositories</b>.</p>
  <p>In Automatic mode, Agent Daemon merges a pull request only when the fix is proven in our sandbox (the check that failed before now passes) and every GitHub check on the pull request reports success. We recommend keeping tests in every repository you connect: the more your tests cover, the more a green check means.</p>
  <p>Push checks: by connecting a repository you allow us to add a webhook to it and to post commit statuses ("Agent Daemon / push check") on the commits we test.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">3. Subscriptions &amp; Billing</h3>
  <ul>
    <li><b>Free Trial:</b> Limited to one 1-day free trial per customer, subject to approval by the Agent Daemon team of engineers.</li>
    <li><b>Paid Plans:</b> Paid access is available for &#8377;{plans.PLAN_PRICES["monthly"]:,} (30 days) and &#8377;{plans.PLAN_PRICES["yearly"]:,} (365 days). Payments made via Paytm UPI QR are activated upon administrative verification of the provided UTR reference.</li>
    <li><b>Monthly Fix Attempts:</b> Each paid plan includes {plans.quota_sentence()}. Quotas reset every month and do not roll over, including on the yearly plan. Extra attempts can be bought in a &#8377;{plans.PACK_PRICE} pack ({plans.PACK_HIGH_TRIES} High or {plans.PACK_EXTRA_TRIES} Extra attempts for the current month).</li>
    <li><b>Projects:</b> Every plan includes {plans.INCLUDED_PROJECTS} connected project. Each additional project is a one-time payment of &#8377;{plans.PROJECT_SLOT_PRICE} and the slot stays on your account.</li>
    <li><b>Attempts, Not Guarantees:</b> We sell attempts to fix a bug, not a guaranteed fix. Every fix is proposed as a pull request for your review.</li>
    <li><b>Renewal &amp; Expiry:</b> If a plan expires, project monitoring is safely paused without data loss until renewal.</li>
  </ul>

  <h3 style="color:var(--silver);margin:24px 0 8px">4. Acceptable Use</h3>
  <p>You agree not to use Agent Daemon to violate applicable laws, reverse engineer our proprietary diagnosis pipelines, or connect repositories containing malicious software.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">5. Limitation of Liability</h3>
  <p>In no event shall Agent Daemon, its engineering team, or contributors be liable for any indirect, incidental, or consequential damages resulting from downtime, software defects, or pull request merges.</p>
</section>"""


def render_header_nav_html(signed_in: bool = False, is_admin: bool = False, csrf_token: str = "") -> str:
    user_action = ""
    if signed_in:
        signout = (
            '<form method="post" action="/logout" style="display:inline">'
            f'<input type="hidden" name="csrf" value="{csrf_token}"><button class="button" type="submit">Sign out</button></form>'
        )
        if is_admin:
            user_action = ('<a href="/admin">Admin</a><a href="/admin/fix">Auto-fix</a>'
                           '<a href="/admin/architecture">Architecture</a>' + signout)
        else:
            user_action = ('<a href="/dashboard">Projects</a><a href="/usage">Usage</a>'
                           '<a href="/billing">Plan &amp; billing</a>' + signout)
    else:
        user_action = '<a class="button primary" href="/login">Sign in with Google</a>'

    return f"""<div class="nav-dropdown">
  <button class="nav-trigger" type="button" aria-haspopup="true">Product</button>
  <div class="nav-menu">
    <a href="/how-it-works">How it works</a>
    <a href="/features">Features</a>
    <a href="/pricing">Pricing</a>
    <a href="/docs">Documentation</a>
    <a href="/changelog">Changelog</a>
  </div>
</div>
<div class="nav-dropdown">
  <button class="nav-trigger" type="button" aria-haspopup="true">Company</button>
  <div class="nav-menu">
    <a href="/about">About Us</a>
    <a href="/contact">Contact Us</a>
  </div>
</div>
<div class="nav-dropdown">
  <button class="nav-trigger" type="button" aria-haspopup="true">Resources</button>
  <div class="nav-menu">
    <a href="/faq">FAQ</a>
    <a href="/help">Help Center</a>
  </div>
</div>
<div class="nav-dropdown">
  <button class="nav-trigger" type="button" aria-haspopup="true">Legal</button>
  <div class="nav-menu">
    <a href="/privacy">Privacy Policy</a>
    <a href="/terms">Terms of Service</a>
  </div>
</div>
{user_action}"""
