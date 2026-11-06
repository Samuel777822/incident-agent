"""The .env loader: reads a local file, never overrides real variables, and the file can never be committed."""
from pathlib import Path

from fixengine import envfile

ROOT = Path(__file__).resolve().parent.parent


def test_parses_comments_quotes_export_and_inline_comments():
    got = envfile.parse('# note\nA=1\nexport B="two words"\nC=\'x y\'\nD=value # trailing\n\nbad line\n1BAD=no\nE=\n')
    assert got == {"A": "1", "B": "two words", "C": "x y", "D": "value", "E": ""}


def test_loads_values_but_real_variables_and_empty_placeholders_win(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("FX_TEST_NEW=fresh\nFX_TEST_EXISTING=from-file\nFX_TEST_EMPTY=\n", encoding="utf-8")
    monkeypatch.setenv("FX_TEST_EXISTING", "from-terminal")
    monkeypatch.delenv("FX_TEST_NEW", raising=False)
    monkeypatch.delenv("FX_TEST_EMPTY", raising=False)
    names = envfile.load_env_file(f)
    import os
    assert names == ["FX_TEST_NEW"]
    assert os.environ["FX_TEST_NEW"] == "fresh" and os.environ["FX_TEST_EXISTING"] == "from-terminal"
    assert "FX_TEST_EMPTY" not in os.environ
    monkeypatch.delenv("FX_TEST_NEW", raising=False)


def test_a_missing_file_is_fine(tmp_path):
    assert envfile.load_env_file(tmp_path / "nope.env") == []


def test_the_real_env_file_can_never_be_committed_or_baked_into_an_image():
    git = (ROOT / ".gitignore").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    assert ".env" in git
    docker = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in docker


def test_the_example_file_has_empty_key_slots_only():
    example = envfile.parse((ROOT / ".env.example").read_text(encoding="utf-8"))
    for name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        assert example[name] == ""
