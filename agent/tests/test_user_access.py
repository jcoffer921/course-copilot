import importlib

import pytest
from rest_framework.test import APIClient

from agent.models import UserSettings
from agent.services import entitlements

backfill_module = importlib.import_module("agent.migrations.0028_backfill_access_status_active")

GATED_ROUTES = [
    "/api/dashboard/",
    "/api/courses/cs101/ask/",
    "/api/courses/cs101/quiz/generate/",
    "/api/courses/cs101/grades/",
    "/api/deadlines/",
    "/api/courses/cs101/calendar-sync/",
]


@pytest.mark.django_db
def test_new_usersettings_defaults_to_pending_pilot(django_user_model):
    user = django_user_model.objects.create_user(username="new-user")

    settings = UserSettings.objects.create(user=user)

    assert settings.access_status == UserSettings.ACCESS_PENDING
    assert settings.tier == UserSettings.TIER_PILOT


class _FakeApps:
    """Minimal stand-in for the migration's historical-model registry,
    resolving straight to the real models so the backfill function can be
    exercised without running the full migration graph."""

    def get_model(self, *args):
        from django.contrib.auth.models import User

        if args[-1] == "UserSettings":
            return UserSettings
        return User


@pytest.mark.django_db
def test_backfill_activates_existing_usersettings_row(django_user_model):
    user = django_user_model.objects.create_user(username="existing-user")
    settings = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_PENDING)

    backfill_module.backfill_active(_FakeApps(), None)

    settings.refresh_from_db()
    assert settings.access_status == UserSettings.ACCESS_ACTIVE


@pytest.mark.django_db
def test_backfill_creates_active_row_for_user_with_none(django_user_model):
    user = django_user_model.objects.create_user(username="no-settings-user")
    assert not UserSettings.objects.filter(user=user).exists()

    backfill_module.backfill_active(_FakeApps(), None)

    settings = UserSettings.objects.get(user=user)
    assert settings.access_status == UserSettings.ACCESS_ACTIVE


@pytest.mark.django_db
def test_backfill_reverse_resets_to_pending(django_user_model):
    user = django_user_model.objects.create_user(username="reverse-user")
    settings = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)

    backfill_module.reverse_backfill(_FakeApps(), None)

    settings.refresh_from_db()
    assert settings.access_status == UserSettings.ACCESS_PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("route", GATED_ROUTES)
def test_pending_user_gets_403_on_every_gated_route(django_user_model, route):
    user = django_user_model.objects.create_user(username="pending-api-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_PENDING)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(route)

    assert response.status_code == 403


@pytest.mark.django_db
def test_active_user_gets_200_on_dashboard(django_user_model):
    """An active user is unaffected by the new gate."""
    user = django_user_model.objects.create_user(username="active-api-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/dashboard/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_suspended_mid_session_is_rejected_on_next_request(django_user_model):
    """A user flipped to suspended mid-session is rejected on their very
    next request using the same session/authentication — not merely
    prevented from signing in again."""
    user = django_user_model.objects.create_user(username="suspend-me")
    settings = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get("/api/dashboard/").status_code == 200

    settings.access_status = UserSettings.ACCESS_SUSPENDED
    settings.save(update_fields=["access_status"])

    assert client.get("/api/dashboard/").status_code == 403


@pytest.mark.django_db
def test_profile_payload_features_match_entitlements(django_user_model):
    from agent.views import _profile_payload

    user = django_user_model.objects.create_user(username="profile-features-user")
    settings = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, tier=UserSettings.TIER_PILOT)

    payload = _profile_payload(user)

    assert payload["access_status"] == UserSettings.ACCESS_ACTIVE
    assert payload["tier"] == UserSettings.TIER_PILOT
    assert payload["features"] == sorted(entitlements.features_for_tier(settings.tier))


@pytest.mark.django_db
def test_pending_page_view_branches_on_access_status(client, django_user_model):
    user = django_user_model.objects.create_user(username="pending-page-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_PENDING)
    client.force_login(user)

    response = client.get("/accounts/pending/")
    assert response.status_code == 200
    assert b"Sign out" in response.content

    UserSettings.objects.filter(user=user).update(access_status=UserSettings.ACCESS_ACTIVE)

    response = client.get("/accounts/pending/")
    assert response.status_code == 302
    assert response.url == "/dashboard/"


@pytest.mark.django_db
def test_pending_user_can_still_reach_logout(client, django_user_model):
    """The access gate must never trap a pending/suspended user — sign-out
    always stays reachable, and never redirect-loops through the pending
    page."""
    user = django_user_model.objects.create_user(username="pending-logout-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_PENDING)
    client.force_login(user)

    response = client.post("/accounts/logout/")

    assert response.status_code == 302
    assert response.url == "/"
