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

import uuid

from . import storage


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
                if value is not None:
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
