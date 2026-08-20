from datetime import datetime
from types import SimpleNamespace

import pytest

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


def _fake_credentials(token="tok", refresh_token="refresh", expiry=None):
    """Mimics google.oauth2.credentials.Credentials' relevant attributes.
    Real Credentials.expiry is a naive UTC datetime — reproduced here since
    get_or_create_account must handle that (see Step 4)."""
    return SimpleNamespace(
        token=token, refresh_token=refresh_token,
        expiry=expiry or datetime(2026, 12, 31, 0, 0, 0),
    )


@pytest.mark.django_db
def test_get_or_create_account_creates_new_user_and_account():
    from agent.models import GoogleAccount

    user = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials())

    assert user.email == "jordan@example.com"
    account = GoogleAccount.objects.get(google_sub="sub-123")
    assert account.user == user
    assert account.email == "jordan@example.com"
    assert account.access_token == "tok"
    assert account.token_expiry.tzinfo is not None  # naive google-auth datetime made tz-aware


@pytest.mark.django_db
def test_get_or_create_account_returns_existing_user_on_second_login():
    from agent.models import GoogleAccount

    first = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(token="old"))
    second = google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(token="new"))

    assert first.pk == second.pk
    assert GoogleAccount.objects.filter(google_sub="sub-123").count() == 1
    assert GoogleAccount.objects.get(google_sub="sub-123").access_token == "new"


@pytest.mark.django_db
def test_get_or_create_account_keeps_existing_refresh_token_if_google_omits_a_new_one():
    from agent.models import GoogleAccount

    google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(refresh_token="original-refresh"))
    google_oauth.get_or_create_account("sub-123", "jordan@example.com", _fake_credentials(refresh_token=None))

    assert GoogleAccount.objects.get(google_sub="sub-123").refresh_token == "original-refresh"
