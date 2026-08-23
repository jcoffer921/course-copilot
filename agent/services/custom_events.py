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


def _coerce_event_type(event_type: str) -> str:
    raw = str(event_type or "other").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in storage.VALID_DATE_TYPES or raw in storage.LEGACY_DATE_TYPE_MAP:
        return storage.normalize_date_type(raw)
    raise ValueError(f"'{event_type}' isn't a valid type (valid: {sorted(storage.VALID_DATE_TYPES)})")


def _validate_time_range(start_time, end_time) -> None:
    if end_time and not start_time:
        raise ValueError("end_time requires time")
    if start_time and end_time:
        try:
            start = datetime.strptime(start_time, "%H:%M").time()
            end = datetime.strptime(end_time, "%H:%M").time()
        except ValueError as e:
            raise ValueError("time and end_time must be HH:MM") from e
        if end <= start:
            raise ValueError("end_time must be later than time")


def list_events(user=None) -> list:
    return storage.read_custom_events(user=user)


def create_event(
    course_id,
    date: str,
    time: str,
    title: str,
    event_type: str,
    user=None,
    replaces_syllabus_key: str = None,
    end_time: str = None,
    completed: bool = False,
) -> dict:
    from django.utils import timezone

    event_type = _coerce_event_type(event_type)
    _validate_time_range(time, end_time)

    events = storage.read_custom_events(user=user)
    event = {
        "id": uuid.uuid4().hex, "course_id": course_id, "date": date, "time": time, "end_time": end_time,
        "title": title, "type": event_type,
        "replaces_syllabus_key": replaces_syllabus_key,
        "completed": bool(completed),
        "synced": False, "google_event_id": None, "synced_at": None,
        "created_at": timezone.now().isoformat(),
    }
    events.append(event)
    storage.write_custom_events(events, user=user)
    return event


def update_event(event_id: str, user=None, **fields) -> dict:
    if fields.get("type") is not None:
        fields["type"] = _coerce_event_type(fields["type"])

    events = storage.read_custom_events(user=user)
    for event in events:
        if event["id"] == event_id:
            start_time = fields["time"] if "time" in fields else event.get("time")
            end_time = fields["end_time"] if "end_time" in fields else event.get("end_time")
            _validate_time_range(start_time, end_time)
            for key, value in fields.items():
                event[key] = value
            storage.write_custom_events(events, user=user)
            return event
    raise EventNotFoundError(f"no custom event '{event_id}'")


def delete_event(event_id: str, user=None) -> None:
    events = storage.read_custom_events(user=user)
    remaining = [e for e in events if e["id"] != event_id]
    if len(remaining) == len(events):
        raise EventNotFoundError(f"no custom event '{event_id}'")
    storage.write_custom_events(remaining, user=user)


def delete_events_for_course(course_id: str, user=None, all_users: bool = False) -> None:
    """Removes every custom event tied to course_id — called when a course
    itself is deleted, so its custom events don't linger as orphaned rows
    labeled with a course_id that no longer exists. General events
    (course_id=None) and other courses' events are untouched. A no-op if
    none match, unlike delete_event, since this is cleanup triggered by an
    unrelated action (course deletion), not a direct user request to delete
    a specific event that must exist."""
    if all_users:
        from agent.models import CustomEvent
        CustomEvent.objects.filter(course_id=course_id).delete()
        return
    events = storage.read_custom_events(user=user)
    remaining = [e for e in events if e["course_id"] != course_id]
    if len(remaining) != len(events):
        storage.write_custom_events(remaining, user=user)


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

    events = storage.read_custom_events(user=user)
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
        if event.get("end_time"):
            end_dt = datetime.strptime(f"{event['date']} {event['end_time']}", "%Y-%m-%d %H:%M")
        else:
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
    storage.write_custom_events(events, user=user)

    return {"google_event_id": created["id"]}
