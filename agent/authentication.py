"""
DRF's status-code choice (401 vs 403) for an unauthenticated request depends
on whether the first configured authenticator's authenticate_header() returns
a truthy value — see DEFAULT_AUTHENTICATION_CLASSES in settings.py.
"""

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission


class SessionAuthenticationWith401(SessionAuthentication):
    """Stock SessionAuthentication returns None from authenticate_header(),
    which makes DRF respond 403 to an unauthenticated request instead of the
    conventional 401. This subclass adds only that header — no new
    authentication capability, still session-cookie-only, still no
    password-based auth path."""

    def authenticate_header(self, request):
        return "Session"


def user_access_status(user) -> str:
    """Resolves a signed-in user's UserSettings.access_status, creating the
    row (defaulting to pending) if this is their first request that needs
    it. The single place both the API permission class and the page-gating
    middleware read entitlement state from."""
    from .models import UserSettings

    settings_row, _ = UserSettings.objects.get_or_create(user=user)
    return settings_row.access_status


def is_access_active(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user_access_status(user) == "active"


def is_pilot_owner(user) -> bool:
    configured_email = str(getattr(settings, "ONTRACK_PILOT_OWNER_EMAIL", "") or "").strip().casefold()
    if not configured_email or not getattr(user, "is_authenticated", False):
        return False
    from django.contrib.auth import get_user_model

    matches = get_user_model().objects.filter(email__iexact=configured_email, is_active=True)
    return matches.count() == 1 and matches.filter(pk=user.pk).exists()


class ActiveAccessPermission(BasePermission):
    """Rejects every request from a signed-in user whose account isn't
    active — pending approval or suspended. Wired into
    DEFAULT_PERMISSION_CLASSES so it applies to every APIView without
    per-view edits; IsAuthenticated runs first, so this only ever sees an
    already-authenticated user."""

    def has_permission(self, request, view):
        return is_access_active(request.user)


class PilotOwnerPermission(BasePermission):
    """Conceal the private analytics surface from every non-owner account."""

    def has_permission(self, request, view):
        if not is_pilot_owner(request.user):
            raise NotFound()
        return True
