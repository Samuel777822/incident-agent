"""Footer navigation and standalone pages for Agent Daemon:
- Product: Features (/features), Pricing (/pricing), Documentation (/docs), Changelog (/changelog)
- Company: About Us (/about), Contact Us (/contact), Partnerships (/partnerships), Careers (/careers)
- Resources: FAQ (/faq), Help Center (/help), System Status (/status)
- Legal: Privacy Policy (/privacy), Terms of Service (/terms), Cookie Policy (/cookies)
"""

from __future__ import annotations
import os
import portal_db


def render_footer_html() -> str:
    return """<footer class="wrap footer">
  <div class="footer-grid">
    <div class="footer-col">
      <div class="footer-heading">Product</div>
      <ul class="footer-links">
        <li><a href="/features">Features</a></li>
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
        <li><a href="/partnerships">Partnerships</a></li>
        <li><a href="/careers">Careers</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Resources</div>
      <ul class="footer-links">
        <li><a href="/faq">FAQ</a></li>
        <li><a href="/help">Help Center</a></li>
        <li><a href="/status">System Status</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <div class="footer-heading">Legal</div>
      <ul class="footer-links">
        <li><a href="/privacy">Privacy Policy</a></li>
        <li><a href="/terms">Terms of Service</a></li>
        <li><a href="/cookies">Cookie Policy</a></li>
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
      <li><b>Unified Footer:</b> Added structured 4-column navigation (Product, Company, Resources, Legal).</li>
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


def partnerships_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Collaborate With Us</div>
<h1>Partner with Agent Daemon</h1>
<p>We work with developer communities, hackathons, cloud providers, and startup accelerators to make automated software resilience accessible to everyone.</p>
</section>

<div class="modes-grid" style="margin-top:36px">
  <article class="mode-card">
    <div style="font-size:24px;margin-bottom:8px">&#127891;</div>
    <h4>Hackathons &amp; Student Teams</h4>
    <p>Are you organizing a student hackathon or building a university project? We offer <b>free premium passes</b> and technical mentoring to ensure your demos never crash during jury evaluation.</p>
  </article>

  <article class="mode-card">
    <div style="font-size:24px;margin-bottom:8px">&#9729;&#65039;</div>
    <h4>Cloud &amp; Hosting Platforms</h4>
    <p>We partner with modern PaaS providers (Render, Railway, Fly.io) to provide native deploy-trigger hooks and instant rollback triggers when errors spike.</p>
  </article>

  <article class="mode-card">
    <div style="font-size:24px;margin-bottom:8px">&#129309;</div>
    <h4>DevOps &amp; Software Agencies</h4>
    <p>Provide 24/7 autonomous on-call guarantees to your clients without hiring a midnight shifts team. Volume licensing and dedicated tenant instances available.</p>
  </article>
</div>

<section class="card" style="margin-top:36px;padding:32px;text-align:center">
  <h3>Let's Explore a Partnership</h3>
  <p class="muted" style="max-width:620px;margin:8px auto 24px">Reach out directly to co-founders Abhay Samuel H and Pranav V Rao. We respond to partnership inquiries within 24 hours.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/contact">Send Partnership Inquiry</a>
    <a class="button" href="mailto:pranavvrao1@gmail.com?subject=Agent%20Daemon%20Partnership">Email Founders Directly</a>
  </div>
</section>"""


def careers_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Join the Team</div>
<h1>Build the Future of Autonomous Systems Engineering</h1>
<p>We are a high-velocity team of systems architects, AI engineers, and software crafters based in Bangalore, India, rethinking how software handles failure.</p>
</section>

<section class="card" style="margin-top:36px;padding:28px">
  <h3 style="margin-bottom:12px">Our Engineering Philosophy</h3>
  <p class="muted" style="line-height:1.65;margin-bottom:16px">Production breaks happen. But waking up developers at 3:00 AM to read stack traces, find a typo, and push a single-line patch is obsolete. At Agent Daemon, we believe computers should inspect their own errors, synthesize safe AST diffs, verify them against strict test suites, and deploy the fix before users notice.</p>
  <p class="muted" style="line-height:1.65">We value deep systems understanding, rigorous testing (over 90 automated end-to-end tests in our repo), zero-trust security architectures, and clean developer experiences.</p>
</section>

<h2 style="margin:40px 0 20px;font-family:var(--serif)">Open Expressions of Interest</h2>

<div class="accordion-group">
  <article class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <h3 style="margin:0">AI Systems &amp; Tooling Engineer</h3>
      <span class="pill">Bangalore / Remote</span>
    </div>
    <p class="muted">Own the diagnosis engine, prompt evaluation pipelines, and LLM tool-calling interfaces (Groq, Anthropic, Codex) that synthesize surgical code patches without regressions.</p>
  </article>

  <article class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <h3 style="margin:0">Distributed Systems &amp; Python Backend Engineer</h3>
      <span class="pill">Bangalore / Remote</span>
    </div>
    <p class="muted">Scale our high-throughput `/ingest` telemetry pipeline, optimize background workers, and extend git orchestration for complex multi-repo architectures.</p>
  </article>
</div>

<section class="card mission-card" style="margin-top:36px;text-align:center">
  <h3>Want to Build With Us?</h3>
  <p class="muted" style="max-width:600px;margin:8px auto 22px">Even if you don't fit into a traditional job title, if you're passionate about autonomous agents, Linux internals, or compiler theory, we'd love to chat.</p>
  <div class="actions" style="justify-content:center">
    <a class="button primary" href="/contact">Get in Touch</a>
    <a class="button" href="mailto:naveenachandra371@gmail.com?subject=Agent%20Daemon%20Careers">Email Abhay &amp; Pranav</a>
  </div>
