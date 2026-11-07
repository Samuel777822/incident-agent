"""AI Knowledge Base & Chatbot Engine for Agent Daemon.

Answers visitor questions with high accuracy using Groq LLM (when configured)
and robust deterministic responses covering all aspects of Agent Daemon.
"""

from __future__ import annotations

import json
import logging
import os
import re
import plans

log = logging.getLogger(__name__)

DAEMON_KNOWLEDGE = """
=== ABOUT AGENT DAEMON ===
Product: Agent Daemon (hosted at https://incident-agent-portal.onrender.com)
Tagline: Push your code. The agent catches what broke, fixes it, and pushes the fix back to GitHub, before you deploy.
Who it is for: vibe coders, students and hackathon teams who have no time to debug.
Languages: Python, JavaScript, TypeScript (React, Next.js, Node), Java (Maven, Gradle, plain javac) and plain HTML/CSS/JS sites,
including repositories that mix several of them (for example a Python backend, a React frontend and a static landing page).

TEAM:
Agent Daemon is built and maintained by the Agent Daemon team of engineers.

HOW IT WORKS (two ways to catch bugs, a project can use one or both):
A. Push guard (new, recommended): when you connect a repository we add a GitHub webhook. Every push to your branch is downloaded
   into a fresh sandbox where we install, build, type-check, run tests and start the app, separately for every language in the repo.
   Green: the commit gets a green "Agent Daemon / push check" status on GitHub. Red: an incident opens and the agent starts fixing it.
   If the webhook cannot be added, the worker checks the branch every few minutes instead.
B. Live error watch (classic): a tiny client in the running app reports crashes; the same fix pipeline takes over.
The fix pipeline: a free first look, then the agent picks an economical mode (Normal, High or Extra). The model only returns text;
our code applies the patch and the SAME sandbox check must pass. The fix goes to a new agent-daemon/fix-... branch with a pull request.
Agent modes per project:
   - Report only: explains the problem, no code changes.
   - Pull request: opens a pull request with the fix for you to merge.
Every pull request stays open for human review, including when sandbox and GitHub checks pass.
The dashboard shows live what the agent is doing (downloading, testing in the sandbox, writing a fix in a given mode, opening a pull request),
which mode is working and how many tries are left.

HOW THE AGENT CHOOSES AN AI (explain it in plain words first):
Agent Daemon compares the available AI models and chooses an economical option to fix the bug. When a weaker AI cannot solve it,
the agent moves to a stronger one and passes on what it learned. It always starts with free attempts and gives Normal at least two
attempts before High or Extra, and it never goes past the customer's tries or the per-bug limits.
Two different numbers appear on /how-it-works: "Cost of this AI attempt" (what one attempt costs) and "Estimated total cost to resolve
the bug" (that attempt plus what may follow if it fails). The ₹30 "person steps in" value there is internal only and is NEVER charged.
The calculator's success chances are starting estimates, not proven rates, and its usage slider is a demonstration, not the user's account.
Only if someone asks for the technical name: an expected-cost dynamic program, like Dijkstra's cheapest-route idea for uncertain steps.

DEFINITIONS (use exactly these meanings):
- Try: @@TRY@@
- Modes: @@MODES@@
- Why a stronger AI: @@WHY@@
- When a fix fails: @@FAIL@@
- When a person is needed: @@HUMAN@@

PRICING & PLANS:
- Free Trial: 1 day of full access upon admin approval.
- Paid Monthly: @@MONTHLY@@ for 30 days. Paid Yearly: @@YEARLY@@ for 365 days (about @@YEARLY_PM@@ a month, saves @@SAVING@@).
- Every plan includes, every month: 30 Normal tries, 6 High tries and 3 Extra tries (exact: @@QUOTAS@@), plus Low effort on fair use.
  Quotas reset monthly and do not roll over. Technical faults on our side never count as a try.
- Projects: @@PROJECTS@@.
- Add-ons: a @@PACK@@ pack adds @@PACK_HIGH@@ High or @@PACK_EXTRA@@ Extra tries for the current month; an extra project is @@SLOT@@ once.
- We sell attempts to fix a bug, not guaranteed fixes.
- Payment: UPI QR (Paytm, Google Pay, PhonePe) with the 12-digit UTR, confirmed by an admin within 1 to 2 hours.

HELP:
- Help Centre: /help. How it works (interactive architecture): /how-it-works. Pricing: /pricing. Usage and tries left: /usage.
- GitHub token: a classic token with the 'repo' and 'workflow' scopes.

CONTACT & LIVE SUPPORT:
The Agent Daemon team of engineers reads this chat. Contact form: /contact.
@@SUPPORT@@
"""

