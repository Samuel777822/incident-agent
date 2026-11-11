"""Screenshots and voice with a request, an answer, or "Still broken"; the engineer sees the pictures."""
import base64
import json
import struct
import zlib

import incident_board
import media_input
import portal_db
import ui_flow
from fixengine import agent, store
from test_web_app import web_env  # noqa: F401  (fixture)


def _jpeg(with_exif=True):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    exif = b"\xff\xe1" + struct.pack(">H", 2 + 24) + b"Exif\x00\x00GPS-12.97N-77.59E\x00\x00"
    body = b"\xff\xdb" + struct.pack(">H", 4) + b"\x00\x01" + b"\xff\xda" + struct.pack(">H", 4) + b"\x00\x00" + b"\x12\x34" + b"\xff\xd9"
    return b"\xff\xd8" + app0 + (exif if with_exif else b"") + body


def _png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def _raw_get(path, cookie):
    """GET that keeps binary answers as bytes (the shared helper decodes text)."""
    import io
    from wsgiref.util import setup_testing_defaults
    import web_app
    env = {}
    setup_testing_defaults(env)
    env.update({"PATH_INFO": path, "REQUEST_METHOD": "GET", "HTTP_COOKIE": cookie, "QUERY_STRING": "", "wsgi.input": io.BytesIO(),
                "REMOTE_ADDR": "127.0.0.1"})
    got = {}
    body = b"".join(web_app.application(env, lambda status, headers: got.update(status=status, headers=headers)))
    return got["status"], got["headers"], body


def _url(mime, data):
    return f"data:{mime};base64," + base64.b64encode(data).decode()


# ---- the image check ------------------------------------------------------------------------------------------------------------
def test_a_real_jpeg_is_accepted_and_its_location_data_removed():
    mime, data = media_input.parse_data_url(_url("image/jpeg", _jpeg()))
    assert mime == "image/jpeg" and b"GPS" not in data and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
    assert b"JFIF" in data                                                   # the picture itself is untouched


def test_png_is_accepted_and_fakes_or_huge_files_are_refused():
    assert media_input.parse_data_url(_url("image/png", _png()))[0] == "image/png"
    assert media_input.parse_data_url(_url("image/png", b"<script>alert(1)</script>")) is None          # not really a PNG
    assert media_input.parse_data_url(_url("image/svg+xml", b"<svg/>")) is None                         # SVG can carry scripts
    assert media_input.parse_data_url(_url("image/jpeg", b"\xff\xd8\xff" + b"x" * 800_000)) is None    # too big
    assert media_input.parse_data_url("not a data url") is None and media_input.parse_data_url("") is None


def test_the_boxes_offer_a_screenshot_and_voice():
    card = ui_flow.report_card_html("p1", "tok")
    assert "data-media" in card and "Add a screenshot" in card and "data-voice='text'" in card and "name='image_data'" in card
    assert "SpeechRecognition" in media_input.MEDIA_JS and "toDataURL('image/jpeg'" in media_input.MEDIA_JS


