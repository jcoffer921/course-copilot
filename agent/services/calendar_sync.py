"""
Pushes individual syllabus deadlines into the signed-in user's real Google
Calendar, one event at a time. Distinct from reminders.py, which only
reads/browses deadlines and never writes anywhere.
"""

import logging
import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import storage

logger = logging.getLogger(__name__)


class AlreadySyncedError(Exception):
    """Raised when a (date, title) deadline has already been pushed to
    Google Calendar for this course — the UI's own synced state should
    normally prevent this call from happening at all; this is the
    server-side guard against a stale-UI or race-condition double-push."""


class CalendarAuthError(Exception):
    """Raised when the signed-in user's stored Google credentials can't be
    refreshed (revoked access, deleted consent, etc.) — callers should
    surface this as a clear, actionable message, not a raw 500."""


class CalendarNotConnectedError(CalendarAuthError):
    """Raised when optional Google Calendar authorization is absent."""


def get_credentials(connection) -> Credentials:
    """Builds a Credentials object from the stored tokens, refreshing (and
    persisting the refresh back onto google_account) if expired.

    google-auth's Credentials.expiry is a naive UTC datetime (same
    convention documented in agent/services/google_oauth.py's
    get_or_create_account) — Django's token_expiry field is timezone-aware,
    so tzinfo is stripped going in and re-attached going out."""
    expiry = connection.token_expiry
    if expiry.tzinfo is not None:
        expiry = expiry.replace(tzinfo=None)

    credentials = Credentials(
        token=connection.access_token,
        refresh_token=connection.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
        expiry=expiry,
    )

    if credentials.expired:
        try:
            credentials.refresh(GoogleAuthRequest())
        except RefreshError as e:
            raise CalendarAuthError(
                "Could not connect to Google Calendar — try signing out and back in."
            ) from e

        connection.access_token = credentials.token
        new_expiry = credentials.expiry
        connection.token_expiry = (
            new_expiry.replace(tzinfo=dt_timezone.utc) if new_expiry.tzinfo is None else new_expiry
        )
        connection.save(update_fields=["access_token", "token_expiry", "updated_at"])

    return credentials


def add_deadline_to_calendar(user, course_id: str, date: str, title: str, event_type: str) -> dict:
    """Pushes one deadline into the signed-in user's Google Calendar as an
    all-day event, and records it so it's never pushed twice. Raises
    AlreadySyncedError if (date, title) is already recorded for this
    course, or CalendarAuthError if the stored Google credentials can't be
    refreshed. Returns {"google_event_id": "..."}."""
    from agent.models import GoogleCalendarConnection

    already_synced = storage.read_calendar_sync(course_id, user=user)
    if any(r["date"] == date and r["title"] == title for r in already_synced):
        raise AlreadySyncedError(f"'{title}' on {date} is already on your Google Calendar")

    try:
        connection = user.google_calendar_connection
    except GoogleCalendarConnection.DoesNotExist as e:
        raise CalendarNotConnectedError("Connect Google Calendar in Settings before syncing events.") from e

    credentials = get_credentials(connection)

    start_date = datetime.strptime(date, "%Y-%m-%d").date()
    end_date = (start_date + timedelta(days=1)).isoformat()

    try:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        event = service.events().insert(
            calendarId="primary",
            body={
                "summary": f"{title} — {course_id.upper()}",
                "description": f"{event_type.capitalize()} for {course_id.upper()}, tracked in OnTrack.",
                "start": {"date": date},
                "end": {"date": end_date},
            },
        ).execute()
    except (HttpError, RefreshError, OSError) as e:
        # Covers both a pre-emptive refresh failure (handled above in
        # get_credentials) and a *lazy* one — the client library also
        # refreshes on a 401 response inside .execute() itself, e.g. if the
        # user revoked OnTrack's access after the stored token was minted
        # but before it looked expired. Also covers rate limits/Google 5xx
        # (HttpError) and network-layer failures (OSError). The raw
        # exception text isn't surfaced to the client — same discipline as
        # auth_views.py's OAuth error handling.
        logger.exception("Google Calendar API call failed")
        raise CalendarAuthError(
            "Could not connect to Google Calendar — try signing out and back in."
        ) from e

    storage.append_calendar_sync_record(course_id, {
        "date": date, "title": title, "type": event_type,
        "google_event_id": event["id"], "synced_at": timezone.now().isoformat(),
    }, user=user)

    return {"google_event_id": event["id"]}
