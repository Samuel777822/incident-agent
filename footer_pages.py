"""Footer navigation and standalone pages for Agent Daemon:
- Product: Features (/features), Pricing (/pricing), Documentation (/docs), Changelog (/changelog)
- Company: About Us (/about), Contact Us (/contact)
- Resources: FAQ (/faq), Help Center (/help)
- Legal: Privacy Policy (/privacy), Terms of Service (/terms)
"""

from __future__ import annotations
import os


def render_footer_html() -> str:
    return """<footer class="wrap footer">
  <div class="footer-grid">
    <div class="footer-col">
      <div class="footer-heading">Product</div>
      <ul class="footer-links">
        <li><a href="#how-it-works">How It Works</a></li>
        <li><a href="/features">Features</a></li>
        <li><a href="#security">Security</a></li>
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
        <li><a href="/support">Support</a></li>
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
  <div class="footer-bottom">
    <div class="footer-brand-line">
      <span class="brand"><span class="brand-mark">A</span>Agent Daemon</span>
      <span class="muted">· Autonomous AI on-call engineer for Python services.</span>
    </div>
    <div class="muted" style="font-size:13px">
      &copy; 2026 Agent Daemon · By Abhay Samuel H &amp; Pranav V Rao · Built for resilient engineering teams.
    </div>
  </div>
</footer>"""


def features_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Platform Capabilities</div>
<h1>Autonomous Incident Response for Python Services</h1>
<p>From unhandled production tracebacks to verified, auto-merged GitHub pull requests in under 3 minutes.</p>
</section>

<section class="grid" style="margin-top:28px">
  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#128065;&#65039;</div>
    <h3>24/7 Production Sentinel</h3>
    <p class="muted">Lightweight monitoring client captures unhandled exceptions, logged errors, and sends short 5-minute heartbeats without slowing your web responses.</p>
  </article>
  
  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#129504;</div>
    <h3>Intelligent Incident Clustering</h3>
    <p class="muted">High-frequency error cascades are deduplicated and grouped into singular, actionable incidents with an automated timeline and severity score.</p>
  </article>

  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#128300;</div>
    <h3>Groq LLM Root-Cause Analysis</h3>
    <p class="muted">Analyzes tracebacks, inspects recent git commits, and pinpoints the exact culprit line of code within seconds.</p>
  </article>

  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#129690;</div>
    <h3>Surgical AST-Validated Patching</h3>
    <p class="muted">Generates targeted find-and-replace patches that parse cleanly with Python's Abstract Syntax Tree. Never runs customer code on our servers.</p>
  </article>

  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#9881;&#65039;</div>
    <h3>CI-Gated Autonomous Merging</h3>
    <p class="muted">In Auto mode, Agent Daemon opens a PR and waits for your GitHub Actions CI tests to pass. If green, it auto-squashes and merges to production.</p>
  </article>

  <article class="card">
    <div style="font-size:24px;margin-bottom:8px">&#128272;</div>
    <h3>Multi-Tenant Zero-Trust Security</h3>
    <p class="muted">Personal Access Tokens are encrypted with AES-128 Fernet keys. Public repositories are locked to PR-only mode to prevent arbitrary error spam.</p>
  </article>
</section>

<section class="card mission-card" style="margin-top:40px;text-align:center">
  <h3>Ready to Automate Your On-Call?</h3>
  <p>Test on your staging or production repository in 60 seconds. One pull request installs monitoring.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/login">Continue with Google</a>
    <a class="button" href="/help">Watch Video Demo</a>
    <a class="button" href="/pricing">View Plans</a>
  </div>
</section>"""


def pricing_page_html(signed_in: bool = False) -> str:
    cta_href = "/billing" if signed_in else "/login"
    cta_text = "Go to Billing &amp; Plans" if signed_in else "Sign in to Subscribe"
    return f"""<section class="about-hero">
<div class="eyebrow">Simple &amp; Transparent Plans</div>
<h1>Predictable Pricing for High-Reliability Teams</h1>
<p>Start with a full-featured 1-day free trial. Upgrade to monthly or annual billing whenever you're ready.</p>
</section>