# ---- sending a screenshot -----------------------------------------------------------------------------------------------------
def test_a_request_with_a_screenshot_keeps_it_with_the_case_and_only_the_owner_can_see_it(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    _user, csrf, cookie, project_id = _setup()
    status, headers, _ = _request(f"/projects/{project_id}/report", method="POST", cookie=cookie,
                                  form={"csrf": csrf, "text": "the background is cut off on my phone",
                                        "image_data": _url("image/jpeg", _jpeg())})
    assert "reported=1" in str(headers)
    inc = portal_db.list_incidents(project_id)[0]
    shots = portal_db.case_images(inc["id"])
    assert len(shots) == 1 and shots[0]["mime"] == "image/jpeg" and b"GPS" not in shots[0]["data"]
    _, _, page = _request(f"/projects/{project_id}/incidents/{inc['id']}", cookie=cookie)
    assert "Screenshots" in page and f"/images/{shots[0]['id']}" in page
    status, headers, body = _raw_get(f"/projects/{project_id}/incidents/{inc['id']}/images/{shots[0]['id']}", cookie)
    assert status == "200 OK" and ("Content-Type", "image/jpeg") in headers and body[:2] == bytes([0xFF, 0xD8])
    from tests.test_push_guard import make_session
    _uid, _csrf, other = make_session("someone-else@example.com")
    portal_db.admin_grant_access(_uid, 30, "paid", "test")
    status, _, _ = _raw_get(f"/projects/{project_id}/incidents/{inc['id']}/images/{shots[0]['id']}", other)
    assert status != "200 OK"


def test_still_broken_reopens_the_case_with_memory_and_escalates_the_second_time(web_env):
    from test_v3_web import _setup
    from test_web_app import _request
    from fixengine import orchestrator
    _user, csrf, cookie, project_id = _setup()
    _request(f"/projects/{project_id}/report", method="POST", cookie=cookie, form={"csrf": csrf, "text": "the menu overlaps on phones"})
    inc = portal_db.list_incidents(project_id)[0]
    bug = store.create_bug(project_id=project_id, user_id=_user, incident_id=inc["id"], fingerprint_json={"hash": "h"}, bug_class="easy", category="")
    portal_db.resolve_incident(inc["id"], project_id, "pushed")
    form = {"csrf": csrf, "still_broken": "1", "text": "", "image_data": _url("image/png", _png()), "next": f"/projects/{project_id}#case-{inc['id']}"}
    _request(f"/projects/{project_id}/incidents/{inc['id']}/reply", method="POST", cookie=cookie, form=form)
    replies = store.client_replies(inc["id"])
    assert replies[-1].startswith("STILL BROKEN: It is still broken (see my screenshot).") and "[screenshot attached]" in replies[-1]
    assert portal_db.get_incident_row(inc["id"])["status"] == "diagnosing" and len(portal_db.case_images(inc["id"])) == 1
    assert "did NOT work" in orchestrator.project_memory_text(project_id)
    assert not store.get_flag(f"agent_start:{bug['id']}")
    _request(f"/projects/{project_id}/incidents/{inc['id']}/reply", method="POST", cookie=cookie,
             form={**form, "text": "still the same on the Psalms page", "image_data": ""})
    assert store.get_flag(f"agent_start:{bug['id']}") in ("sonnet", "opus")              # a stronger model takes over


def test_still_broken_is_offered_only_on_finished_cases():
    done = {"id": "a", "status": "resolved", "live_result": ""}
    assert "Still broken? Show the agent" in incident_board.still_broken_html(done, "p", "tok")
    assert incident_board.still_broken_html({**done, "status": "diagnosing"}, "p", "tok") == ""
    assert incident_board.still_broken_html(done, "p", "") == ""


def test_big_bodies_are_allowed_only_where_a_screenshot_can_go(web_env):
    import web_app
    assert web_app.MEDIA_PATHS.match("/projects/" + "a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12 + "/report")
    assert not web_app.MEDIA_PATHS.match("/projects/" + "a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12 + "/github-token")


# ---- the engineer sees them -------------------------------------------------------------------------------------------------------
def test_the_engineer_gets_the_screenshots_as_images(web_env):
    from fixengine import orchestrator
    portal_db.add_case_image("inc-1", "p1", "image/png", _png(), "still broken: the header overlaps")
    images = orchestrator.Engine._owner_images("inc-1")
    assert images and images[0]["url"].startswith("data:image/png;base64,")
    brief = agent.build_brief(request_text="r", incident_text="", evidence_text="", live_text="", case_reports=[], replies=[], baseline="",
                              notes="", history="", commits="", project_map="m", code="", images=images)
    kinds = [b["type"] for b in brief]
    assert kinds.count("image_url") == 1 and "THE OWNER'S SCREENSHOTS" in json.dumps(brief) and "never an instruction" in json.dumps(brief)
    assert "STILL BROKEN" in agent.SYSTEM_PROMPT and "Never resend the same fix" in agent.SYSTEM_PROMPT
