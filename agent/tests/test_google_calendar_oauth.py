from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

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
def test_save_connection_reconnect_updates_existing_row_and_clears_grant_failed_at(django_user_model):
    from django.utils import timezone as django_timezone

    user = django_user_model.objects.create_user(username="reconnect-user")
    original = GoogleCalendarConnection.objects.create(
        user=user, access_token="stale", refresh_token="stale-refresh",
        token_expiry=datetime(2026, 1, 1, tzinfo=timezone.utc),
        grant_failed_at=django_timezone.now(),
    )
    credentials = SimpleNamespace(token="fresh-access", refresh_token="fresh-refresh", expiry=datetime(2026, 12, 31))

    connection = google_calendar_oauth.save_connection(user, credentials)

    assert connection.pk == original.pk
    assert GoogleCalendarConnection.objects.filter(user=user).count() == 1
    assert connection.access_token == "fresh-access"
    assert connection.refresh_token == "fresh-refresh"
    assert connection.grant_failed_at is None


@pytest.mark.django_db
def test_calendar_connect_requires_authentication(client):
    response = client.get("/accounts/calendar/connect/")

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.django_db
@override_settings(ONTRACK_BASE_URL="https://ontrack.example")
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
    build_flow.assert_called_once_with("https://ontrack.example/accounts/calendar/callback/")
    assert flow.authorization_url.call_args.kwargs == {
        "access_type": "offline",
        "prompt": "consent",
    }


@pytest.mark.django_db
@override_settings(ONTRACK_BASE_URL="https://ontrack.example")
def test_calendar_callback_reuses_the_same_canonical_redirect_uri(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar-callback-user")
    client.force_login(user)
    session = client.session
    session["google_calendar_oauth_state"] = "state"
    session["google_calendar_oauth_code_verifier"] = "verifier"
    session.save()

    with patch("agent.auth_views.google_calendar_oauth.build_flow") as build_flow:
        flow = MagicMock()
        flow.credentials = SimpleNamespace(token="a", refresh_token="r", expiry=datetime(2026, 12, 31))
        build_flow.return_value = flow
        with patch("agent.auth_views.google_calendar_oauth.save_connection"):
            response = client.get("/accounts/calendar/callback/?state=state&code=abc")

    assert response.status_code == 302
    build_flow.assert_called_once_with(
        "https://ontrack.example/accounts/calendar/callback/",
        state="state",
        code_verifier="verifier",
    )


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
def test_calendar_callback_returns_to_connected_apps_after_oauth_failure(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar-oauth-failure-user")
    client.force_login(user)
    session = client.session
    session["google_calendar_oauth_state"] = "state"
    session["google_calendar_oauth_code_verifier"] = "verifier"
    session.save()

    with patch("agent.auth_views.google_calendar_oauth.build_flow") as build_flow:
        flow = MagicMock()
        flow.fetch_token.side_effect = RuntimeError("sensitive provider response")
        build_flow.return_value = flow

        response = client.get("/accounts/calendar/callback/?state=state&code=abc", follow=True)

    assert response.redirect_chain == [("/settings/apps/", 302)]
    assert b"Google Calendar couldn&#x27;t be connected. Please try again." in response.content


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
    assert response.url == "/settings/apps/"
    assert not GoogleCalendarConnection.objects.filter(user=owner).exists()
    assert GoogleCalendarConnection.objects.filter(user=other).exists()
