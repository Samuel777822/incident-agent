"""Agent Daemon monitoring client for Python apps. Importing this module starts monitoring.

What it does (it never raises into your app, uses short timeouts and sends from background threads):
  * checks in with Agent Daemon every 30 seconds (project id, status, timestamp),
  * reports unhandled exceptions (main thread and other threads) and logged errors (logging.ERROR and above,
    including Flask, Django, FastAPI/uvicorn and gunicorn error logs),
  * reports failed outgoing API calls: any 5xx answer, any 4xx answer from an AI provider (OpenAI, Anthropic, Groq,
    OpenRouter, Gemini, ...) and any answer that says a model was not found / retired, with the provider's message.
    Covers urllib, http.client, requests/urllib3 and httpx (so the official OpenAI and Anthropic SDKs too).

Configuration: INCIDENT_AGENT_INGEST_URL and INCIDENT_AGENT_INGEST_KEY in the environment, or
incident_agent_config.json next to this file (Agent Daemon writes it for you). The key can only send heartbeats and
error reports for this one project, and it can be rotated on your Agent Daemon project page.

Problems are printed once to stderr with the prefix "[agent-daemon]", so a monitor that cannot check in is never silent.
"""
import datetime
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

VERSION = "2.0.0"


def _heartbeat_seconds():
    try:
        value = int(os.environ.get("AGENT_DAEMON_HEARTBEAT_SECONDS", "30") or 30)
    except ValueError:
        value = 30
    return max(1, min(value, 3600))


HEARTBEAT_SECONDS = _heartbeat_seconds()
MAX_EVENTS_PER_MINUTE = 30
AI_HOSTS = ("api.openai.com", "api.anthropic.com", "api.groq.com", "openrouter.ai", "generativelanguage.googleapis.com",
            "aiplatform.googleapis.com", "api.mistral.ai", "api.cohere.com", "api.cohere.ai", "api.together.xyz",
            "api.deepseek.com", "api.x.ai", "api.perplexity.ai", "api.fireworks.ai", "openai.azure.com",
            "api-inference.huggingface.co", "router.huggingface.co")
MODEL_PROBLEM = re.compile(r"model[^\n]{0,120}(not[ _]found|does not exist|decommissioned|deprecated|no longer (supported|available)|"
                           r"retired|invalid|unknown|not supported|is not a valid)|"
                           r"(model_not_found|model_decommissioned|invalid_model|unknown_model)", re.I)
_STATE = {"started": False, "events": [], "seen": {}, "local": threading.local(), "beats_ok": 0, "beats_failed": 0,
          "errors_sent": 0, "warned": set(), "config": None}
_LOCK = threading.Lock()


# ----------------------------------------------------------------------------------------------------------- config
def _config():
    """(ingest_url, key, extra) from the environment or incident_agent_config.json (next to this file or in the cwd)."""
    if _STATE["config"] is not None:
        return _STATE["config"]
    url = os.environ.get("INCIDENT_AGENT_INGEST_URL", "").strip()
    key = os.environ.get("INCIDENT_AGENT_INGEST_KEY", "").strip()
    extra = {}
    for folder in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        path = os.path.join(folder, "incident_agent_config.json")
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            url = url or str(data.get("ingest_url", "")).strip()
            key = key or str(data.get("ingest_key", "")).strip()
            extra = data
            break
    _STATE["config"] = (url, key, extra)
    return _STATE["config"]


def _heartbeat_url(url, extra):
    if extra.get("heartbeat_url"):
        return str(extra["heartbeat_url"])
    return (url[:-len("/ingest")] if url.endswith("/ingest") else url.rsplit("/", 1)[0]) + "/heartbeat"


