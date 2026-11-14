"""Render's free plan allows 5 GB a month of data sent out; it ran out on 14 Nov 2026 because open dashboards re-downloaded their
live panel every 5 seconds, uncompressed. Pages are now gzip-compressed and a live panel that has not changed costs no body."""
import gzip
import io
from wsgiref.util import setup_testing_defaults

import incident_board
import web_app
from tests.test_v3_web import _setup
from tests.test_web_app import web_env  # noqa: F401  (fixture)


def _raw(path, cookie="", **env):
    values = {}
    setup_testing_defaults(values)
    values.update({"PATH_INFO": path, "QUERY_STRING": "", "REQUEST_METHOD": "GET", "REMOTE_ADDR": "127.0.0.1",
                   "HTTP_COOKIE": cookie, "wsgi.input": io.BytesIO()})
    values.update(env)
    got = {}
    body = b"".join(web_app.application(values, lambda status, headers: got.update(status=status, headers=dict(headers))))
    return got["status"], got["headers"], body


def test_pages_are_compressed_only_when_the_browser_accepts_it(web_env):
    status, headers, body = _raw("/pricing", HTTP_ACCEPT_ENCODING="gzip, deflate, br")
    assert status == "200 OK" and headers["Content-Encoding"] == "gzip" and headers["Vary"] == "Accept-Encoding"
    html = gzip.decompress(body).decode()
    assert "Basic" in html and int(headers["Content-Length"]) == len(body) and len(body) * 3 < len(html.encode())
    status, headers, body = _raw("/pricing")
    assert "Content-Encoding" not in headers and b"Basic" in body                 # old clients still get plain HTML
    _, headers, _ = _raw("/assets/daemon-bg.webp", HTTP_ACCEPT_ENCODING="gzip")
    assert "Content-Encoding" not in headers                                      # images are already compressed


def test_an_unchanged_live_panel_costs_no_body(web_env):
    _user, _csrf, cookie, pid = _setup()
    status, headers, body = _raw(f"/projects/{pid}/incidents/live", cookie, HTTP_X_LIVE_HASH="")
    assert status == "200 OK" and body and headers["X-Live-Hash"]
    status, again, body = _raw(f"/projects/{pid}/incidents/live", cookie, HTTP_X_LIVE_HASH=headers["X-Live-Hash"])
    assert status == "204 No Content" and body == b""                            # nothing changed: nothing sent
    status, _, body = _raw(f"/projects/{pid}/incidents/live", cookie, HTTP_X_LIVE_HASH="old")
    assert status == "200 OK" and body                                           # changed: the new panel
    status, headers, body = _raw("/dashboard/live", cookie, HTTP_X_LIVE_HASH="")
    assert status == "200 OK" and _raw("/dashboard/live", cookie, HTTP_X_LIVE_HASH=headers["X-Live-Hash"])[0] == "204 No Content"
    assert "X-Live-Hash" not in _raw(f"/projects/{pid}/incidents/live", cookie)[1]   # normal page loads are untouched


def test_the_live_script_sends_its_hash_and_keeps_the_panel_on_204():
    js = incident_board.LIVE_JS
    assert "'X-Live-Hash': hash" in js and "r.status === 204" in js and incident_board.LIVE_JS_VERSION == "4"
