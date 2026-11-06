import json
import re
import pytest

import portal_db
import footer_pages
import web_app
from test_web_app import _request, web_env


def test_footer_gov_visitor_and_last_updated_strip(web_env):
    # 1. Initial request on homepage
    st, hdrs, body = _request("/")
    assert st == "200 OK"

    # Verify visual sections
    assert "gov-info-strip" in body
    assert "TOTAL VISITORS SINCE LAUNCH" in body
    assert "WEBSITE LAST UPDATED" in body
    assert "gov-digit-tile" in body

    # Verify date format is strictly DD-MM-YYYY
    assert re.search(r"\b\d{2}-\d{2}-\d{4}\b", body)
    assert footer_pages.WEBSITE_LAST_UPDATED in body
    assert "04-11-2026" in body

    # Verify copyright is retained below this section
    idx_strip = body.find("gov-info-strip")
    idx_copyright = body.find("&copy; 2026 Agent Daemon")
    assert idx_strip != -1
    assert idx_copyright != -1
    assert idx_strip < idx_copyright, "Website info strip must appear above the copyright line"


def test_unique_visitor_counting_and_bot_filtering(web_env):
    initial_count = portal_db.get_total_unique_visitors()

    # 1. Request with bot User-Agent should NOT be counted
    headers_bot = {"HTTP_USER_AGENT": "Googlebot/2.1 (+http://www.google.com/bot.html)"}
    st, _, _ = _request("/", headers=headers_bot)
    assert st == "200 OK"
    assert portal_db.get_total_unique_visitors() == initial_count

    # Another bot User-Agent (curl / python-requests)
    headers_curl = {"HTTP_USER_AGENT": "curl/7.88.1"}
    st, _, _ = _request("/", headers=headers_curl)
    assert st == "200 OK"
    assert portal_db.get_total_unique_visitors() == initial_count

    # 2. Genuine human visitor arrives
    headers_human = {"HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    st, resp_headers, body = _request("/", headers=headers_human)
    assert st == "200 OK"
    count_after_first = portal_db.get_total_unique_visitors()
    assert count_after_first == initial_count + 1

    # Extract visitor cookie
    cookie_header = [v for k, v in resp_headers if k.lower() == "set-cookie" and "agent_visitor_id" in v]
    visitor_cookie = ""
    if cookie_header:
        visitor_cookie = cookie_header[0].split(";")[0]

    # 3. Refreshing with the same visitor cookie MUST NOT increment the unique count
    st, _, _ = _request("/", cookie=visitor_cookie, headers=headers_human)
    assert st == "200 OK"
    assert portal_db.get_total_unique_visitors() == count_after_first

    # Multiple refreshes
    for _ in range(5):
        _request("/", cookie=visitor_cookie, headers=headers_human)
    assert portal_db.get_total_unique_visitors() == count_after_first

    # 4. Another genuine unique visitor arrives with different cookie
    another_cookie = "agent_visitor_id=11111111-2222-3333-4444-555555555555"
    st, _, _ = _request("/", cookie=another_cookie, headers=headers_human)
    assert st == "200 OK"
    assert portal_db.get_total_unique_visitors() == count_after_first + 1


def test_api_visitor_track_endpoint(web_env):
    # Test /api/visitor/track returns json with accurate count and last_updated
    headers_human = {"HTTP_USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    st, _, body = _request("/api/visitor/track", method="POST", form={"path": "/", "referrer": ""}, headers=headers_human)
    assert st == "200 OK"
    data = json.loads(body)
    assert data["ok"] is True
    assert "count" in data
    assert isinstance(data["count"], int)
    assert data["last_updated"] == footer_pages.WEBSITE_LAST_UPDATED
    assert data["last_updated"] == "04-11-2026"
