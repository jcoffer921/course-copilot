"""
Unit tests for agent.services.profiles.build_profile's Google Calendar
connection state — specifically that "never connected" and "connected once,
now lapsed" are distinguishable, since the UI needs different copy for each
(see calendar_connection_lapsed in profiles.py).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.models import GoogleCalendarConnection
from agent.services import google_calendar_oauth, profiles


@pytest.mark.django_db
def test_never_connected_user_is_not_lapsed(django_user_model):
    user = django_user_model.objects.create_user(username="never-connected")

    profile = profiles.build_profile(user)

    assert profile["calendar_connected"] is False
    assert profile["calendar_connection_lapsed"] is False


@pytest.mark.django_db
def test_actively_connected_user_is_not_lapsed(django_user_model):
    user = django_user_model.objects.create_user(username="actively-connected")
    GoogleCalendarConnection.objects.create(
        user=user, access_token="tok", refresh_token="refresh",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    profile = profiles.build_profile(user)

    assert profile["calendar_connected"] is True
    assert profile["calendar_connection_lapsed"] is False


@pytest.mark.django_db
def test_grant_failure_is_reported_as_lapsed_not_never_connected(django_user_model):
    user = django_user_model.objects.create_user(username="lapsed-connection")
    GoogleCalendarConnection.objects.create(
        user=user, access_token="tok", refresh_token="refresh",
        token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
        grant_failed_at=datetime.now(timezone.utc),
    )

    profile = profiles.build_profile(user)

    assert profile["calendar_connected"] is False
    assert profile["calendar_connection_lapsed"] is True


@pytest.mark.django_db
def test_reconnecting_after_a_lapsed_grant_clears_the_lapsed_flag(django_user_model):
    # The full round trip: lapsed -> successful reconnect -> not lapsed. If
    # save_connection ever stopped clearing grant_failed_at, the banner/status
    # text would keep saying "needs reconnecting" through a working connection.
    user = django_user_model.objects.create_user(username="lapsed-then-reconnected")
    GoogleCalendarConnection.objects.create(
        user=user, access_token="stale", refresh_token="stale-refresh",
        token_expiry=datetime.now(timezone.utc) - timedelta(hours=1),
        grant_failed_at=datetime.now(timezone.utc),
    )
    assert profiles.build_profile(user)["calendar_connection_lapsed"] is True

    google_calendar_oauth.save_connection(user, SimpleNamespace(
        token="fresh-access", refresh_token="fresh-refresh",
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    ))

    # Re-fetched deliberately: build_profile above cached the (lapsed)
    # reverse OneToOne relation on this same in-memory `user`, same as
    # Django would cache it within a single real request — but a real
    # reconnect and the profile read that follows are two separate HTTP
    # requests, each getting its own fresh `user` from the DB. Reusing the
    # cached instance here would pass or fail on a staleness artifact that
    # has nothing to do with whether save_connection actually clears the
    # flag in the database.
    user = django_user_model.objects.get(pk=user.pk)
    profile = profiles.build_profile(user)
    assert profile["calendar_connected"] is True
    assert profile["calendar_connection_lapsed"] is False
