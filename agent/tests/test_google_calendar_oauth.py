from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.models import GoogleCalendarConnection
from agent.services import google_calendar_oauth


def test_calendar_scope_is_separate_and_calendar_only():
    assert google_calendar_oauth.CALENDAR_SCOPES == [
        "https://www.googleapis.com/auth/calendar.events"
    ]


@pytest.mark.django_db
def test_save_connection_persists_optional_calendar_credentials(django_user_model):
    user = django_user_model.objects.create_user(username="calendar-user")
    credentials = SimpleNamespace(
        token="access",
        refresh_token="refresh",
        expiry=datetime(2026, 12, 31),
    )

    connection = google_calendar_oauth.save_connection(user, credentials)

    assert connection.user == user
    assert connection.refresh_token == "refresh"
    assert connection.token_expiry.tzinfo is not None


@pytest.mark.django_db
def test_calendar_connect_requires_authentication(client):
    response = client.get("/accounts/calendar/connect/")

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.django_db
def test_calendar_connect_requests_offline_consent(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar-user")
    client.force_login(user)
    with patch("agent.auth_views.google_calendar_oauth.build_flow") as build_flow:
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.com/calendar", "state")
        flow.code_verifier = "verifier"
        build_flow.return_value = flow

        response = client.get("/accounts/calendar/connect/")

    assert response.status_code == 302
    assert flow.authorization_url.call_args.kwargs == {
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }


@pytest.mark.django_db
def test_calendar_callback_fails_closed_without_pkce(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar-user")
    client.force_login(user)
    session = client.session
    session["google_calendar_oauth_state"] = "state"
    session.save()

    with patch("agent.auth_views.google_calendar_oauth.build_flow") as build_flow:
        response = client.get("/accounts/calendar/callback/?state=state&code=abc")

    assert response.status_code == 400
    build_flow.assert_not_called()


@pytest.mark.django_db
def test_calendar_disconnect_is_post_only_and_user_scoped(client, django_user_model):
    owner = django_user_model.objects.create_user(username="owner")
    other = django_user_model.objects.create_user(username="other")
    expiry = datetime(2026, 12, 31, tzinfo=timezone.utc)
    GoogleCalendarConnection.objects.create(user=owner, access_token="a", refresh_token="r", token_expiry=expiry)
    GoogleCalendarConnection.objects.create(user=other, access_token="b", refresh_token="s", token_expiry=expiry)
    client.force_login(owner)

    assert client.get("/accounts/calendar/disconnect/").status_code == 405
    response = client.post("/accounts/calendar/disconnect/")

    assert response.status_code == 302
    assert response.url == "/settings/"
    assert not GoogleCalendarConnection.objects.filter(user=owner).exists()
    assert GoogleCalendarConnection.objects.filter(user=other).exists()
