"""The Pay ₹200 / Pay ₹1,500 buttons must never vanish under the cursor (11 Nov 2026: in Chrome on some graphics cards the buttons
inside a blurred-glass price card disappeared while the card tilted in 3D)."""
import re

import theme_motion


def _tilt_selectors() -> list[str]:
    m = re.search(r"var TILT='([^']+)'", theme_motion.MOTION_JS)
    assert m, "the tilt list is missing"
    return [s.strip() for s in m.group(1).split(",")]


def test_price_cards_never_tilt():
    assert ".price-card" not in _tilt_selectors()
    assert ".project-card" in _tilt_selectors()                         # other cards still move


def test_a_tilting_card_has_no_glass_blur():
    rule = re.search(r"\.tilt\{([^}]*)\}", theme_motion.MOTION_CSS)
    assert rule and "backdrop-filter:none" in rule.group(1) and "-webkit-backdrop-filter:none" in rule.group(1)


def test_the_pages_with_pay_buttons_load_the_fixed_motion(monkeypatch):
    import footer_pages
    html = footer_pages.pricing_page_html(signed_in=True)
    assert "price-card" in html and "button primary" in html
    assert "var TILT='" in theme_motion.MOTION_JS and ".price-card" not in _tilt_selectors()
