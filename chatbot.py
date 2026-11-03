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

TEAM:
Agent Daemon is built and maintained by the Agent Daemon team of engineers.
Project Repository: https://github.com/Samuel777822/incident-agent

HOW IT WORKS:
1. Sign in with Google (OAuth2, passwordless).
2. Choose a plan or request a free trial (approved by the engineering team).
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
The Agent Daemon team of engineers is available directly via this chat or our Contact form at /contact.
"""

SYSTEM_PROMPT = f"""You are the friendly, helpful AI Assistant for Agent Daemon.
You answer questions from prospective customers and users who visit the website.

KNOWLEDGE BASE:
{DAEMON_KNOWLEDGE}

CRITICAL PRIVACY DIRECTIVES (MANDATORY):
- NEVER mention any personal names (such as Abhay, Pranav, Samuel, Rao) under ANY circumstances.
- NEVER disclose personal email addresses (such as naveenachandra371@gmail.com, pranavvrao1@gmail.com, or any @gmail.com address).
- When asked "Who are the founders?", "Who made this?", "Who built this?", or about the creators, ALWAYS state that Agent Daemon is created and operated by the "Agent Daemon team of engineers".
- For contact, ALWAYS refer visitors to this live chat or the Contact form at /contact.

GUIDELINES:
1. Be concise, warm, professional, and accurate.
2. Help users understand how Agent Daemon solves production errors, how easy it is to install, and how pricing works.
3. If they want to talk to the team, assure them that the Agent Daemon team of engineers will see their messages right here in the chat, and encourage them to leave their name or contact details.
4. Keep replies within 2-4 sentences or short bullet points unless more detail is specifically requested.
5. Do not invent features or make up technical guarantees outside the knowledge base.
"""


def sanitize_chat_text(text: str) -> str:
    """Strictly scrubs any personal names and personal email IDs from chat text."""
    if not text:
        return ""

    # If the message is the legacy founder introduction, replace it cleanly
    if any(k in text.lower() for k in ("abhay", "pranav", "naveenachandra")):
        if any(f in text.lower() for f in ("created by", "co-founder", "students", "founders")):
            return (
                "Agent Daemon is built and maintained by the Agent Daemon team of engineers. "
                "Our team designed it to give developer teams 24/7 AI incident response without on-call burnout. "
                "You can reach our team directly right here in this chat or through our contact form at /contact."
            )

    # Strip personal email addresses
    text = re.sub(r'[\w.+-]+@gmail\.com', 'support through /contact', text, flags=re.I)
    text = re.sub(r'naveenachandra371@\S+', 'support through /contact', text, flags=re.I)
    text = re.sub(r'pranavvrao1@\S+', 'support through /contact', text, flags=re.I)

    # Strip student bios or personal university references
    text = re.sub(r'Both are students[^\n.]*\.?', '', text, flags=re.I)
    text = re.sub(r'Abhay studies[^\n.]*\.?', '', text, flags=re.I)
    text = re.sub(r'Pranav studies[^\n.]*\.?', '', text, flags=re.I)

    # Strip and replace personal names
    text = re.sub(r'\*?\*?Abhay Samuel H\*?\*?', 'the Agent Daemon team of engineers', text, flags=re.I)
    text = re.sub(r'\*?\*?Pranav V Rao\*?\*?', 'the Agent Daemon team of engineers', text, flags=re.I)
    text = re.sub(r'\bAbhay\s*(?:and|&)\s*Pranav\b', 'the Agent Daemon team of engineers', text, flags=re.I)
    text = re.sub(r'\bAbhay\b', 'the Agent Daemon team', text, flags=re.I)
    text = re.sub(r'\bPranav\b', 'the Agent Daemon team', text, flags=re.I)

    # Clean up any awkward phrasing resulting from replacements
    text = re.sub(r'(?:the Agent Daemon team of engineers\s*(?:and|,)\s*)+the Agent Daemon team of engineers', 'the Agent Daemon team of engineers', text, flags=re.I)
    return text.strip()


def answer_visitor_query(user_text: str, history: list[dict] | None = None) -> str:
    """Answers visitor questions using Groq or falls back to built-in knowledge matching."""
    text_lower = user_text.lower().strip()

    # Immediate deterministic intercept for founder/team/creator inquiries to guarantee privacy
    if any(k in text_lower for k in ("founder", "founders", "team", "who built", "who made", "who created", "who is the creator", "creator", "creators", "author", "authors", "who are you", "abhay", "pranav")):
        return (
            "Agent Daemon is built and maintained by the Agent Daemon team of engineers. "
            "They designed it to give developer teams 24/7 AI incident response without on-call burnout. "
            "Feel free to drop your questions or contact details here—our engineering team reviews incoming messages!"
        )

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
                    clean_content = sanitize_chat_text(h.get("text", ""))
                    messages.append({"role": role, "content": clean_content})
            messages.append({"role": "user", "content": user_text})

            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0.3,
                max_tokens=400,
            )
            ans = response.choices[0].message.content.strip()
            if ans:
                ans = sanitize_chat_text(ans)
                if any(k in text_lower for k in ("troubleshoot", "offline", "guide", "docs", "help")) and "/help" not in ans:
                    ans += "\n\nFor more detailed step-by-step troubleshooting playbooks and demo videos, check out our Help Centre at /help."
                return ans
        except Exception as e:
            log.warning("Groq chatbot call failed: %s; using deterministic fallback", e)

    # Deterministic fallback responses
    if any(k in text_lower for k in ("help", "guide", "doc", "troubleshoot", "demo", "video", "offline", "tutorial", "how to")):
        return (
            "You can find complete setup guides, troubleshooting playbooks, and our full video walkthrough demo "
            "in our Help Centre at /help! You can also view our contact page at /contact to reach our engineering team directly."
        )

    if any(k in text_lower for k in ("price", "cost", "plan", "free", "trial", "payment", "pay", "upi")):
        return (
            "Agent Daemon offers a 1-day free trial so you can test it on your repository. "
            "Our paid plans are ₹100 for 30 days or ₹1,000 for a full year, with simple UPI payments. "
            "Would you like help getting started?"
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
            "If the Agent Daemon team of engineers is currently away, leave your message or email and they will follow up shortly."
        )

    return (
        "Agent Daemon monitors your Python app's error logs, groups incidents, diagnoses the root cause, and opens pull requests with fixes. "
        "Can I answer any questions about setup, GitHub permissions, pricing, or our team?"
    )
