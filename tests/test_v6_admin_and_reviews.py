"""v6: the admin page is a set of sections (one box each) instead of one endless page, and customers can leave reviews that the
admins see in their own section (proof for the next hackathon organizer)."""
import re

import incident_board
import notifications
import portal_db
from test_portal_flows import location, make_session, post
from test_web_app import _request, web_env  # noqa: F401  (fixture)


def test_the_admin_home_is_boxes_and_each_box_opens_one_section(web_env):
    _, csrf, cookie = make_session("admin1@example.com")
    status, _, hub = _request("/admin", cookie=cookie)
    assert status == "200 OK"
    for key in ("requests", "payments", "customers", "founders", "tickets", "reviews", "chats", "apps", "incidents", "system"):
        assert f"href='/admin?view={key}'" in hub, key
    assert "href='/admin/fix'" in hub and "href='/admin/architecture'" in hub
    assert "Grant access" not in hub and "Support Tickets &amp; Inquiries" not in hub          # the long tables are not on the home
    _, _, tickets = _request("/admin?view=tickets", cookie=cookie)
    assert "Support Tickets &amp; Inquiries" in tickets and "← All sections" in tickets and "Grant access" not in tickets
    _, _, unknown = _request("/admin?view=nothing", cookie=cookie)
    assert "href='/admin?view=reviews'" in unknown                                            # an unknown section shows the home


def test_a_form_in_a_section_comes_back_to_that_section(web_env):
    user_id, *_ = make_session("team@example.com")
    _, csrf, cookie = make_session("admin1@example.com")
    _, _, page = _request("/admin?view=customers", cookie=cookie)
    assert "action='/admin?view=customers'" in page
    _, headers, _ = post("/admin?view=customers", cookie, csrf, action="grant", user_id=user_id, grant="basic:30")
    assert location(headers) == "/admin?view=customers&msg=access_granted"


def test_custom_job_requests_have_their_own_section(web_env):
    portal_db.create_support_ticket("Riya", "riya@example.com", "Custom job: build a new app", "WhatsApp: +91 98765 43210")
    portal_db.create_support_ticket("Sam", "sam@example.com", "Login broken", "help")
    _, _, cookie = make_session("admin1@example.com")
    _, _, founders = _request("/admin?view=founders", cookie=cookie)
    _, _, tickets = _request("/admin?view=tickets", cookie=cookie)
    assert "riya@example.com" in founders and "sam@example.com" not in founders
    assert "sam@example.com" in tickets and "riya@example.com" not in tickets
    _, _, hub = _request("/admin", cookie=cookie)
    assert re.search(r"Custom job requests</b><span class='n'>1</span>", hub)


def test_customers_leave_reviews_and_the_admins_see_them(web_env, monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "notify_admins", lambda subject, body, kind="admin": sent.append((subject, body)) or [])
    user_id, csrf, cookie = make_session("dev@example.com")
    status, _, page = _request("/review", cookie=cookie)
    assert status == "200 OK" and "How is Agent Daemon doing?" in page and "name='can_publish'" in page
    _, _, bad = post("/review", cookie, csrf, rating="9", text="?")
    assert "pick 1 to 5 stars" in bad and not portal_db.list_reviews()
    _, _, ok = post("/review", cookie, csrf, rating="5", text="Found the CSS bug in a minute", can_publish="1")
    assert "Thanks for your review" in ok
    review = portal_db.list_reviews()[0]
    assert review["rating"] == 5 and review["can_publish"] == 1 and review["email"] == "dev@example.com"
    assert "★★★★★" in sent[0][0] and "Found the CSS bug" in sent[0][1]
    post("/review", cookie, csrf, rating="3", text="")
    assert portal_db.review_stats() == {"count": 2, "average": 4.0, "publishable": 1}
    _, _, admin_cookie = make_session("admin1@example.com")
    _, _, section = _request("/admin?view=reviews", cookie=admin_cookie)
    assert "Found the CSS bug in a minute" in section and "Average 4.0 / 5" in section and "May publish" in section
    assert _request("/review")[0].startswith("30")                                           # sign-in needed


def test_reviews_are_asked_for_on_the_dashboard_and_on_every_fixed_case():
    fixed = incident_board.still_broken_html({"id": "i-1", "status": "resolved"}, "p-1", "tok")
    assert "/review?case=i-1&amp;project=p-1" in fixed and "Rate this fix" in fixed
    assert incident_board.still_broken_html({"id": "i-1", "status": "open"}, "p-1", "tok") == ""
    import web_app
    src = open(web_app.__file__, encoding="utf-8").read()
    assert "href='/review'>&#9733; Leave a review</a>" in src