<div class="modes-grid" style="margin-top:36px">
  <article class="mode-card" style="border-color:#3a2338">
    <div style="margin-bottom:12px"><span class="badge-tag setup">Evaluation</span></div>
    <h3 style="font-size:22px;margin:0 0 4px">1-Day Free Trial</h3>
    <div style="font-size:28px;font-weight:700;color:var(--text);margin:14px 0">&#8377;0</div>
    <p class="muted" style="margin-bottom:20px">Test the full autonomous pipeline on your own repository with no commitment.</p>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px;margin-bottom:24px">
      <li>Full access to Automatic, PR-only &amp; Report modes</li>
      <li>Instant error ingestion &amp; Groq AI diagnosis</li>
      <li>Approved directly by founders within 1-2 hours</li>
    </ul>
    <a class="button" style="width:100%;text-align:center" href="{cta_href}">Request Free Trial</a>
  </article>

  <article class="mode-card" style="border-color:var(--crimson);box-shadow:0 0 24px #e11d2a33">
    <div style="margin-bottom:12px"><span class="badge-tag bug" style="background:#45141b;color:#ff8a7a">Most Popular</span></div>
    <h3 style="font-size:22px;margin:0 0 4px">Monthly Plan</h3>
    <div style="font-size:28px;font-weight:700;color:var(--text);margin:14px 0">&#8377;100 <span style="font-size:14px;color:var(--muted)">/ 30 days</span></div>
    <p class="muted" style="margin-bottom:20px">Continuous 24/7 AI on-call coverage for active repositories and fast-shipping teams.</p>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px;margin-bottom:24px">
      <li>Unlimited error ingestion &amp; heartbeat telemetry</li>
      <li>Automated CI-verified fix pull requests</li>
      <li>Fast Paytm UPI QR activation with UTR confirmation</li>
    </ul>
    <a class="button primary" style="width:100%;text-align:center" href="{cta_href}">{cta_text}</a>
  </article>

  <article class="mode-card" style="border-color:var(--violet);box-shadow:0 0 24px #9a4dff33">
    <div style="margin-bottom:12px"><span class="badge-tag git" style="background:#231a3b;color:#b98aff">Best Value &middot; Save &#8377;200</span></div>
    <h3 style="font-size:22px;margin:0 0 4px">Annual Plan</h3>
    <div style="font-size:28px;font-weight:700;color:var(--text);margin:14px 0">&#8377;1,000 <span style="font-size:14px;color:var(--muted)">/ 365 days</span></div>
    <p class="muted" style="margin-bottom:20px">Year-round production safety net for startups and small engineering squads.</p>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px;margin-bottom:24px">
      <li>Everything in Monthly with 365 days of coverage</li>
      <li>Priority worker diagnosis queue</li>
      <li>Direct Slack / WhatsApp founder escalation access</li>
    </ul>
    <a class="button primary" style="width:100%;text-align:center" href="{cta_href}">{cta_text}</a>
  </article>
</div>

<section class="card" style="margin-top:36px;padding:26px">
  <h3 style="margin-bottom:12px">Payment Methods &amp; Activation</h3>
  <p class="muted" style="line-height:1.6">We support instant UPI QR payments (Paytm, Google Pay, PhonePe, and BHIM). When you transfer with your UPI app, enter your 12-digit UTR reference on the portal. Our administrators confirm the transaction and unlock your access promptly. Razorpay card &amp; net banking integration is also supported.</p>
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
      <h3 style="margin:0;color:var(--silver)">v1.3 &mdash; Help Centre &amp; Troubleshooting Knowledge Base</h3>
      <span class="pill green">Latest Release &middot; Nov 2026</span>
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
      <h3 style="margin:0;color:var(--silver)">v1.2 &mdash; Direct Support &amp; Founder Alerts</h3>
      <span class="pill">Oct 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Contact Us Page (/contact):</b> Dedicated inquiry form with guest submission capability and CSRF protection.</li>
      <li><b>Founder Instant Alerts:</b> Automated Brevo/Resend HTTPS notifications dispatching to Abhay &amp; Pranav upon form submission.</li>
      <li><b>Admin Inquiries Console:</b> Manage incoming support queries with one-click email reply links.</li>
    </ul>
  </article>

  <article class="card" style="margin-bottom:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="margin:0;color:var(--silver)">v1.1 &mdash; AI Assistant &amp; Live Founder Chat</h3>
      <span class="pill">Oct 2026</span>
    </div>
    <ul style="color:#d1c4df;font-size:14px;line-height:1.7;padding-left:18px">
      <li><b>Groq LLM Chatbot:</b> Embedded dark-mode conversational assistant answering visitor queries about features, pricing, and architecture.</li>
      <li><b>Admin Chat Console:</b> Live multi-tab messaging drawer for founders to take over chat sessions in real time.</li>
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
    return """<section class="about-hero">
<div class="eyebrow">Frequently Asked Questions</div>
<h1>Everything You Need to Know</h1>
<p>Clear answers to common questions about permissions, security, autonomous pull requests, and pricing.</p>
</section>

<div class="accordion-group" style="margin-top:36px">

  <details class="accordion-item" open>
    <summary class="accordion-summary">Does Agent Daemon execute my proprietary code on its servers?</summary>
    <div class="accordion-body">
      <p><b>No.</b> Agent Daemon only reads source code files as text evidence via GitHub API to diagnose problems and construct minimal AST-checked diffs. Customer code and test suites are never executed on Agent Daemon servers. Tests are executed solely inside your own GitHub Actions runners.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How does the Automatic (`auto`) remediation mode work?</summary>
    <div class="accordion-body">
      <p>When an error occurs, Agent Daemon diagnoses the cause, generates an AST-validated patch, opens a pull request on GitHub, and monitors your GitHub Actions test suite. If all CI checks pass, it automatically squash-merges the PR to production. This mode is restricted to private repositories for security.</p>
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
      <p>No. Auto-fix is strictly confined to Python source code bugs. Database migrations, credentials, environment variables, network outages, and infrastructure errors are strictly escalated to human engineers.</p>
    </div>
  </details>

  <details class="accordion-item">
    <summary class="accordion-summary">How does the 1-day free trial work?</summary>
    <div class="accordion-body">
      <p>Every customer is eligible for one 1-day free trial. Submit a request on the <a href="/billing">Billing page</a>, and our founders (Abhay &amp; Pranav) will approve it promptly, activating 24 hours of unrestricted autonomous incident response.</p>
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
  <p>Agent Daemon ("we", "us", or "our"), operated by founders Abhay Samuel H and Pranav V Rao, is committed to safeguarding the privacy and security of developers and organizations using our autonomous on-call monitoring and remediation platform.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">2. Information We Collect</h3>
  <ul>
    <li><b>Account Information:</b> When you sign in via Google OAuth, we receive your email address, display name, and unique Google subject identifier. We do not store Google passwords.</li>
    <li><b>GitHub Integration Data:</b> To interact with your repository, you provide a classic Personal Access Token. This token is encrypted at rest using AES-128 Fernet keys and is used solely to inspect source files for bug diagnosis and open fix pull requests.</li>
    <li><b>Application Telemetry &amp; Logs:</b> When an error occurs in your application, the monitoring client transmits the exception message, stack traceback, timestamp, service name, and execution environment.</li>
  </ul>

  <h3 style="color:var(--silver);margin:24px 0 8px">3. How We Use and Protect Source Code</h3>
  <p><b>We never clone or execute your proprietary code on our servers.</b> Source files are accessed transiently via GitHub's API solely as text evidence to enable LLM root cause analysis and construct minimal AST diffs. Customer code is never used to train generalized machine learning models.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">4. Data Retention &amp; Deletion</h3>
  <p>You may delete any connected project at any time through your dashboard. Deletion permanently purges all stored incidents, decrypted tokens, and telemetry associated with that project. You may also revoke the GitHub Personal Access Token directly from GitHub at any time.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">5. Contact Information</h3>
  <p>If you have questions regarding your data privacy or would like to request data deletion, contact us at <a href="mailto:pranavvrao1@gmail.com">pranavvrao1@gmail.com</a> or through our <a href="/contact">Contact Page</a>.</p>
</section>"""


