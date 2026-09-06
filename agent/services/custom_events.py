"""
Manual and study-plan deadlines/events — course-specific or general
(course_id None, e.g. holidays) — full CRUD. Distinct from syllabus-extracted
dates, which are read-only here and owned entirely by confirmed syllabus
content. Google Calendar sync
for custom events lives here too (sync_event_to_calendar, added in a later
task) — it reuses calendar_sync.py's credential-refresh logic rather than
duplicating it, since a custom event's sync status is tracked inline on
the event itself, not in calendar_sync.py's per-course calendar_sync.json.
"""

import logging
import uuid
from datetime import date, datetime, timedelta

from django.conf import settings
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from . import calendar_events, calendar_sync, storage

logger = logging.getLogger(__name__)


class EventNotFoundError(Exception):
    """Raised when event_id doesn't match an owned custom event."""


# Python date.weekday() convention (Monday=0..Sunday=6) — the one shared
# mapping for weekday-abbreviation input, used by create_recurring_events
# (via the API serializer) and ask.py's _recurring_schedule_proposal alike,
# so the two recurring-event entry points can't drift on what "tue" means.
WEEKDAY_ABBREVIATIONS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

VALID_EVENT_SOURCES = {"manual", "study_plan"}
UPDATABLE_FIELDS = {
    "course_id",
    "date",
    "time",
    "end_time",
    "title",
    "type",
    "location",
    "notes",
    "completed",
    "estimated_effort_minutes",
    "source_material_id",
    "synced",
    "google_event_id",
    "synced_at",
}
# Fields that are inherently per-occurrence and must never be copied from one
# series member onto its siblings, even when the caller asked for a
# "following"/"all" bulk edit — each occurrence keeps its own date,
# completion state, effort estimate, source material link, and Google sync
# status regardless of what changed on the anchor event.
SERIES_SCOPES = {"this", "following", "all"}
_SERIES_PROPAGATION_EXCLUDED_FIELDS = {
    "date", "completed", "estimated_effort_minutes", "source_material_id",
    "synced", "google_event_id", "synced_at",
}


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