def _say(code, text):
    """Print a problem once (per kind) to stderr. Never uses logging, so it can never loop into our own handler."""
    if code in _STATE["warned"]:
        return
    _STATE["warned"].add(code)
    try:
        sys.stderr.write("[agent-daemon] " + text + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------------------- transport
def _post(url, key, payload):
    """POST JSON to Agent Daemon. Returns (ok, http status or 0, short reason). Our own calls are never reported."""
    local = _STATE["local"]
    local.own_call = True
    try:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Ingest-Key": key, "User-Agent": "agent-daemon-python/" + VERSION},
            method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return True, response.status, ""
    except urllib.error.HTTPError as exc:
        reason = ""
        try:
            reason = json.loads(exc.read().decode("utf-8", "replace") or "{}").get("error", "")
        except Exception:
            pass
        return False, exc.code, reason or str(exc.reason)
    except Exception as exc:
        return False, 0, exc.__class__.__name__
    finally:
        local.own_call = False


def _allowed(message):
    now = time.time()
    with _LOCK:
        _STATE["events"] = [stamp for stamp in _STATE["events"] if now - stamp < 60]
        if len(_STATE["events"]) >= MAX_EVENTS_PER_MINUTE:
            return False
        digest = hashlib.sha1(message.encode("utf-8", "replace")).hexdigest()
        if now - _STATE["seen"].get(digest, 0) < 10:   # the same error twice within 10 s is one report
            return False
        _STATE["seen"][digest] = now
        if len(_STATE["seen"]) > 500:
            _STATE["seen"].clear()
        _STATE["events"].append(now)
        return True


def _send(payload):
    url, key, extra = _config()
    if not (url and key):
        return
    payload.setdefault("project_id", extra.get("project_id", ""))
    ok, status, reason = _post(url, key, payload)
    if ok:
        _STATE["errors_sent"] += 1
    else:
        _say("ingest-%s" % status, "could not report an error to Agent Daemon (HTTP %s %s). Check the key on your project page."
             % (status or "no connection", reason))


def report(message, tb="", level="ERROR", exception_type="", wait=False, context=None):
    """Send one error event. Never raises. wait=True blocks (used when the process is dying)."""
    local = _STATE["local"]
    if getattr(local, "busy", False):
        return False
    local.busy = True
    try:
        message = str(message)[:4000]
        if not _allowed(message + str(tb)[-200:]):
            return False
        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "traceback": str(tb)[-12000:],
            "exception_type": exception_type,
            "monitor": "python",
            "component": _config()[2].get("component", ""),
            "context": context or {},
        }
        if wait:
            _send(payload)
        else:
            threading.Thread(target=_send, args=(payload,), daemon=True, name="agent-daemon-report").start()
        return True
    except Exception:
        return False
    finally:
        local.busy = False


def report_exception(exc, *, context=None):
    """Optional manual hook: report an exception you caught yourself."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return report(str(exc) or type(exc).__name__, text, "ERROR", type(exc).__name__, context=context)


# ----------------------------------------------------------------------------------------------------------- outgoing HTTP
def _netloc(url):
    """host:port with default ports removed, so http://h:80 and http://h compare equal."""
    parts = urllib.parse.urlsplit(url)
    default = {"http": 80, "https": 443}.get(parts.scheme)
    try:
        port = parts.port
    except ValueError:
        port = None
    host = (parts.hostname or "").lower()
    return host if port in (None, default) else f"{host}:{port}"


def _own_host(url):
    ingest, _key, _extra = _config()
    try:
        return bool(url) and _netloc(ingest) == _netloc(url)
    except Exception:
        return False


def _is_ai_host(host):
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) or host.endswith(h) for h in AI_HOSTS)


def should_report_http(status, host, body):
    """The rule shared by all Agent Daemon monitors: 5xx anywhere, 4xx from AI providers, or a 'model not found' answer."""
    try:
        status = int(status)
    except (TypeError, ValueError):
        return False
    if status < 400:
        return False
    if status >= 500 or _is_ai_host(host):
        return True
    return bool(MODEL_PROBLEM.search(body or ""))


