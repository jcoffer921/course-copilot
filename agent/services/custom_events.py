"""
Manually-added deadlines/events — course-specific or general (course_id
None, e.g. holidays) — full CRUD. Distinct from syllabus-extracted dates,
which are read-only here and owned entirely by syllabus extraction. Lives
in its own top-level custom_events.json (not per-course) rather than
syllabus.json, which stays purely extraction-derived. Google Calendar sync
for custom events lives here too (sync_event_to_calendar, added in a later
task) — it reuses calendar_sync.py's credential-refresh logic rather than
duplicating it, since a custom event's sync status is tracked inline on
the event itself, not in calendar_sync.py's per-course calendar_sync.json.
"""

import logging
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from . import calendar_sync, storage

logger = logging.getLogger(__name__)


class EventNotFoundError(Exception):
    """Raised when event_id doesn't match any entry in custom_events.json."""


def list_events() -> list:
    return storage.read_custom_events()


def create_event(course_id, date: str, time: str, title: str, event_type: str) -> dict:
    from django.utils import timezone

    if event_type not in storage.VALID_DATE_TYPES:
        raise ValueError(f"'{event_type}' isn't a valid type (valid: {sorted(storage.VALID_DATE_TYPES)})")

    events = storage.read_custom_events()
    event = {
        "id": uuid.uuid4().hex, "course_id": course_id, "date": date, "time": time,
        "title": title, "type": event_type,
        "synced": False, "google_event_id": None, "synced_at": None,
        "created_at": timezone.now().isoformat(),
    }
    events.append(event)
    storage.write_custom_events(events)
    return event


def update_event(event_id: str, **fields) -> dict:
    if fields.get("type") is not None and fields["type"] not in storage.VALID_DATE_TYPES:
        raise ValueError(f"'{fields['type']}' isn't a valid type (valid: {sorted(storage.VALID_DATE_TYPES)})")

    events = storage.read_custom_events()
    for event in events:
        if event["id"] == event_id:
            for key, value in fields.items():
                event[key] = value
            storage.write_custom_events(events)
            return event
    raise EventNotFoundError(f"no custom event '{event_id}'")


def delete_event(event_id: str) -> None:
    events = storage.read_custom_events()
    remaining = [e for e in events if e["id"] != event_id]
    if len(remaining) == len(events):
        raise EventNotFoundError(f"no custom event '{event_id}'")
    storage.write_custom_events(remaining)


def sync_event_to_calendar(user, event_id: str) -> dict:
    """Pushes one custom event into the signed-in user's Google Calendar —
    all-day if it has no time, a real timed event (1-hour duration,
    settings.TIME_ZONE) if it does. Records the result directly on the
    event itself (not in calendar_sync.py's per-course calendar_sync.json
    — a general event has no course to key that file by). Raises
    AlreadySyncedError if already synced, EventNotFoundError if event_id
    doesn't exist, or CalendarAuthError if the stored Google credentials
    can't be used."""
    from agent.models import GoogleAccount

    events = storage.read_custom_events()
    event = next((e for e in events if e["id"] == event_id), None)
    if event is None:
        raise EventNotFoundError(f"no custom event '{event_id}'")
    if event["synced"]:
        raise calendar_sync.AlreadySyncedError(f"'{event['title']}' is already on your Google Calendar")

    try:
        google_account = user.google_account
    except GoogleAccount.DoesNotExist as e:
        raise calendar_sync.CalendarAuthError("Sign in with Google to add deadlines to your calendar.") from e

    credentials = calendar_sync.get_credentials(google_account)

    if event["time"]:
        start_dt = datetime.strptime(f"{event['date']} {event['time']}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(hours=1)
        body_dates = {
            "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": settings.TIME_ZONE},
            "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": settings.TIME_ZONE},
        }
    else:
        start_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        end_date = (start_date + timedelta(days=1)).isoformat()
        body_dates = {"start": {"date": event["date"]}, "end": {"date": end_date}}

    course_label = event["course_id"].upper() if event["course_id"] else "General"

    try:
        service = calendar_sync.build("calendar", "v3", credentials=credentials, cache_discovery=False)
        created = service.events().insert(
            calendarId="primary",
            body={
                "summary": f"{event['title']} — {course_label}",
                "description": f"{event['type'].capitalize()} — added manually in OnTrack.",
                **body_dates,
            },
        ).execute()
    except (HttpError, RefreshError, OSError) as e:
        logger.exception("Google Calendar API call failed")
        raise calendar_sync.CalendarAuthError(
            "Could not connect to Google Calendar — try signing out and back in."
        ) from e

    from django.utils import timezone as django_timezone
    event["synced"] = True
    event["google_event_id"] = created["id"]
    event["synced_at"] = django_timezone.now().isoformat()
    storage.write_custom_events(events)

    return {"google_event_id": created["id"]}