DAEMON_KNOWLEDGE = (DAEMON_KNOWLEDGE
    .replace("@@MONTHLY@@", f"₹{plans.PLAN_PRICES['monthly']:,}")
    .replace("@@YEARLY@@", f"₹{plans.PLAN_PRICES['yearly']:,}")
    .replace("@@YEARLY_PM@@", f"₹{plans.YEARLY_PER_MONTH:,}")
    .replace("@@SAVING@@", f"₹{plans.YEARLY_SAVING:,}")
    .replace("@@QUOTAS@@", plans.quota_sentence())
    .replace("@@PACK@@", f"₹{plans.PACK_PRICE}")
    .replace("@@PACK_HIGH@@", str(plans.PACK_HIGH_TRIES))
    .replace("@@PACK_EXTRA@@", str(plans.PACK_EXTRA_TRIES))
    .replace("@@PROJECTS@@", plans.projects_sentence())
    .replace("@@TRY@@", plans.TRY_DEFINITION).replace("@@MODES@@", plans.MODE_SUMMARY).replace("@@WHY@@", plans.WHY_STRONGER)
    .replace("@@FAIL@@", plans.FAILED_FIX).replace("@@HUMAN@@", plans.HUMAN_NEEDED)
    .replace("@@SLOT@@", f"₹{plans.PROJECT_SLOT_PRICE}")
    .replace("@@SUPPORT@@", "Support email: " + (os.getenv("SUPPORT_EMAIL", "").strip() or "contact@agentdaemon.xyz")))

SYSTEM_PROMPT = f"""You are the friendly, helpful AI Assistant for Agent Daemon.
You answer questions from prospective customers and users who visit the website.

KNOWLEDGE BASE:
{DAEMON_KNOWLEDGE}

CRITICAL PRIVACY DIRECTIVES (MANDATORY):
- NEVER mention any personal names (such as Abhay, Pranav, Samuel, Rao) under ANY circumstances.
- NEVER disclose personal or admin email addresses. The only email address you may give out is the support email listed in the knowledge base (if one is listed).
- When asked "Who are the founders?", "Who made this?", "Who built this?", or about the creators, ALWAYS state that Agent Daemon is created and operated by the "Agent Daemon team of engineers".
- For contact, refer visitors to this live chat, the Contact form at /contact, or the support email if one is listed.

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
                model=os.getenv("CHATBOT_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")),
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
            f"Our paid plans are ₹{plans.PLAN_PRICES['monthly']:,} for 30 days or ₹{plans.PLAN_PRICES['yearly']:,} for a full year "
            f"(about ₹{plans.YEARLY_PER_MONTH:,} a month), with simple UPI payments. Each month includes {plans.quota_sentence()}. "
            f"One project is included; each extra project is a one-time ₹{plans.PROJECT_SLOT_PRICE}. "
            "We sell attempts to fix a bug, not guaranteed fixes. "
            "Would you like help getting started?"
        )

    if any(k in text_lower for k in ("try", "tries", "attempt", "quota", "left")):
        return f"{plans.TRY_DEFINITION} Every plan includes {plans.quota_sentence()}. Your dashboard shows how many are left."

    if any(k in text_lower for k in ("stronger", "high mode", "extra mode", "why high", "why extra", "escalat", "which ai", "which model")):
        return f"{plans.MODE_SUMMARY} {plans.WHY_STRONGER}"

    if any(k in text_lower for k in ("fail", "human", "person", "review")):
        return f"{plans.FAILED_FIX} {plans.HUMAN_NEEDED}"

    if any(k in text_lower for k in ("language", "python", "java", "javascript", "typescript", "react", "html", "node")):
        return (
            "Agent Daemon checks and fixes Python, JavaScript, TypeScript, Java and plain HTML/CSS/JS projects, and repos that mix them: "
            "each part (say a Python backend and a React frontend) is built and tested on its own. See /how-it-works for the full picture."
        )

    if any(k in text_lower for k in ("how does it work", "how it works", "what is", "features", "github", "push", "deploy", "algorithm", "router")):
        return (
            "Every time you push to GitHub, Agent Daemon installs, builds, tests and starts your code in a sandbox. If something breaks, "
            "the agent proposes a fix, runs the same check, and opens a pull request for you to review and merge. "
            "The agent picks an economical AI that is likely to fix the bug and moves to a stronger one only when needed. "
            "The interactive diagram is at /how-it-works."
        )

    if any(k in text_lower for k in ("project", "repo", "repositories")):
        return (f"Every plan includes one project. Each extra project is a one-time ₹{plans.PROJECT_SLOT_PRICE}, and your monthly "
                "tries are shared by all your projects. Add one from your dashboard.")

    if any(k in text_lower for k in ("contact", "email", "talk", "human", "support", "online", "hello", "hi", "hey")):
        return (
            "Hello! I am the Agent Daemon assistant. You can chat with our team right here! "
            "If the Agent Daemon team of engineers is currently away, leave your message or email and they will follow up shortly."
        )

    return (
        "Agent Daemon checks every push to GitHub in a sandbox, fixes what broke, and pushes the fix back as a pull request. "
        "Can I answer any questions about setup, languages, pricing, or how the agent decides which mode to use?"
    )