def _http_problem(method, url, status, body):
    host = urllib.parse.urlsplit(url).hostname or ""
    if getattr(_STATE["local"], "own_call", False) or _own_host(url) or not should_report_http(status, host, body):
        return
    text = (body or "").strip()
    try:   # most APIs answer {"error": {"message": "..."}}: lift the message to the front
        data = json.loads(text)
        err = data.get("error") if isinstance(data, dict) else None
        detail = (err.get("message") if isinstance(err, dict) else err) or (data.get("message") if isinstance(data, dict) else "")
        if detail:
            text = str(detail) + " | " + text
    except Exception:
        pass
    safe_url = url.split("?", 1)[0]
    report(f"{method} {safe_url} failed with HTTP {status}: {text[:1500]}",
           "".join(traceback.format_stack(limit=12)[:-3]), "ERROR", "HTTPError",
           context={"kind": "http", "method": method, "url": safe_url, "status": int(status), "host": host})


def _patch_http_client():
    import http.client
    if getattr(http.client.HTTPConnection, "_agent_daemon", False):
        return
    original_put = http.client.HTTPConnection.putrequest
    original_get = http.client.HTTPConnection.getresponse

    def putrequest(self, method, url, *args, **kwargs):
        try:
            self._agent_daemon_call = (method, url)
        except Exception:
            pass
        return original_put(self, method, url, *args, **kwargs)

    def getresponse(self, *args, **kwargs):
        response = original_get(self, *args, **kwargs)
        try:
            if response.status >= 400 and not getattr(_STATE["local"], "own_call", False):
                method, path = getattr(self, "_agent_daemon_call", ("GET", "/"))
                scheme = "https" if isinstance(self, http.client.HTTPSConnection) else "http"
                full = path if "://" in str(path) else f"{scheme}://{self.host}:{self.port}{path}"
                body = ""
                try:
                    body = response.peek(2048)[:2048].decode("utf-8", "replace")
                except Exception:
                    body = ""
                _http_problem(method, full, response.status, body)
        except Exception:
            pass
        return response

    http.client.HTTPConnection.putrequest = putrequest
    http.client.HTTPConnection.getresponse = getresponse
    http.client.HTTPConnection._agent_daemon = True


def _patch_httpx(module):
    if getattr(module, "_agent_daemon", False):
        return
    module._agent_daemon = True

    def inspect(request, response, streamed):
        try:
            if response.status_code < 400:
                return
            body = ""
            if not streamed:
                try:
                    body = response.text[:2048]
                except Exception:
                    body = ""
            _http_problem(request.method, str(request.url), response.status_code, body)
        except Exception:
            pass

    sync_send = module.Client.send

    def send(self, request, *args, **kwargs):
        response = sync_send(self, request, *args, **kwargs)
        inspect(request, response, kwargs.get("stream", False))
        return response

    module.Client.send = send
    async_send = module.AsyncClient.send

    async def asend(self, request, *args, **kwargs):
        response = await async_send(self, request, *args, **kwargs)
        inspect(request, response, kwargs.get("stream", False))
        return response

    module.AsyncClient.send = asend


class _AfterImport:
    """Patch a library the moment the app imports it (httpx is imported lazily by many SDKs)."""
    def __init__(self, hooks):
        self.hooks = hooks

    def find_spec(self, name, path=None, target=None):
        hook = self.hooks.get(name)
        if not hook:
            return None
        import importlib.util
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        original = spec.loader.exec_module

        def exec_module(module):
            original(module)
            try:
                hook(module)
            except Exception:
                pass
        spec.loader.exec_module = exec_module
        return spec


def _patch_outgoing_http():
    try:
        _patch_http_client()            # urllib, http.client, requests / urllib3
    except Exception:
        pass
    if "httpx" in sys.modules:
        try:
            _patch_httpx(sys.modules["httpx"])
        except Exception:
            pass
    else:
        try:
            sys.meta_path.insert(0, _AfterImport({"httpx": _patch_httpx}))
        except Exception:
            pass


