"""
DRF's status-code choice (401 vs 403) for an unauthenticated request depends
on whether the first configured authenticator's authenticate_header() returns
a truthy value — see DEFAULT_AUTHENTICATION_CLASSES in settings.py.
"""

from rest_framework.authentication import SessionAuthentication


class SessionAuthenticationWith401(SessionAuthentication):
    """Stock SessionAuthentication returns None from authenticate_header(),
    which makes DRF respond 403 to an unauthenticated request instead of the
    conventional 401. This subclass adds only that header — no new
    authentication capability, still session-cookie-only, still no
    password-based auth path."""

    def authenticate_header(self, request):
        return "Session"