def terms_of_service_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Terms &amp; Agreements</div>
<h1>Terms of Service</h1>
<p class="muted">Effective date: November 2026 &middot; Agent Daemon Platform Agreement</p>
</section>

<section class="card" style="margin-top:36px;padding:32px;line-height:1.7;color:#d1c4df">
  <h3 style="color:var(--silver);margin-bottom:8px">1. Acceptance of Terms</h3>
  <p>By accessing or using Agent Daemon (https://incident-agent-portal.onrender.com), you agree to be bound by these Terms of Service. If you are entering into this agreement on behalf of a company or legal entity, you represent that you have the authority to bind such entity.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">2. Autonomous Pull Requests &amp; Customer Responsibility</h3>
  <p>Agent Daemon provides autonomous error diagnosis and software patch synthesis. While our system implements strict AST validation, test suite gates, and confidence thresholds, <b>the customer retains ultimate responsibility for reviewing and validating any code pushed or merged into their production repositories</b>.</p>
  <p>In Automatic mode, Agent Daemon will only merge pull requests if your repository's automated CI checks report success. We recommend maintaining comprehensive unit and integration test coverage on all repositories connected to Agent Daemon.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">3. Subscriptions &amp; Billing</h3>
  <ul>
    <li><b>Free Trial:</b> Limited to one 1-day free trial per customer, subject to founder approval.</li>
    <li><b>Paid Plans:</b> Paid access is available for &#8377;100 (30 days) and &#8377;1,000 (365 days). Payments made via Paytm UPI QR are activated upon administrative verification of the provided UTR reference.</li>
    <li><b>Renewal &amp; Expiry:</b> If a plan expires, project monitoring is safely paused without data loss until renewal.</li>
  </ul>

  <h3 style="color:var(--silver);margin:24px 0 8px">4. Acceptable Use</h3>
  <p>You agree not to use Agent Daemon to violate applicable laws, reverse engineer our proprietary diagnosis pipelines, or connect repositories containing malicious software.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">5. Limitation of Liability</h3>
  <p>In no event shall Agent Daemon, its founders, or contributors be liable for any indirect, incidental, or consequential damages resulting from downtime, software defects, or pull request merges.</p>
</section>"""


def render_header_nav_html(signed_in: bool = False, is_admin: bool = False, csrf_token: str = "") -> str:
    user_action = ""
    if signed_in:
        signout = (
            '<form method="post" action="/logout" style="display:inline">'
            f'<input type="hidden" name="csrf" value="{csrf_token}"><button class="button" type="submit">Sign out</button></form>'
        )
        if is_admin:
            user_action = '<a href="/admin">Admin</a>' + signout
        else:
            user_action = '<a href="/dashboard">Projects</a><a href="/billing">Plan &amp; billing</a>' + signout
    else:
        user_action = '<a class="button primary" href="/login">Sign in with Google</a>'

    return f"""<div class="nav-dropdown">
  <button class="nav-trigger" type="button" aria-haspopup="true">Product</button>
  <div class="nav-menu">
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