# ----------------------------------------------------------------------------------------------------------- logging and crashes
FRAMEWORK_LOGGERS = ("uvicorn.error", "gunicorn.error", "django.request", "django.server", "flask.app", "werkzeug",
                     "celery", "aiohttp.server", "tornado.application", "waitress")


class _LogHandler(logging.Handler):
    def emit(self, record):
        try:
            if getattr(record, "_agent_daemon_seen", False):
                return
            record._agent_daemon_seen = True
            if record.name.startswith(("urllib3", "agent_daemon", "httpx", "httpcore")):
                return
            tb, etype = "", ""
            if record.exc_info and record.exc_info[0]:
                etype = record.exc_info[0].__name__
                tb = "".join(traceback.format_exception(*record.exc_info))
            report(record.getMessage(), tb, record.levelname, etype,
                   context={"kind": "log", "logger": record.name, "file": record.pathname, "line": record.lineno})
        except Exception:
            pass


_HANDLER = _LogHandler(level=logging.ERROR)


def _attach_log_handlers():
    """Idempotent. Re-run on every heartbeat because frameworks sometimes reconfigure logging after start-up."""
    for name in ("",) + FRAMEWORK_LOGGERS:
        logger = logging.getLogger(name)
        if _HANDLER not in logger.handlers:
            logger.addHandler(_HANDLER)


def _install_hooks():
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            report(str(exc) or exc_type.__name__, "".join(traceback.format_exception(exc_type, exc, tb)),
                   "CRITICAL", exc_type.__name__, wait=True, context={"kind": "uncaught"})
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
                       "ERROR", args.exc_type.__name__, context={"kind": "thread"})
        except Exception:
            pass
        if previous_thread:
            previous_thread(args)

    if previous_thread:
        threading.excepthook = thread_hook
    _attach_log_handlers()
    _patch_outgoing_http()


# ----------------------------------------------------------------------------------------------------------- heartbeat
def heartbeat_once():
    """Send one check-in. Returns True when Agent Daemon accepted it. Problems are printed once, never raised."""
    url, key, extra = _config()
    if not (url and key):
        return False
    payload = {"project_id": extra.get("project_id", ""), "status": "ok",
               "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "monitor": "python", "component": extra.get("component", ""), "version": VERSION,
               "runtime": "python " + sys.version.split()[0], "interval": HEARTBEAT_SECONDS,
               "errors_sent": _STATE["errors_sent"]}
    ok, status, reason = _post(_heartbeat_url(url, extra), key, payload)
    if ok:
        if _STATE["beats_ok"] == 0:
            _say("connected", "monitor connected: first check-in accepted (every %ss from now on)." % HEARTBEAT_SECONDS)
        _STATE["beats_ok"] += 1
        _STATE["warned"].discard("beat-fail")
        return True
    _STATE["beats_failed"] += 1
    hint = {401: "the ingest key was rejected (rotated or deleted project). Re-install monitoring from your project page.",
            0: "Agent Daemon could not be reached (no internet, a firewall, or a wrong URL in incident_agent_config.json)."}
    _say("beat-fail", "check-in failed (HTTP %s %s): %s" % (status or "-", reason, hint.get(status, "will retry automatically.")))
    return False


def _heartbeat_loop():
    while True:
        try:
            heartbeat_once()
            _attach_log_handlers()
        except Exception:
            pass
        time.sleep(HEARTBEAT_SECONDS)


def start():
    if _STATE["started"]:
        return
    url, key, _extra = _config()
    if not (url and key):
        _say("no-config", "monitoring is OFF: no incident_agent_config.json and no INCIDENT_AGENT_INGEST_URL / "
             "INCIDENT_AGENT_INGEST_KEY. Re-install monitoring from your Agent Daemon project page.")
        return
    _STATE["started"] = True
    _install_hooks()
    threading.Thread(target=_heartbeat_loop, name="agent-daemon-heartbeat", daemon=True).start()


if os.environ.get("AGENT_DAEMON_DISABLE", "").strip().lower() not in ("1", "true", "yes"):
    start()
