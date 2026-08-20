from agent.services import google_oauth


def test_is_email_allowed_matches_case_insensitively(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "Jordan@Example.com,alex@example.com")

    assert google_oauth.is_email_allowed("jordan@example.com") is True
    assert google_oauth.is_email_allowed("JORDAN@EXAMPLE.COM") is True


def test_is_email_allowed_rejects_unlisted_email(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")

    assert google_oauth.is_email_allowed("stranger@example.com") is False


def test_is_email_allowed_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("ALLOWED_GOOGLE_EMAILS", raising=False)

    assert google_oauth.is_email_allowed("jordan@example.com") is False


def test_is_email_allowed_ignores_whitespace_around_entries(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", " jordan@example.com , alex@example.com ")

    assert google_oauth.is_email_allowed("alex@example.com") is True
