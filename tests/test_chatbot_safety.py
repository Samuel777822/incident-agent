import chatbot


def test_chatbot_replaces_configured_private_names(monkeypatch):
    monkeypatch.setenv("CHATBOT_PRIVATE_NAMES", "Example Founder")
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)

    result = chatbot.sanitize_chat_text("Created by Example Founder; email private@example.invalid")

    assert "Example Founder" not in result
    assert "private@example.invalid" not in result
    assert "the Agent Daemon team of engineers" in result
    assert "/contact" in result


def test_chatbot_allows_only_the_configured_support_address(monkeypatch):
    monkeypatch.setenv("CHATBOT_PRIVATE_NAMES", "")
    monkeypatch.setenv("SUPPORT_EMAIL", "support@example.invalid")

    result = chatbot.sanitize_chat_text("Contact support@example.invalid or visitor@example.invalid")

    assert "support@example.invalid" in result
    assert "visitor@example.invalid" not in result
    assert "support through /contact" in result


def test_founder_questions_are_intercepted_without_the_model(monkeypatch):
    monkeypatch.setenv("CHATBOT_PRIVATE_NAMES", "Example Founder")

    result = chatbot.answer_visitor_query("Who is Example Founder?")

    assert "Example Founder" not in result
    assert "Agent Daemon team of engineers" in result
