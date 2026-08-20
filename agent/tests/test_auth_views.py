from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.models import GoogleAccount


def _mock_flow_with_credentials():
    """A MagicMock Flow whose .credentials has real (non-Mock) values for
    every attribute get_or_create_account touches — a bare MagicMock()
    there would fail when Django tries to save token_expiry to the DB."""
    mock_flow = MagicMock()
    mock_flow.credentials = MagicMock(
        id_token="fake-id-token", token="access-tok", refresh_token="refresh-tok",
        expiry=datetime(2026, 12, 31, 0, 0, 0),
    )
    return mock_flow


@pytest.mark.django_db
def test_google_login_page_renders_sign_in_button(client):
    response = client.get("/accounts/login/")

    assert response.status_code == 200
    assert b"/accounts/login/start/" in response.content
    assert b"Sign in with Google" in response.content


@pytest.mark.django_db
def test_google_login_page_redirects_authenticated_user_to_ontrack(client, django_user_model):
    user = django_user_model.objects.create_user(username="already-signed-in")
    client.force_login(user)

    response = client.get("/accounts/login/")

    assert response.status_code == 302
    assert response.url == "/"


@pytest.mark.django_db
def test_google_login_start_redirects_to_google_and_saves_state(client):
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?mock=1", "state-xyz")
        mock_flow.code_verifier = "generated-verifier"
        build_flow.return_value = mock_flow

        response = client.get("/accounts/login/start/")

    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/")
    assert client.session["google_oauth_state"] == "state-xyz"
    assert client.session["google_oauth_code_verifier"] == "generated-verifier"


@pytest.mark.django_db
def test_google_callback_passes_saved_code_verifier_to_build_flow(client, monkeypatch):
    """The PKCE code_verifier google-auth-oauthlib generates during
    authorization_url() (login-start leg) must be the one used when
    fetch_token() runs on the callback's separately-constructed Flow —
    otherwise Google's token endpoint rejects the exchange with
    'invalid_grant: Missing code verifier'."""
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session["google_oauth_code_verifier"] = "saved-verifier-value"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com", "email_verified": True}

        client.get("/accounts/callback/?state=expected-state&code=abc")

    assert build_flow.call_args.kwargs.get("code_verifier") == "saved-verifier-value"
    assert "google_oauth_code_verifier" not in client.session


@pytest.mark.django_db
def test_google_callback_rejects_mismatched_state(client):
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    response = client.get("/accounts/callback/?state=wrong-state&code=abc")

    assert response.status_code == 400


@pytest.mark.django_db
def test_google_callback_creates_account_and_logs_in_allowed_email(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com", "email_verified": True}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 302
    assert response.url == "/"
    assert GoogleAccount.objects.filter(google_sub="sub-123").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_google_callback_returns_400_when_fetch_token_fails(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        mock_flow = MagicMock()
        mock_flow.fetch_token.side_effect = Exception("invalid_grant")
        build_flow.return_value = mock_flow

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 400
    verify_id_token.assert_not_called()
    assert not GoogleAccount.objects.exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_callback_returns_400_when_verify_id_token_fails(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.side_effect = Exception("invalid token")

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 400
    assert not GoogleAccount.objects.exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_callback_rejects_disallowed_email_and_creates_no_account(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-999", "email": "stranger@example.com", "email_verified": True}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 302
    assert response.url == "/accounts/login/"
    assert not GoogleAccount.objects.filter(google_sub="sub-999").exists()
    assert "_auth_user_id" not in client.session

    followup = client.get(response.url)
    assert b"approved list" in followup.content


@pytest.mark.django_db
def test_google_callback_returns_400_when_email_claim_missing(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email_verified": True}  # no "email"

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 400
    assert not GoogleAccount.objects.exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_callback_returns_400_when_sub_claim_missing(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"email": "jordan@example.com", "email_verified": True}  # no "sub"

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 400
    assert not GoogleAccount.objects.exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_callback_returns_400_when_email_not_verified(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com", "email_verified": False}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 400
    assert not GoogleAccount.objects.exists()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_logout_clears_session(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com", "email_verified": True}
        client.get("/accounts/callback/?state=expected-state&code=abc")
    assert "_auth_user_id" in client.session

    response = client.post("/accounts/logout/")

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_logout_rejects_get(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com", "email_verified": True}
        client.get("/accounts/callback/?state=expected-state&code=abc")
    assert "_auth_user_id" in client.session

    response = client.get("/accounts/logout/")

    assert response.status_code == 405
    assert "_auth_user_id" in client.session