def _validate_estimated_effort(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("estimated_effort_minutes must be a positive integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as e:
        raise ValueError("estimated_effort_minutes must be a positive integer") from e
    if value < 1:
        raise ValueError("estimated_effort_minutes must be a positive integer")
    return value


def _validate_source_material(user, course_id, material_id):
    if material_id in (None, ""):
        return None
    if not course_id:
        raise ValueError("source_material_id requires course_id")
    from agent.models import CourseMaterial

    material = CourseMaterial.objects.filter(
        user=user,
        course_id=course_id,
        material_id=material_id,
        processing_status=CourseMaterial.STATUS_READY,
    ).first()
    if material is None:
        raise ValueError("source_material_id must identify a ready material in this course")
    return str(material.material_id)


def expand_weekly_dates(start_date: date, end_date: date, weekdays: set[int]) -> list[date]:
    """Every date in [start_date, end_date] (inclusive) whose Python
    date.weekday() (Monday=0..Sunday=6) is in weekdays. Shared by
    create_recurring_events() below and ask.py's Cora-chat recurring-class
    proposal, so both paths expand a "weekly on these days" pattern the
    same way instead of keeping two copies of this loop in sync by hand."""
    if end_date < start_date:
        return []
    dates = []
    current = start_date
    while current <= end_date:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates


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
    estimated_effort_minutes: int = None,
    source_material_id=None,
    source: str = "manual",
    location: str = "",
    notes: str = "",
    series_id: str = None,
) -> dict:
    from django.utils import timezone

    event_type = _coerce_event_type(event_type)
    _validate_time_range(time, end_time)
    if source not in VALID_EVENT_SOURCES:
        raise ValueError("source must be manual or study_plan")
    estimated_effort_minutes = _validate_estimated_effort(estimated_effort_minutes)
    source_material_id = _validate_source_material(user, course_id, source_material_id)

    events = storage.read_custom_events(user=user)
    event_id = uuid.uuid4().hex
    if replaces_syllabus_key:
        calendar_events.validate_syllabus_replacement(user, course_id, replaces_syllabus_key)
        event_id = calendar_events.stable_syllabus_event_id(user, replaces_syllabus_key)
        if any(event.get("id") == event_id for event in events):
            raise ValueError("this syllabus deadline already has an editable replacement")
    event = {
        "id": event_id, "course_id": course_id, "date": date, "time": time, "end_time": end_time,
        "title": title, "type": event_type,
        "location": location,
        "notes": notes,
        "source": source,
        "estimated_effort_minutes": estimated_effort_minutes,
        "source_material_id": source_material_id,
        "replaces_syllabus_key": replaces_syllabus_key,
        "series_id": series_id,
        "completed": bool(completed),
        "synced": False, "google_event_id": None, "synced_at": None,
        "created_at": timezone.now().isoformat(),
    }
    events.append(event)
    storage.write_custom_events(events, user=user)
    return event


def create_recurring_events(
    course_id,
    title: str,
    event_type: str,
    weekdays: set[int],
    start_date: date,
    end_date: date,
    time: str,
    end_time: str = None,
    user=None,
    location: str = "",
    notes: str = "",
) -> dict:
    """Creates one CustomEvent per matching date in [start_date, end_date],
    all sharing a freshly generated series_id so they're later bulk-
    editable/deletable as a group via update_event/delete_event's
    series_scope. Reuses create_event's own validation (time range, event
    type) for every occurrence rather than duplicating it."""
    series_id = uuid.uuid4().hex
    events = [
        create_event(
            course_id, occurrence.isoformat(), time, title, event_type, user=user,
            end_time=end_time, location=location, notes=notes, series_id=series_id,
        )
        for occurrence in expand_weekly_dates(start_date, end_date, weekdays)
    ]
    return {"series_id": series_id, "events": events}


def update_event(event_id: str, user=None, series_scope: str = "this", **fields) -> dict:
    """series_scope="this" (default) is exactly the original single-event
    behavior. "following"/"all" additionally copy a propagation subset of
    fields (everything except _SERIES_PROPAGATION_EXCLUDED_FIELDS) onto the
    anchor's siblings — every other event sharing its series_id, restricted
    to date >= the anchor's own date for "following". Raises ValueError if
    the anchor isn't part of a series at all."""
    if series_scope not in SERIES_SCOPES:
        raise ValueError(f"series_scope must be one of {sorted(SERIES_SCOPES)}")
    unexpected = set(fields) - UPDATABLE_FIELDS
    if unexpected:
        raise ValueError(f"fields cannot be updated: {', '.join(sorted(unexpected))}")
    if fields.get("type") is not None:
        fields["type"] = _coerce_event_type(fields["type"])
    if "estimated_effort_minutes" in fields:
        fields["estimated_effort_minutes"] = _validate_estimated_effort(fields["estimated_effort_minutes"])

    storage.claim_custom_event(event_id, user)
    events = storage.read_custom_events(user=user)
    anchor = next((event for event in events if event["id"] == event_id), None)
    if anchor is None:
        raise EventNotFoundError(f"no custom event '{event_id}'")
    if series_scope != "this" and not anchor.get("series_id"):
        raise ValueError("this event is not part of a recurring series")

    start_time = fields["time"] if "time" in fields else anchor.get("time")
    end_time = fields["end_time"] if "end_time" in fields else anchor.get("end_time")
    _validate_time_range(start_time, end_time)
    course_id = fields["course_id"] if "course_id" in fields else anchor.get("course_id")
    material_id = (
        fields["source_material_id"] if "source_material_id" in fields else anchor.get("source_material_id")
    )
    if material_id:
        fields["source_material_id"] = _validate_source_material(user, course_id, material_id)

    for key, value in fields.items():
        anchor[key] = value

    if series_scope != "this":
        propagated = {k: v for k, v in fields.items() if k not in _SERIES_PROPAGATION_EXCLUDED_FIELDS}
        for event in events:
            if event is anchor or event.get("series_id") != anchor["series_id"]:
                continue
            if series_scope == "following" and event["date"] < anchor["date"]:
                continue
            for key, value in propagated.items():
                event[key] = value

    storage.write_custom_events(events, user=user)
    return anchor


def delete_event(event_id: str, user=None, series_scope: str = "this") -> None:
    """series_scope="this" (default) is exactly the original single-event
    behavior. "following" removes the anchor plus every sibling sharing its
    series_id with date >= the anchor's own date; "all" removes every
    sibling regardless of date. Raises ValueError if the anchor isn't part
    of a series at all."""
    if series_scope not in SERIES_SCOPES:
        raise ValueError(f"series_scope must be one of {sorted(SERIES_SCOPES)}")
    storage.claim_custom_event(event_id, user)
    events = storage.read_custom_events(user=user)
    anchor = next((event for event in events if event["id"] == event_id), None)
    if anchor is None:
        raise EventNotFoundError(f"no custom event '{event_id}'")

    if series_scope == "this":
        remaining = [event for event in events if event["id"] != event_id]
    else:
        if not anchor.get("series_id"):
            raise ValueError("this event is not part of a recurring series")
        if series_scope == "following":
            remaining = [
                event for event in events
                if not (event.get("series_id") == anchor["series_id"] and event["date"] >= anchor["date"])
            ]
        else:
            remaining = [event for event in events if event.get("series_id") != anchor["series_id"]]

    storage.write_custom_events(remaining, user=user)


def delete_events_for_course(course_id: str, user=None) -> None:
    """Removes every custom event tied to course_id — called when a course
    itself is deleted, so its custom events don't linger as orphaned rows
    labeled with a course_id that no longer exists. General events
    (course_id=None) and other courses' events are untouched. A no-op if
    none match, unlike delete_event, since this is cleanup triggered by an
    unrelated action (course deletion), not a direct user request to delete
    a specific event that must exist.

    An authenticated `user` scopes the delete to that user's own rows plus
    legacy (pre-auth, user=NULL) rows for course_id — never every user's
    rows regardless of owner, since course_id is just a string two
    different users' courses can share in a multi-tenant world. There is
    deliberately no all-users escape hatch here: this function is always
    driven by a single user's own course deletion, and an unscoped sweep
    would let one student's delete destroy another's events."""
    from agent.models import CustomEvent

    if getattr(user, "is_authenticated", False):
        storage._scope_user_queryset(CustomEvent.objects.filter(course_id=course_id), user).delete()
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
    from agent.models import GoogleCalendarConnection

    storage.claim_custom_event(event_id, user)
    events = storage.read_custom_events(user=user)
    event = next((e for e in events if e["id"] == event_id), None)
    if event is None:
        raise EventNotFoundError(f"no custom event '{event_id}'")
    if event["synced"]:
        raise calendar_sync.AlreadySyncedError(f"'{event['title']}' is already on your Google Calendar")

    try:
        connection = user.google_calendar_connection
    except GoogleCalendarConnection.DoesNotExist as e:
        raise calendar_sync.CalendarNotConnectedError(
            "Connect Google Calendar in Settings before syncing events."
        ) from e

    credentials = calendar_sync.get_credentials(connection)

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
