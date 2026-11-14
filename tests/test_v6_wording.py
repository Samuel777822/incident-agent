"""v6: the pages customers read today name the Engineer and the Lead engineer, never the old Normal / High / Extra modes or Opus."""
import re

import architecture
import engineer_visual
import homepage
import plans
from fixengine import ui as fx_ui

OLD = re.compile(r"Normal → High|High or Extra|Extra tries|\bNormal mode\b|\(Extra\)|Normal engineer|tries left")


def test_how_it_works_and_the_engineer_ladder_use_the_v6_names():
    section = engineer_visual.section({}, plans.quotas(), plans.TRY_DEFINITION, plans.HUMAN_NEEDED)
    assert "Engineer → Lead engineer" in section and "The founders" not in section and "/build-request" in section
    assert not OLD.search(section) and "Opus" not in section
    page = architecture.user_page_html()
    assert "Engineer → Lead engineer" in page and not OLD.search(page)


def test_homepage_and_mode_help_use_the_v6_names():
    src = open(homepage.__file__, encoding="utf-8").read()
    assert not OLD.search(src)
    assert all(not OLD.search(text) for _name, text in fx_ui.MODE_HELP.values())
