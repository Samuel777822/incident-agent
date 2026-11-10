"""Will our emails reach the inbox? (admin page check)

Emails go out as EMAIL_FROM (an @agentdaemon.xyz address) through Brevo or Resend, and the founders read mail in Zoho. Mail providers
send messages to spam when the sending domain is not authenticated. Three public DNS records decide that:

  SPF    one TXT record on the domain listing every service allowed to send as it (Zoho AND Brevo/Resend)
  DKIM   a signature key per sending service (Zoho: a selector you create; Brevo: brevo1/brevo2; Resend: resend)
  DMARC  a TXT record on _dmarc.<domain> saying what to do with mail that fails the checks

This module looks them up through public DNS-over-HTTPS (no secrets, cached for 6 hours) and returns plain problems with the fix.
"""
from __future__ import annotations

import os
import time

import httpx

_CACHE: dict = {}
CACHE_SECONDS = 6 * 3600


def _txt(name: str, client=None) -> list[str] | None:
    """TXT records of a name ([] when there are none, None when DNS could not be asked)."""
    try:
        get = client.get if client is not None else httpx.get
        resp = get("https://dns.google/resolve", params={"name": name, "type": "TXT"}, timeout=8)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return [str(a.get("data", "")).replace('" "', "").strip('"') for a in data.get("Answer", []) or [] if a.get("type") == 16]


def sender() -> tuple[str, str]:
    """(domain, service) of the address the app sends from."""
    address = os.getenv("EMAIL_FROM", "").strip()
    domain = address.split("@")[-1].strip(" >").lower() if "@" in address else ""
    service = "brevo" if os.getenv("BREVO_API_KEY") else ("resend" if os.getenv("RESEND_API_KEY") else ("smtp" if os.getenv("SMTP_HOST") else ""))
    return domain, service


def check(domain: str = "", service: str = "", client=None) -> dict:
    """{"domain", "service", "problems": [plain sentences], "ok": bool, "checked": bool}"""
    if os.getenv("EMAIL_HEALTH_CHECK", "1").strip().lower() in ("0", "false", "no", "off") and client is None:
        return {"domain": domain, "service": service, "problems": [], "ok": True, "checked": False}
    if not domain:
        domain, service = sender()
    if not domain:
        return {"domain": "", "service": service, "problems": ["EMAIL_FROM is not set, so no email is sent at all."], "ok": False, "checked": True}
    key = (domain, service)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS and client is None:
        return hit[1]
    problems: list[str] = []
    root = _txt(domain, client)
    if root is None:
        return {"domain": domain, "service": service, "problems": [], "ok": True, "checked": False}
    spf = [r for r in root if r.lower().startswith("v=spf1")]
    need = {"brevo": "spf.brevo.com", "resend": "amazonses.com"}.get(service, "")
    if not spf:
        problems.append(f"No SPF record on {domain}: mail providers cannot tell that Zoho" + (f" and {service.title()}" if need else "")
                        + " may send as you, so your emails go to spam.")
    elif len(spf) > 1:
        problems.append(f"{domain} has {len(spf)} SPF records. There must be exactly ONE: merge them into a single record.")
    else:
        rec = spf[0].lower()
        if "zoho" not in rec:
            problems.append("The SPF record does not include Zoho, so mail you send from Zoho can land in spam.")
        if need and need not in rec:
            problems.append(f"The SPF record does not include {service.title()} ({need}), the service the app sends through.")
    dkim_names = {"brevo": ["brevo1._domainkey", "brevo2._domainkey"], "resend": ["resend._domainkey"]}.get(service, [])
    if dkim_names and not any(_txt(f"{n}.{domain}", client) for n in dkim_names):
        problems.append(f"{service.title()} has no DKIM signature key on {domain} (the domain is not authenticated in {service.title()}).")
    dmarc = [r for r in (_txt(f"_dmarc.{domain}", client) or []) if r.lower().startswith("v=dmarc1")]
    if not dmarc:
        problems.append(f"No DMARC record on {domain}. Gmail and others now expect one from anyone who sends many emails.")
    result = {"domain": domain, "service": service, "problems": problems, "ok": not problems, "checked": True}
    _CACHE[key] = (time.time(), result)
    return result


def fix_steps(domain: str, service: str) -> list[str]:
    include = {"brevo": " include:spf.brevo.com", "resend": " include:amazonses.com"}.get(service, "")
    steps = [f"Open the DNS settings of {domain} (where you bought the domain).",
             f"Add ONE TXT record. Name: @ (or {domain}). Value: v=spf1 include:zoho.in{include} ~all",
             "In Zoho Mail: Admin Console, Domains, " + domain + ", Email Configuration, DKIM, Add, create a selector (for example zmail), "
             "copy the TXT record Zoho shows into your DNS, then press Verify in Zoho."]
    if service == "brevo":
        steps.append("In Brevo: Senders, Domains & Dedicated IPs, Domains, Add a domain (" + domain + "), Authenticate: copy the records Brevo "
                     "shows (brevo-code, brevo1._domainkey, brevo2._domainkey) into your DNS, then press Verify in Brevo.")
    elif service == "resend":
        steps.append("In Resend: Domains, Add domain (" + domain + "): copy the records Resend shows into your DNS, then press Verify.")
    steps.append(f"Add a TXT record. Name: _dmarc. Value: v=DMARC1; p=none; rua=mailto:postmaster@{domain} (you can make it stricter later).")
    steps.append("Wait up to an hour, then reload this page: this warning disappears when all records are found. Meanwhile, mark our "
                 "messages as Not spam in Zoho and add the sender to your contacts.")
    return steps
