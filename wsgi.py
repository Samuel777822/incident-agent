"""Gunicorn entry point; initialize and validate the production app once."""

import config_check
import portal_db
from web_app import application, _secret

config_check.check("web")          # a missing required setting stops here with one clear message
portal_db.init_db()
_secret()


