"""setup_env.py writes the private .env from a hidden prompt and never echoes the key."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import setup_env                                                                     # noqa: E402

FAKE = "sk-or-" + "v1-" + "0" * 40                                                  # obviously fake, built in pieces


def test_writes_the_key_into_a_copy_of_the_example(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("# note\nOPENROUTER_API_KEY=\nFIXENGINE_PROVIDER=auto\n", encoding="utf-8")
    env = tmp_path / ".env"
    code = setup_env.run(env, example, ask=lambda prompt: "  " + FAKE + "  ", confirm=lambda p: "y")
    assert code == 0
    text = env.read_text(encoding="utf-8").splitlines()
    assert "OPENROUTER_API_KEY=" + FAKE in text and "FIXENGINE_PROVIDER=auto" in text and "# note" in text


def test_a_wrong_looking_key_writes_nothing(tmp_path):
    env = tmp_path / ".env"
    assert setup_env.run(env, tmp_path / "missing", ask=lambda p: "not a key", confirm=lambda p: "y") == 1
    assert not env.exists()


def test_an_existing_env_is_kept_unless_you_say_yes(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=keep-me\n", encoding="utf-8")
    assert setup_env.run(env, tmp_path / "missing", ask=lambda p: FAKE, confirm=lambda p: "n") == 0
    assert env.read_text(encoding="utf-8") == "OPENROUTER_API_KEY=keep-me\n"


def test_the_loader_then_picks_the_key_up(tmp_path, monkeypatch):
    from fixengine import envfile
    env = tmp_path / ".env"
    setup_env.run(env, tmp_path / "missing", ask=lambda p: FAKE, confirm=lambda p: "y")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert envfile.load_env_file(env) == ["OPENROUTER_API_KEY"]
    import os
    assert os.environ["OPENROUTER_API_KEY"] == FAKE
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