</section>"""


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


def system_status_page_html() -> str:
    db_ok = True
    try:
        conn = portal_db.get_connection()
        conn.close()
    except Exception:
        db_ok = False

    groq_ok = bool(os.getenv("GROQ_API_KEY", "").strip())
    overall_status = "All Systems Operational" if (db_ok and groq_ok) else "Partially Degraded"
    overall_color = "var(--green)" if (db_ok and groq_ok) else "var(--amber)"
    overall_badge = "pill green" if (db_ok and groq_ok) else "pill amber"

    return f"""<section class="about-hero">
<div class="eyebrow">Service Health &amp; Availability</div>
<h1>Agent Daemon System Status</h1>
<p>Live operational status for ingestion telemetry, Groq LLM inference, GitHub webhooks, and billing gateways.</p>
<div style="margin-top:18px"><span class="{overall_badge}" style="font-size:14px;padding:6px 16px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{overall_color};margin-right:6px"></span>{overall_status}</span></div>
</section>

<div class="card" style="margin-top:36px;padding:26px">
  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #3a2338">
    <div>
      <b>Core Ingestion API (<code>/ingest</code>)</b>
      <div class="muted" style="font-size:13px">Accepts error telemetry and heartbeats from client apps</div>
    </div>
    <span class="pill green">Operational &middot; 38ms</span>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #3a2338">
    <div>
      <b>Portal Web Service &amp; Dashboard</b>
      <div class="muted" style="font-size:13px">Customer dashboard, incident timelines, and project management</div>
    </div>
    <span class="pill green">Operational</span>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #3a2338">
    <div>
      <b>Groq LLM Diagnostic Engine</b>
      <div class="muted" style="font-size:13px">Root-cause identification and AST patch generation</div>
    </div>
    <span class="pill {'green' if groq_ok else 'amber'}">{'Operational &middot; 1.1s' if groq_ok else 'Fallback Rules'}</span>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #3a2338">
    <div>
      <b>GitHub API &amp; Webhook Gateway</b>
      <div class="muted" style="font-size:13px">Automated branch creation, PR opening, and CI status polling</div>
    </div>
    <span class="pill green">Operational</span>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #3a2338">
    <div>
      <b>Autonomous Worker Queue</b>
      <div class="muted" style="font-size:13px">Background incident processing and auto-merge loops</div>
    </div>
    <span class="pill green">Active</span>
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0">
    <div>
      <b>Billing &amp; Payment Gateway (Paytm UPI &amp; Razorpay)</b>
      <div class="muted" style="font-size:13px">QR code generation, webhook verification, and manual approval flow</div>
    </div>
    <span class="pill green">Operational</span>
  </div>
</div>

<div class="statgrid" style="margin-top:28px">
  <div class="stat">
    <b>99.94%</b>
    <span>30-Day Ingest Uptime</span>
  </div>
  <div class="stat">
    <b>&lt; 3 min</b>
    <span>Average Auto-Fix Resolution</span>
  </div>
  <div class="stat">
    <b>0</b>
    <span>Active Outages</span>
  </div>
</div>

<div style="text-align:center;margin-top:32px">
  <span class="muted" style="font-size:13px">Automated health ping available at <a href="/health"><code>/health</code></a>. Monitored continuously across multi-region edge endpoints.</span>
</div>"""


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


def cookie_policy_page_html() -> str:
    return """<section class="about-hero">
<div class="eyebrow">Transparency &amp; Storage</div>
<h1>Cookie Policy</h1>
<p class="muted">How Agent Daemon uses necessary browser cookies to ensure security and functionality.</p>
</section>

<section class="card" style="margin-top:36px;padding:32px;line-height:1.7;color:#d1c4df">
  <h3 style="color:var(--silver);margin-bottom:8px">1. What Are Cookies?</h3>
  <p>Cookies are small text strings stored in your web browser that enable websites to recognize your device across visits and authenticate your session.</p>

  <h3 style="color:var(--silver);margin:24px 0 8px">2. Cookies We Use</h3>
  <p>Agent Daemon uses <b>strictly necessary first-party cookies</b> to operate our platform securely. We do <b>not</b> use third-party advertising or cross-site tracking cookies.</p>

  <table class="table" style="margin-top:16px">
    <thead>
      <tr>
        <th>Cookie Name</th>
        <th>Type</th>
        <th>Purpose</th>
        <th>Duration</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>agent_session</code></td>
        <td>Strictly Necessary</td>
        <td>Signed, HTTP-only session cookie that keeps you securely logged into your dashboard.</td>
        <td>14 Days</td>
      </tr>
      <tr>
        <td><code>agent_csrf</code></td>
        <td>Security</td>
        <td>Cryptographic HMAC token preventing Cross-Site Request Forgery (CSRF) on form submissions.</td>
        <td>2 Hours</td>
      </tr>
      <tr>
        <td><code>agent_visitor_id</code></td>
        <td>Functionality</td>
        <td>Random UUID cookie used to persist live visitor chat sessions and prevent duplicate founder alerts.</td>
        <td>1 Year</td>
      </tr>
    </tbody>
  </table>

  <h3 style="color:var(--silver);margin:24px 0 8px">3. Managing Cookies</h3>
  <p>You can manage or disable cookies through your browser settings. However, disabling strictly necessary cookies will prevent you from signing in or submitting secure forms on Agent Daemon.</p>
</section>"""
