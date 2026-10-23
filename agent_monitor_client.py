"""Agent Daemon monitoring client. Importing this module starts monitoring.

It reports unhandled exceptions and logged errors to your Agent Daemon project
and sends a heartbeat every few minutes. It never raises into your app, uses
short network timeouts and sends events from background threads.

Configuration: INCIDENT_AGENT_INGEST_URL and INCIDENT_AGENT_INGEST_KEY in the
environment, or incident_agent_config.json next to this file.
"""
import datetime
import json
import logging
import os
import sys
import threading
import time
import traceback
import urllib.request

HEARTBEAT_SECONDS = 300
MAX_EVENTS_PER_MINUTE = 30
_STATE = {"started": False, "events": [], "local": threading.local()}


def _config():
    url = os.environ.get("INCIDENT_AGENT_INGEST_URL", "").strip()
    key = os.environ.get("INCIDENT_AGENT_INGEST_KEY", "").strip()
    if not (url and key):
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incident_agent_config.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            url = url or str(data.get("ingest_url", "")).strip()
            key = key or str(data.get("ingest_key", "")).strip()
        except Exception:
            pass
    return url, key


def _post(url, key, payload):
    try:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Ingest-Key": key}, method="POST")
        with urllib.request.urlopen(request, timeout=3):
            return True
    except Exception:
        return False


def _allowed():
    now = time.time()
    recent = [stamp for stamp in _STATE["events"] if now - stamp < 60]
    _STATE["events"] = recent
    if len(recent) >= MAX_EVENTS_PER_MINUTE:
        return False
    recent.append(now)
    return True


def _send(payload):
    url, key = _config()
    if url and key:
        _post(url, key, payload)


def report(message, tb="", level="ERROR", exception_type="", wait=False):
    """Send one error event. Never raises. wait=True blocks (used when the process is dying)."""
    local = _STATE["local"]
    if getattr(local, "busy", False):
        return False
    local.busy = True
    try:
        if not _allowed():
            return False
        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": level,
            "message": str(message)[:4000],
            "traceback": str(tb)[-12000:],
            "exception_type": exception_type,
        }
        if wait:
            _send(payload)
        else:
            threading.Thread(target=_send, args=(payload,), daemon=True).start()
        return True
    except Exception:
        return False
    finally:
        local.busy = False


def report_exception(exc, *, context=None):
    """Optional manual hook, kept for backwards compatibility."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return report(str(exc) or type(exc).__name__, text, "ERROR", type(exc).__name__)


class _LogHandler(logging.Handler):
    def emit(self, record):
        try:
            if record.name.startswith(("urllib3", "agent_monitor")):
                return
            tb, etype = "", ""
            if record.exc_info and record.exc_info[0]:
                etype = record.exc_info[0].__name__
                tb = "".join(traceback.format_exception(*record.exc_info))
            report(record.getMessage(), tb, record.levelname, etype)
        except Exception:
            pass


def _install_hooks():
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            report(str(exc) or exc_type.__name__, "".join(traceback.format_exception(exc_type, exc, tb)),
                   "CRITICAL", exc_type.__name__, wait=True)
        except Exception:
            pass
        previous(exc_type, exc, tb)

    sys.excepthook = hook
    previous_thread = getattr(threading, "excepthook", None)

    def thread_hook(args):
        try:
            if args.exc_type is not SystemExit:
                report(str(args.exc_value) or args.exc_type.__name__,
                       "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
                       "ERROR", args.exc_type.__name__)
        except Exception:
            pass
        if previous_thread:
            previous_thread(args)

    if previous_thread:
        threading.excepthook = thread_hook
    handler = _LogHandler(level=logging.ERROR)
    logging.getLogger().addHandler(handler)


def _heartbeat_loop():
    while True:
        try:
            url, key = _config()
            if url and key:
                base = url[:-len("/ingest")] if url.endswith("/ingest") else url.rsplit("/", 1)[0]
                _post(base + "/heartbeat", key, {})
        except Exception:
            pass
        time.sleep(HEARTBEAT_SECONDS)


def start():
    if _STATE["started"]:
        return
    url, key = _config()
    if not (url and key):
        return
    _STATE["started"] = True
    _install_hooks()
    threading.Thread(target=_heartbeat_loop, name="agent-daemon-heartbeat", daemon=True).start()


start()
