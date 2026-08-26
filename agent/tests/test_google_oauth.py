import pytest

from agent.services import google_oauth


def test_sign_in_scopes_are_identity_only():
    assert google_oauth.OAUTH_SCOPES == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]


def test_is_email_allowed_matches_case_insensitively(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "Jordan@Example.com,alex@example.com")

    assert google_oauth.is_email_allowed("jordan@example.com") is True
    assert google_oauth.is_email_allowed("JORDAN@EXAMPLE.COM") is True


def test_is_email_allowed_rejects_unlisted_email(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")

    assert google_oauth.is_email_allowed("stranger@example.com") is False


def test_is_email_allowed_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("ONTRACK_ADMISSION_MODE", raising=False)
    monkeypatch.delenv("ALLOWED_GOOGLE_EMAILS", raising=False)

    assert google_oauth.is_email_allowed("jordan@example.com") is False


def test_open_admission_accepts_any_verified_identity(monkeypatch):
    monkeypatch.setenv("ONTRACK_ADMISSION_MODE", "open")
    monkeypatch.delenv("ALLOWED_GOOGLE_EMAILS", raising=False)

    assert google_oauth.is_email_allowed("student@any-domain.example") is True


def test_unknown_admission_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("ONTRACK_ADMISSION_MODE", "typo")

    assert google_oauth.is_email_allowed("student@example.com") is False


def test_is_email_allowed_ignores_whitespace_around_entries(monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", " jordan@example.com , alex@example.com ")

    assert google_oauth.is_email_allowed("alex@example.com") is True


@pytest.mark.django_db
def test_get_or_create_account_creates_new_user_and_account():
    from agent.models import GoogleAccount

    user = google_oauth.get_or_create_account("sub-123", "jordan@example.com")

    assert user.email == "jordan@example.com"
    account = GoogleAccount.objects.get(google_sub="sub-123")
    assert account.user == user
    assert account.email == "jordan@example.com"


@pytest.mark.django_db
def test_get_or_create_account_stores_google_profile_name():
    user = google_oauth.get_or_create_account(
        "sub-123", "jordan@example.com", name="Jordan Lee"
    )

    assert user.first_name == "Jordan Lee"


@pytest.mark.django_db
def test_get_or_create_account_returns_existing_user_on_second_login():
    from agent.models import GoogleAccount

    first = google_oauth.get_or_create_account("sub-123", "jordan@example.com")
    second = google_oauth.get_or_create_account("sub-123", "jordan@example.com")

    assert first.pk == second.pk
    assert GoogleAccount.objects.filter(google_sub="sub-123").count() == 1


def test_build_flow_carries_a_passed_in_code_verifier(monkeypatch):
    """google-auth-oauthlib's Flow auto-generates a PKCE code_verifier inside
    authorization_url() when none is supplied. Since the login-start leg and
    the callback leg build two separate Flow objects, the callback's Flow
    must be constructed with the SAME code_verifier the login-start leg
    generated, or Google's token endpoint rejects the exchange with
    'invalid_grant: Missing code verifier' (a real failure this test guards
    against — see agent/auth_views.py's session round-trip)."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")

    flow = google_oauth.build_flow("http://127.0.0.1:8000/accounts/callback/", code_verifier="saved-verifier-value")

    assert flow.code_verifier == "saved-verifier-value"
