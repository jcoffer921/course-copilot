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
def test_google_login_redirects_to_google_and_saves_state(client):
    with patch("agent.auth_views.google_oauth.build_flow") as build_flow:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?mock=1", "state-xyz")
        build_flow.return_value = mock_flow

        response = client.get("/accounts/login/")

    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/")
    assert client.session["google_oauth_state"] == "state-xyz"


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
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com"}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 302
    assert response.url == "/"
    assert GoogleAccount.objects.filter(google_sub="sub-123").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_google_callback_rejects_disallowed_email_and_creates_no_account(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "jordan@example.com")
    session = client.session
    session["google_oauth_state"] = "expected-state"
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = _mock_flow_with_credentials()
        verify_id_token.return_value = {"sub": "sub-999", "email": "stranger@example.com"}

        response = client.get("/accounts/callback/?state=expected-state&code=abc")

    assert response.status_code == 403
    assert not GoogleAccount.objects.filter(google_sub="sub-999").exists()
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
        verify_id_token.return_value = {"sub": "sub-123", "email": "jordan@example.com"}
        client.get("/accounts/callback/?state=expected-state&code=abc")
    assert "_auth_user_id" in client.session

    response = client.get("/accounts/logout/")

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session
