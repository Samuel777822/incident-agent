"""Gunicorn entry point; initialize and validate the production app once."""

import portal_db
from web_app import application, _secret

portal_db.init_db()
_secret()


