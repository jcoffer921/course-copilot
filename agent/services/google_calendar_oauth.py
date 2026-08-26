"""Optional Google Calendar OAuth flow, separate from identity sign-in."""

import os
from datetime import timezone as dt_timezone

from google_auth_oauthlib.flow import Flow


CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET environment variables are not set")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def build_flow(redirect_uri: str, state: str = None, code_verifier: str = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=CALENDAR_SCOPES,
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = redirect_uri
    return flow


def save_connection(user, credentials):
    """Persist optional Calendar credentials only after explicit consent."""
    from agent.models import GoogleCalendarConnection

    expiry = credentials.expiry
    if expiry is None:
        raise ValueError("Google Calendar authorization did not include token expiry")
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=dt_timezone.utc)

    existing = GoogleCalendarConnection.objects.filter(user=user).first()
    refresh_token = credentials.refresh_token or (existing.refresh_token if existing else None)
    if not refresh_token:
        raise ValueError("Google Calendar authorization did not return a refresh token")

    connection, _ = GoogleCalendarConnection.objects.update_or_create(
        user=user,
        defaults={
            "access_token": credentials.token,
            "refresh_token": refresh_token,
            "token_expiry": expiry,
        },
    )
    return connection


def disconnect(user) -> None:
    from agent.models import GoogleCalendarConnection

    GoogleCalendarConnection.objects.filter(user=user).delete()
