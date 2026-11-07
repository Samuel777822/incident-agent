"""Start-up configuration check. In production a missing required setting stops the process with one clear message
(instead of failing later on the first request); optional settings only produce a warning in the log."""
from __future__ import annotations

import logging
import os

LOG = logging.getLogger("config_check")

REQUIRED_IN_PRODUCTION = {
    "SESSION_SECRET": "a random string of at least 32 characters (signs login cookies)",
    "DATABASE_URL": "the PostgreSQL connection string (Render fills it from the database)",
    "TOKEN_ENCRYPTION_KEY": "a Fernet key that encrypts saved GitHub tokens and monitor keys",
}
RECOMMENDED = {
    "PORTAL_BASE_URL": "the public address of this site; monitors and GitHub webhooks send data to it",
    "BREVO_API_KEY": "email (warnings, 'monitor offline' and 'make your repo private' messages)",
    "GROQ_API_KEY": "the free AI mode (or OPENROUTER_API_KEY)",
}


def problems(component: str = "web") -> tuple[list[str], list[str]]:
    """component: 'web' (needs SESSION_SECRET for login cookies) or 'worker' (never signs cookies)."""
    errors, warnings = [], []
    production = os.getenv("APP_ENV", "development").lower() == "production"
    for name, why in REQUIRED_IN_PRODUCTION.items():
        if name == "SESSION_SECRET" and component != "web":
            continue
        value = os.getenv(name, "").strip()
        if not value and (production or name == "SESSION_SECRET"):
            errors.append(f"{name} is not set: {why}.")
    if component == "web" and os.getenv("SESSION_SECRET", "") and len(os.getenv("SESSION_SECRET", "")) < 32:
        errors.append("SESSION_SECRET must contain at least 32 characters.")
    url = os.getenv("DATABASE_URL", "").strip()
    if production and url and not url.startswith(("postgres://", "postgresql://")):
        errors.append("DATABASE_URL must be a PostgreSQL URL in production.")
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if key:
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode("ascii"))
        except Exception:
            errors.append("TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Make one with: "
                          "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    for name, why in RECOMMENDED.items():
        if production and not os.getenv(name, "").strip():
            if name == "GROQ_API_KEY" and os.getenv("OPENROUTER_API_KEY", "").strip():
                continue
            warnings.append(f"{name} is not set: {why}.")
    return errors, warnings


def check(component: str = "web") -> None:
    errors, warnings = problems(component)
    for text in warnings:
        LOG.warning("Configuration: %s", text)
        print(f"[config] warning ({component}): {text}", flush=True)
    if errors:
        message = "Agent Daemon cannot start; fix these environment variables:\n  - " + "\n  - ".join(errors)
        print(message, flush=True)
        raise SystemExit(message)
