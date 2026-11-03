"""AI Knowledge Base & Chatbot Engine for Agent Daemon.

Answers visitor questions with high accuracy using Groq LLM (when configured)
and robust deterministic responses covering all aspects of Agent Daemon.
"""

from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

DAEMON_KNOWLEDGE = """
=== ABOUT AGENT DAEMON ===
Product: Agent Daemon (hosted at https://incident-agent-portal.onrender.com)
Tagline: When production breaks, get to the cause faster. AI incident response for Python services.

FOUNDERS:
1. Abhay Samuel H - Co-Founder & CTO. Computer Science Engineering student at BMSCE, Bangalore. Built the monitoring client, incident pipeline, automated fix PRs, and the customer/admin portal. Email: naveenachandra371@gmail.com, GitHub: https://github.com/Samuel777822.
2. Pranav V Rao - Co-Founder & Systems Architect. AI & ML Engineering student. Architected backend infrastructure, Codex integration, uptime monitoring, autonomous worker agent, and Render deployments. Email: pranavvrao1@gmail.com, GitHub: https://github.com/pranavvrao1-ai.
Project Repository: https://github.com/Samuel777822/incident-agent

HOW IT WORKS:
1. Sign in with Google (OAuth2, passwordless).
2. Choose a plan or request a free trial (approved by founders).
3. Connect your GitHub repository using a classic personal access token with 'repo' and 'workflow' scopes.
4. Agent Daemon automatically opens one pull request adding zero-touch monitoring (incident_agent_monitor.py, app entry file import, and incident_agent_config.json) and merges it if allowed.
5. In production, unhandled exceptions and error logs are shipped to the portal, deduplicated, grouped into incidents, diagnosed by an LLM, and a reviewable pull request with a fix is opened.
6. Execution modes:
   - Report only: creates incident report with root cause analysis.
   - Pull request (default): diagnoses and opens a pull request with the fix.
   - Auto: opens PR and merges automatically ONLY IF GitHub checks pass on private repos.

PRICING & PLANS:
- Free Trial: 1 day of full access upon admin approval.
- Paid Monthly: ₹100 for 30 days.
- Paid Yearly: ₹1,000 for 365 days.
- Payment method: Instant Paytm UPI QR with admin UTR confirmation.

HELP CENTRE, DEMO & TROUBLESHOOTING:
- Help Centre URL: /help (also /docs, /help-center, /troubleshooting).
- Video Demo & Walkthrough: https://www.youtube.com/watch?v=Y3neE_B2d-M (shows autonomous detection, diagnosis, fix PR, and auto-merge on a live coffee shop API).
- Guides include: GitHub token setup (repo & workflow scopes), zero-touch installer, manual integration for Flask, FastAPI, Django, and WSGI.
- Troubleshooting playbooks: solving 'Offline' status, GitHub API 401/403/404 errors, auto-fix 'needs_human' safety gates, CI check auto-merge rules, and Render idle sleep.

CONTACT & LIVE SUPPORT:
Founders are available directly via this chat, our Contact form at /contact, or by email:
- pranavvrao1@gmail.com
- naveenachandra371@gmail.com
"""

SYSTEM_PROMPT = f"""You are the friendly, helpful AI Assistant for Agent Daemon.
You answer questions from prospective customers and users who visit the website.

KNOWLEDGE BASE:
{DAEMON_KNOWLEDGE}

GUIDELINES:
1. Be concise, warm, professional, and accurate.
2. Help users understand how Agent Daemon solves production errors, how easy it is to install, and how pricing works.
3. If they want to talk to the founders, assure them that Abhay and Pranav will see their messages right here in the chat and by email, and encourage them to leave their name or email address.
4. Keep replies within 2-4 sentences or short bullet points unless more detail is specifically requested.
5. Do not invent features or make up technical guarantees outside the knowledge base.
"""


def answer_visitor_query(user_text: str, history: list[dict] | None = None) -> str:
    """Answers visitor questions using Groq or falls back to built-in knowledge matching."""
    text_lower = user_text.lower().strip()

    # Try Groq if configured
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if history:
                for h in history[-4:]:
                    role = "assistant" if h.get("sender") in ("bot", "admin") else "user"
                    messages.append({"role": role, "content": h.get("text", "")})
            messages.append({"role": "user", "content": user_text})

            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0.3,
                max_tokens=400,
            )
            ans = response.choices[0].message.content.strip()
            if ans:
                if any(k in text_lower for k in ("troubleshoot", "offline", "guide", "docs", "help")) and "/help" not in ans:
                    ans += "\n\nFor more detailed step-by-step troubleshooting playbooks and demo videos, check out our Help Centre at /help."
                return ans
        except Exception as e:
            log.warning("Groq chatbot call failed: %s; using deterministic fallback", e)

    # Deterministic fallback responses
    if any(k in text_lower for k in ("help", "guide", "doc", "troubleshoot", "demo", "video", "offline", "tutorial", "how to")):
        return (
            "You can find complete setup guides, troubleshooting playbooks, and our full video walkthrough demo "
            "in our Help Centre at /help! You can also view our contact page at /contact to reach our founders directly."
        )

    if any(k in text_lower for k in ("price", "cost", "plan", "free", "trial", "payment", "pay", "upi")):
        return (
            "Agent Daemon offers a 1-day free trial so you can test it on your repository. "
            "Our paid plans are ₹100 for 30 days or ₹1,000 for a full year, with simple UPI payments. "
            "Would you like help getting started?"
        )

    if any(k in text_lower for k in ("founder", "team", "who built", "who are you", "abhay", "pranav")):
        return (
            "Agent Daemon is built by two co-founders: Abhay Samuel H (Co-Founder & CTO) and Pranav V Rao (Co-Founder & Systems Architect). "
            "They designed it to give developer teams 24/7 AI incident response without on-call burnout. "
            "Feel free to drop your questions or contact details here—they read incoming messages!"
        )

    if any(k in text_lower for k in ("how does it work", "how it works", "what is", "features", "python", "github")):
        return (
            "Agent Daemon watches the error logs of your Python app, groups repeated failures into incidents, "
            "explains the root cause with an LLM, and opens a pull request with a verified fix for you to review. "
            "Installation takes just 1 minute by connecting your GitHub repository."
        )

    if any(k in text_lower for k in ("contact", "email", "talk", "human", "support", "online", "hello", "hi", "hey")):
        return (
            "Hello! I am the Agent Daemon assistant. You can chat with our team right here! "
            "If our founders (Abhay & Pranav) are currently away, leave your message or email and they will follow up shortly."
        )

    return (
        "Agent Daemon monitors your Python app's error logs, groups incidents, diagnoses the root cause, and opens pull requests with fixes. "
        "Can I answer any questions about setup, GitHub permissions, pricing, or our team?"
    )
