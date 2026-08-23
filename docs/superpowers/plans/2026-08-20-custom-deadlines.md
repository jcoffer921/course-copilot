# Manually-Added Deadlines + Full Deadlines View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user manually add, edit, and delete deadlines/events (course-specific or general, e.g. holidays) with full CRUD, push them to Google Calendar the same way syllabus deadlines already can, and see every upcoming deadline — not just the next 14 days — in a new "Deadlines" tab.

**Architecture:** A new top-level `courses/custom_events.json` (not per-course, since a general event belongs to no single course) holds every manually-created deadline, each with a stable `id`. `agent/services/custom_events.py` owns CRUD over it and Calendar-sync for it, reusing (not duplicating) the credential-refresh logic already built for syllabus-deadline sync in `agent/services/calendar_sync.py` — that module's `_get_credentials` is promoted to a public `get_credentials` for this reuse. `agent/services/reminders.py` gains `list_all_deadlines()`, merging syllabus-extracted deadlines (unbounded, source-tagged `"syllabus"`) with custom events (source-tagged `"custom"`) into one chronologically-sorted list, which a new `GET /api/deadlines/` serves to a new "Deadlines" nav tab in `ontrack.html`.

**Tech Stack:** Django/DRF (existing patterns: flat-file JSON storage, `sync_to_async`-wrapped async views), the already-installed `google-api-python-client` (existing Calendar sync feature), pytest + pytest-django, DC component templating in `ontrack.html`.

## Global Constraints

- Same type taxonomy as syllabus dates: `exam|assignment|reading|other` (from `storage.VALID_DATE_TYPES`). No new types — a holiday is `type: "other"`.
- `course_id: null` on a custom event means "general" — it must appear in `list_all_deadlines()` regardless of course, matching the design's stated behavior.
- A custom event's `time` field is optional (`"HH:MM"` or `null`). When set and the event is pushed to Google Calendar, it becomes a real timed event (1-hour default duration, using `settings.TIME_ZONE`) instead of all-day.
- Sync state for a custom event lives inline on the event itself (`synced`/`google_event_id`/`synced_at` fields in `custom_events.json`) — NOT in the existing per-course `calendar_sync.json`, which stays exactly as-is and is not touched by this plan.
- Only custom events are editable/deletable. Syllabus-extracted dates are not — nothing in this plan adds edit/delete for them.
- The Dashboard's existing "Upcoming deadlines" panel (14-day window, its own data source, its own sync-status UI) is untouched except for one addition: a "See all →" link to the new Deadlines tab.
- Non-goals (do not build): recurring class schedules, a calendar grid/month view, un-syncing a custom event that's already on Google Calendar, editing a syllabus-extracted date.

---

## Task 1: `custom_events.json` storage + CRUD service

**Files:**
- Modify: `agent/services/storage.py`
- Create: `agent/services/custom_events.py`
- Test: `agent/tests/test_storage_custom_events.py`, `agent/tests/test_custom_events.py`

**Interfaces:**
- Produces: `agent.services.storage.read_custom_events() -> list`, `agent.services.storage.write_custom_events(events: list) -> Path`, `agent.services.storage.CustomEventsStorageError`; `agent.services.custom_events.list_events() -> list`, `agent.services.custom_events.create_event(course_id: str|None, date: str, time: str|None, title: str, event_type: str) -> dict`, `agent.services.custom_events.update_event(event_id: str, **fields) -> dict`, `agent.services.custom_events.delete_event(event_id: str) -> None`, `agent.services.custom_events.EventNotFoundError`

This task has no Google Calendar / API / UI dependency at all — pure CRUD over a new JSON file, independently testable.

- [ ] **Step 1: Write the failing tests for the storage helpers**

Create `agent/tests/test_storage_custom_events.py`:

```python
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_custom_events_returns_empty_list_when_file_absent(isolated_courses_dir):
    assert storage.read_custom_events() == []


def test_write_custom_events_writes_and_reads_back(isolated_courses_dir):
    storage.write_custom_events([
        {"id": "abc123", "course_id": "cs101", "date": "2026-09-01", "time": None, "title": "Study group", "type": "other",
         "synced": False, "google_event_id": None, "synced_at": None, "created_at": "2026-08-20T00:00:00+00:00"},
    ])

    events = storage.read_custom_events()

    assert len(events) == 1
    assert events[0]["id"] == "abc123"
    assert events[0]["title"] == "Study group"


def test_write_custom_events_overwrites_whole_file(isolated_courses_dir):
    storage.write_custom_events([{"id": "a", "course_id": None, "date": "2026-09-01", "time": None, "title": "X", "type": "other",
                                   "synced": False, "google_event_id": None, "synced_at": None, "created_at": "x"}])
    storage.write_custom_events([{"id": "b", "course_id": None, "date": "2026-09-02", "time": None, "title": "Y", "type": "other",
                                   "synced": False, "google_event_id": None, "synced_at": None, "created_at": "x"}])

    events = storage.read_custom_events()

    assert len(events) == 1
    assert events[0]["id"] == "b"


def test_read_custom_events_raises_on_corrupt_json(isolated_courses_dir):
    (isolated_courses_dir / "custom_events.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(storage.CustomEventsStorageError):
        storage.read_custom_events()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_custom_events.py -v`
Expected: FAIL — `AttributeError: module 'agent.services.storage' has no attribute 'read_custom_events'`.

- [ ] **Step 3: Add the storage helpers**

In `agent/services/storage.py`, add this exception class alongside the other `*StorageError` classes (near `CalendarSyncStorageError`):

```python
class CustomEventsStorageError(Exception):
    """Raised when custom_events.json exists but is corrupt."""
```

Then add these two functions anywhere near `read_grades`/`write_grades` (same "directly user-editable, whole-file overwrite" shape):

```python
def read_custom_events() -> list:
    """Returns the list of manually-added deadlines/events, or [] if
    custom_events.json doesn't exist yet — no custom events yet is the
    normal starting state, same convention as trusted_domains.json. Unlike
    every other course JSON file, this one lives at the top level
    (COURSES_DIR itself), not under a specific course_id — a general event
    (course_id=None) has no single course to belong to."""
    path = COURSES_DIR / "custom_events.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CustomEventsStorageError(f"custom_events.json is corrupt: {e}")
    return data.get("events", [])


def write_custom_events(events: list) -> Path:
    """Writes custom_events.json. Always overwrites — directly
    user-editable (add/edit/delete), not append-only, same pattern as
    write_grades."""
    COURSES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = COURSES_DIR / "custom_events.json"
    out_path.write_text(json.dumps({"events": events}, indent=2), encoding="utf-8")
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_custom_events.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Write the failing tests for the CRUD service**

Create `agent/tests/test_custom_events.py`:

```python
import pytest

from agent.services import custom_events, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_create_event_assigns_id_and_defaults(isolated_courses_dir):
    event = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other")

    assert event["course_id"] == "cs101"
    assert event["date"] == "2026-09-01"
    assert event["time"] is None
    assert event["title"] == "Study group"
    assert event["type"] == "other"
    assert event["synced"] is False
    assert event["google_event_id"] is None
    assert isinstance(event["id"], str) and event["id"]


def test_create_event_general_has_null_course_id(isolated_courses_dir):
    event = custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other")

    assert event["course_id"] is None


def test_create_event_rejects_invalid_type(isolated_courses_dir):
    with pytest.raises(ValueError):
        custom_events.create_event("cs101", "2026-09-01", None, "X", "not-a-real-type")


def test_list_events_returns_created_events(isolated_courses_dir):
    custom_events.create_event("cs101", "2026-09-01", None, "A", "other")
    custom_events.create_event(None, "2026-09-02", "14:00", "B", "other")

    events = custom_events.list_events()

    assert len(events) == 2
    assert {e["title"] for e in events} == {"A", "B"}


def test_update_event_changes_fields(isolated_courses_dir):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Original", "other")

    updated = custom_events.update_event(created["id"], title="Renamed", time="15:30")

    assert updated["title"] == "Renamed"
    assert updated["time"] == "15:30"
    assert updated["date"] == "2026-09-01"  # untouched field preserved
    assert custom_events.list_events()[0]["title"] == "Renamed"


def test_update_event_rejects_invalid_type(isolated_courses_dir):
    created = custom_events.create_event("cs101", "2026-09-01", None, "X", "other")

    with pytest.raises(ValueError):
        custom_events.update_event(created["id"], type="not-a-real-type")


def test_update_event_raises_when_not_found(isolated_courses_dir):
    with pytest.raises(custom_events.EventNotFoundError):
        custom_events.update_event("nonexistent-id", title="X")


def test_delete_event_removes_it(isolated_courses_dir):
    created = custom_events.create_event("cs101", "2026-09-01", None, "X", "other")

    custom_events.delete_event(created["id"])

    assert custom_events.list_events() == []


def test_delete_event_raises_when_not_found(isolated_courses_dir):
    with pytest.raises(custom_events.EventNotFoundError):
        custom_events.delete_event("nonexistent-id")
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_custom_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.services.custom_events'`.

- [ ] **Step 7: Create `agent/services/custom_events.py`**

```python
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
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_custom_events.py -v`
Expected: PASS (9 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 9: Commit**

```bash
git add agent/services/storage.py agent/services/custom_events.py agent/tests/test_storage_custom_events.py agent/tests/test_custom_events.py
git commit -m "feat: add custom_events.json storage and CRUD service"
```

---

## Task 2: Calendar sync for custom events + the merged deadlines list

**Files:**
- Modify: `agent/services/calendar_sync.py`
- Modify: `agent/services/custom_events.py`
- Modify: `agent/services/reminders.py`
- Test: `agent/tests/test_calendar_sync.py`, `agent/tests/test_custom_events.py`, `agent/tests/test_reminders.py` (new file)

**Interfaces:**
- Consumes: `agent.services.storage.read_custom_events`/`read_calendar_sync` (existing), `agent.services.reminders.upcoming_deadlines` (existing)
- Produces: `agent.services.calendar_sync.get_credentials(google_account) -> Credentials` (renamed from `_get_credentials`, now public so `custom_events.py` can reuse it), `agent.services.custom_events.sync_event_to_calendar(user, event_id: str) -> dict`, `agent.services.reminders.list_all_deadlines() -> list`

- [ ] **Step 1: Rename `_get_credentials` to `get_credentials` in `calendar_sync.py`**

In `agent/services/calendar_sync.py`, change:

```python
def _get_credentials(google_account) -> Credentials:
```

to:

```python
def get_credentials(google_account) -> Credentials:
```

And change its one call site:

```python
    credentials = _get_credentials(google_account)
```

to:

```python
    credentials = get_credentials(google_account)
```

This is a pure rename (dropping the leading underscore to make it part of this module's public interface) — no behavior change. Run the existing suite once now to confirm nothing broke before continuing:

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_calendar_sync.py agent/tests/test_views.py -v`
Expected: all PASS, unchanged from before this rename (no test referenced the old private name directly).

- [ ] **Step 2: Write the failing tests for `sync_event_to_calendar`**

Append to `agent/tests/test_custom_events.py`. First add these imports at the top of the file, alongside the existing ones:

```python
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.utils import timezone

from agent.models import GoogleAccount
```

Then append at the end of the file:

```python
@pytest.fixture
def user_with_valid_token(db):
    user = User.objects.create_user(username="sub-123", email="jordan@example.com")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
        access_token="valid-access-token", refresh_token="refresh-token-value",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    return user


def _mock_calendar_build(event_id="event-abc"):
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": event_id}
    return mock_service


@pytest.mark.django_db
def test_sync_event_to_calendar_creates_all_day_event_when_no_time(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other")

    with patch("agent.services.custom_events.calendar_sync.build", return_value=_mock_calendar_build("evt-1")) as build:
        result = custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    assert result == {"google_event_id": "evt-1"}
    _, kwargs = build.return_value.events.return_value.insert.call_args
    assert kwargs["body"]["start"] == {"date": "2026-09-01"}
    assert kwargs["body"]["end"] == {"date": "2026-09-02"}

    updated = custom_events.list_events()[0]
    assert updated["synced"] is True
    assert updated["google_event_id"] == "evt-1"
    assert updated["synced_at"] is not None


@pytest.mark.django_db
def test_sync_event_to_calendar_creates_timed_event_when_time_set(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", "14:00", "Study group", "other")

    mock_service = _mock_calendar_build("evt-2")
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert kwargs["body"]["start"]["dateTime"] == "2026-09-01T14:00:00"
    assert kwargs["body"]["end"]["dateTime"] == "2026-09-01T15:00:00"
    assert "timeZone" in kwargs["body"]["start"]


@pytest.mark.django_db
def test_sync_event_to_calendar_raises_when_already_synced(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other")
    custom_events.update_event(created["id"], synced=True, google_event_id="already-there")

    with patch("agent.services.custom_events.calendar_sync.build") as build:
        with pytest.raises(calendar_sync.AlreadySyncedError):
            custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    build.assert_not_called()


@pytest.mark.django_db
def test_sync_event_to_calendar_raises_when_event_not_found(isolated_courses_dir, user_with_valid_token):
    with pytest.raises(custom_events.EventNotFoundError):
        custom_events.sync_event_to_calendar(user_with_valid_token, "nonexistent-id")


@pytest.mark.django_db
def test_sync_event_to_calendar_general_event_uses_general_label(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other")

    mock_service = _mock_calendar_build("evt-3")
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert "General" in kwargs["body"]["summary"]
```

Also add `from agent.services import calendar_sync` to the top of `agent/tests/test_custom_events.py` alongside the existing `from agent.services import custom_events, storage` line, since `calendar_sync.AlreadySyncedError` is now referenced directly.

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_custom_events.py -k sync_event_to_calendar -v`
Expected: FAIL — `AttributeError: module 'agent.services.custom_events' has no attribute 'sync_event_to_calendar'`.

- [ ] **Step 4: Add `sync_event_to_calendar` to `custom_events.py`**

In `agent/services/custom_events.py`, change the top-of-file imports:

```python
import uuid

from . import storage
```

to:

```python
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from . import calendar_sync, storage
```

Then add this function at the end of the file:

```python
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
        raise calendar_sync.CalendarAuthError(
            "Could not connect to Google Calendar — try signing out and back in."
        ) from e

    from django.utils import timezone as django_timezone
    event["synced"] = True
    event["google_event_id"] = created["id"]
    event["synced_at"] = django_timezone.now().isoformat()
    storage.write_custom_events(events)

    return {"google_event_id": created["id"]}
```

Note: `calendar_sync.build` here refers to `googleapiclient.discovery.build`, already imported into `calendar_sync.py`'s module namespace under the name `build` — `calendar_sync.build(...)` and the tests' `patch("agent.services.custom_events.calendar_sync.build", ...)` both reach that same name via the `calendar_sync` module reference, consistent with how the existing Calendar sync feature's own tests patch `agent.services.calendar_sync.build` directly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_custom_events.py -v`
Expected: PASS (14 passed: the 9 from Task 1 plus 5 new).

- [ ] **Step 6: Write the failing tests for `reminders.list_all_deadlines`**

Create `agent/tests/test_reminders.py`:

```python
import pytest

from agent.services import custom_events, reminders, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_syllabus(course_id, dates):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": dates, "grading": [], "topics": [],
    })


def test_list_all_deadlines_combines_syllabus_and_custom(isolated_courses_dir):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()  # well outside the 14-day dashboard window, proving this is unbounded
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}])
    custom_events.create_event("cs101", far_date, None, "Study session", "other")

    deadlines = reminders.list_all_deadlines()

    sources = {d["title"]: d["source"] for d in deadlines}
    assert sources["Final Exam"] == "syllabus"
    assert sources["Study session"] == "custom"


def test_list_all_deadlines_marks_synced_syllabus_deadline(isolated_courses_dir):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}])
    storage.append_calendar_sync_record("cs101", {
        "date": far_date, "title": "Final Exam", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    })

    deadlines = reminders.list_all_deadlines()

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Final Exam"]["synced"] is True


def test_list_all_deadlines_marks_synced_custom_event(isolated_courses_dir):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study session", "other")
    custom_events.update_event(created["id"], synced=True, google_event_id="evt-2")

    deadlines = reminders.list_all_deadlines()

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Study session"]["synced"] is True


def test_list_all_deadlines_includes_general_custom_event(isolated_courses_dir):
    custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other")

    deadlines = reminders.list_all_deadlines()

    assert any(d["title"] == "Thanksgiving break" and d["course_id"] is None for d in deadlines)


def test_list_all_deadlines_excludes_past_custom_events(isolated_courses_dir):
    custom_events.create_event("cs101", "2020-01-01", None, "Long past", "other")

    deadlines = reminders.list_all_deadlines()

    assert deadlines == []


def test_list_all_deadlines_sorted_by_date(isolated_courses_dir):
    custom_events.create_event("cs101", "2099-03-01", None, "Later", "other")
    custom_events.create_event("cs101", "2099-01-01", None, "Earlier", "other")

    deadlines = reminders.list_all_deadlines()

    assert [d["title"] for d in deadlines] == ["Earlier", "Later"]
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_reminders.py -v`
Expected: FAIL — `AttributeError: module 'agent.services.reminders' has no attribute 'list_all_deadlines'`.

- [ ] **Step 8: Add `list_all_deadlines` to `reminders.py`**

In `agent/services/reminders.py`, change the top-of-file import:

```python
from . import storage
```

to:

```python
from . import custom_events, storage
```

Then add this function at the end of the file:

```python
def list_all_deadlines() -> list:
    """Every upcoming deadline from both sources — syllabus-extracted
    (read-only, tagged source="syllabus") and manually-added (full CRUD,
    tagged source="custom") — combined and sorted by date, unbounded (no
    14-day cap, unlike the Dashboard's own upcoming_deadlines() call).
    Powers the Deadlines tab's full list.

    The sync-status annotation for syllabus deadlines duplicates
    dashboard.py's _annotate_synced (same 4-line cross-reference against
    read_calendar_sync) rather than importing it — dashboard.py already
    imports this module, so importing back would be circular."""
    today = date.today()

    syllabus_deadlines = upcoming_deadlines(within_days=None)
    synced_by_course = {}
    for d in syllabus_deadlines:
        course_id = d["course_id"]
        if course_id not in synced_by_course:
            synced_by_course[course_id] = storage.read_calendar_sync(course_id)
        d["synced"] = any(
            r["date"] == d["date"] and r["title"] == d["title"]
            for r in synced_by_course[course_id]
        )
        d["source"] = "syllabus"
        d["id"] = None
        d["time"] = None

    custom = [
        dict(e, source="custom")
        for e in custom_events.list_events()
        if e["date"] >= today.isoformat()
    ]

    combined = syllabus_deadlines + custom
    combined.sort(key=lambda d: (d["date"], d["time"] or ""))
    return combined
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_reminders.py -v`
Expected: PASS (6 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 10: Commit**

```bash
git add agent/services/calendar_sync.py agent/services/custom_events.py agent/services/reminders.py agent/tests/test_calendar_sync.py agent/tests/test_custom_events.py agent/tests/test_reminders.py
git commit -m "feat: add Google Calendar sync for custom events and the merged deadlines list"
```

---

## Task 3: API endpoints

**Files:**
- Modify: `agent/serializers.py`
- Modify: `agent/views.py`
- Modify: `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `agent.services.custom_events.list_events`/`create_event`/`update_event`/`delete_event`/`sync_event_to_calendar`/`EventNotFoundError` (Task 1/2), `agent.services.reminders.list_all_deadlines` (Task 2), `agent.services.calendar_sync.AlreadySyncedError`/`CalendarAuthError` (existing)
- Produces: `GET/POST /api/deadlines/` (URL name `deadlines`), `PATCH/DELETE /api/deadlines/<event_id>/` (URL name `custom-event-detail`), `POST /api/deadlines/<event_id>/calendar-sync/` (URL name `custom-event-calendar-sync`)

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_deadlines_get_returns_merged_list(isolated_courses_dir, api_client):
    from agent.services import custom_events

    custom_events.create_event("cs101", "2099-01-01", None, "Future thing", "other")

    response = api_client.get("/api/deadlines/")

    assert response.status_code == 200
    assert any(d["title"] == "Future thing" for d in response.data)


@pytest.mark.django_db
def test_deadlines_post_creates_custom_event(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"course_id": "cs101", "date": "2026-09-01", "time": "14:00", "title": "Study group", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Study group"
    # The view converts the validated TimeField back to a plain "HH:MM"
    # string (d["time"].strftime("%H:%M")) before calling create_event, and
    # the response is that same stored dict returned as-is (not re-run
    # through DRF serialization) — so it comes back "HH:MM", not "HH:MM:SS".
    assert response.data["time"] == "14:00"


@pytest.mark.django_db
def test_deadlines_post_general_event_has_null_course_id(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-11-26", "title": "Thanksgiving break", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["course_id"] is None


@pytest.mark.django_db
def test_deadlines_post_rejects_invalid_type(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "X", "type": "not-a-real-type"},
        format="json",
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_custom_event_detail_patch_updates_event(isolated_courses_dir, api_client):
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Original", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    response = api_client.patch(f"/api/deadlines/{event_id}/", {"title": "Renamed"}, format="json")

    assert response.status_code == 200
    assert response.data["title"] == "Renamed"


@pytest.mark.django_db
def test_custom_event_detail_patch_404_when_not_found(isolated_courses_dir, api_client):
    response = api_client.patch("/api/deadlines/nonexistent-id/", {"title": "X"}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
def test_custom_event_detail_delete_removes_event(isolated_courses_dir, api_client):
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "X", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    response = api_client.delete(f"/api/deadlines/{event_id}/")

    assert response.status_code == 204
    assert api_client.get("/api/deadlines/").data == []


@pytest.mark.django_db
def test_custom_event_detail_delete_404_when_not_found(isolated_courses_dir, api_client):
    response = api_client.delete("/api/deadlines/nonexistent-id/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_custom_event_calendar_sync_creates_event(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import MagicMock, patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    create_response = client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-abc"}
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        response = client.post(f"/api/deadlines/{event_id}/calendar-sync/")

    assert response.status_code == 201
    assert response.data == {"google_event_id": "evt-abc"}


@pytest.mark.django_db
def test_custom_event_calendar_sync_404_when_event_not_found(isolated_courses_dir, api_client):
    response = api_client.post("/api/deadlines/nonexistent-id/calendar-sync/")

    assert response.status_code == 404
```

Note: these tests use `isolated_courses_dir` and `api_client` — both already defined in this file's existing fixtures. Verify near the top of `agent/tests/test_views.py` that `isolated_courses_dir` redirects `storage.COURSES_DIR` (it does, per every other test in this file) — since `custom_events.json` lives directly under `COURSES_DIR`, this fixture isolates it the same way it isolates every per-course file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k "deadlines or custom_event" -v`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Add the request serializers**

In `agent/serializers.py`, change:

```python
class CalendarSyncRequestSerializer(serializers.Serializer):
    # DateField (not CharField) so a malformed date ("not-a-date") is
    # rejected here with a 400 at the serializer layer, rather than passing
    # validation and later blowing up datetime.strptime() in calendar_sync.py.
    date = serializers.DateField()
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)
```

to:

```python
class CalendarSyncRequestSerializer(serializers.Serializer):
    # DateField (not CharField) so a malformed date ("not-a-date") is
    # rejected here with a 400 at the serializer layer, rather than passing
    # validation and later blowing up datetime.strptime() in calendar_sync.py.
    date = serializers.DateField()
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)


class CreateCustomEventRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    date = serializers.DateField()
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)


class UpdateCustomEventRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    date = serializers.DateField(required=False, default=None)
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    type = serializers.CharField(required=False, allow_blank=False, default=None)
```

- [ ] **Step 4: Add the views**

In `agent/views.py`, change the import block:

```python
from .serializers import (
    AddGradeItemRequestSerializer,
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    CalendarSyncRequestSerializer,
    ChunkNotesRequestSerializer,
    CreateCourseDraftRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
    UpdateGradeItemRequestSerializer,
)
from .services import calendar_sync, chunk_notes, dashboard, domain_suggestions, grades, mastery, quiz, references, reminders, sessions, storage
```

to:

```python
from .serializers import (
    AddGradeItemRequestSerializer,
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    CalendarSyncRequestSerializer,
    ChunkNotesRequestSerializer,
    CreateCourseDraftRequestSerializer,
    CreateCustomEventRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
    UpdateCustomEventRequestSerializer,
    UpdateGradeItemRequestSerializer,
)
from .services import calendar_sync, chunk_notes, custom_events, dashboard, domain_suggestions, grades, mastery, quiz, references, reminders, sessions, storage
```

Then add these three classes right after `CalendarSyncView` (i.e., immediately before `class SyllabusDetailView(APIView):`):

```python
class DeadlinesView(APIView):
    """
    GET /api/deadlines/ — every upcoming deadline, syllabus-extracted and
    manually-added combined, unbounded (no 14-day cap).
    POST /api/deadlines/ — create a manually-added deadline.
    body: {"course_id"?, "date", "time"?, "title", "type"}
    course_id omitted/null means a general (not course-specific) event.
    """

    async def get(self, request):
        data = await sync_to_async(reminders.list_all_deadlines)()
        return Response(data, status=status.HTTP_200_OK)

    async def post(self, request):
        serializer = CreateCustomEventRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data

        try:
            event = await sync_to_async(custom_events.create_event)(
                d["course_id"],
                d["date"].isoformat(),
                d["time"].strftime("%H:%M") if d["time"] else None,
                d["title"], d["type"],
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(event, status=status.HTTP_201_CREATED)


class CustomEventDetailView(APIView):
    """
    PATCH /api/deadlines/<event_id>/ — partial update.
    DELETE /api/deadlines/<event_id>/
    """

    async def patch(self, request, event_id):
        serializer = UpdateCustomEventRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        fields = {k: v for k, v in serializer.validated_data.items() if v is not None}
        if "date" in fields:
            fields["date"] = fields["date"].isoformat()
        if "time" in fields:
            fields["time"] = fields["time"].strftime("%H:%M")

        try:
            event = await sync_to_async(custom_events.update_event)(event_id, **fields)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(event, status=status.HTTP_200_OK)

    async def delete(self, request, event_id):
        try:
            await sync_to_async(custom_events.delete_event)(event_id)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomEventCalendarSyncView(APIView):
    """POST /api/deadlines/<event_id>/calendar-sync/ — push a custom event
    to the signed-in user's real Google Calendar. 404 if the event doesn't
    exist, 409 if already synced, 502 if Google credentials can't be used
    (including any unexpected failure — never an unhandled 500)."""

    async def post(self, request, event_id):
        try:
            result = await sync_to_async(custom_events.sync_event_to_calendar)(request.user, event_id)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except calendar_sync.AlreadySyncedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except calendar_sync.CalendarAuthError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("Unexpected error in custom event calendar sync")
            return Response({"detail": "Could not add to Google Calendar."}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_201_CREATED)
```

- [ ] **Step 5: Wire the URLs**

In `agent/urls.py`, change:

```python
    path("reminders/", views.RemindersView.as_view(), name="reminders"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("grades/summary/", views.GradesSummaryView.as_view(), name="grades-summary"),
]
```

to:

```python
    path("reminders/", views.RemindersView.as_view(), name="reminders"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("grades/summary/", views.GradesSummaryView.as_view(), name="grades-summary"),
    path("deadlines/", views.DeadlinesView.as_view(), name="deadlines"),
    path("deadlines/<str:event_id>/", views.CustomEventDetailView.as_view(), name="custom-event-detail"),
    path("deadlines/<str:event_id>/calendar-sync/", views.CustomEventCalendarSyncView.as_view(), name="custom-event-calendar-sync"),
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k "deadlines or custom_event" -v`
Expected: PASS (10 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 7: Commit**

```bash
git add agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add /api/deadlines/ CRUD and calendar-sync endpoints"
```

---

## Task 4: "Deadlines" tab — list, add/edit modal, delete

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET/POST /api/deadlines/`, `PATCH/DELETE /api/deadlines/<event_id>/`, `POST /api/deadlines/<event_id>/calendar-sync/` (Task 3)

This task is browser-side only — no new Python. All edits are to `agent/templates/agent/ontrack.html`. Search for each block by its exact content, not by line number (this file has shifted line numbers repeatedly across prior work).

- [ ] **Step 1: Add the nav tab button**

Find this exact block:

```html
      <button type="button" onClick="{{ goGrades }}" style="{{ navBtnStyleGrades }}">
```

Read the few lines above it and below it in the actual file to find the button's full markup (icon + label), and add a new, near-identical button for "Deadlines" immediately after the Grades button closes (before the `</div>` that closes the nav button list). Use this exact markup for the new button, matching the existing buttons' structure (svg icon + span label) — use a calendar icon:

```html
      <button type="button" onClick="{{ goDeadlines }}" style="{{ navBtnStyleDeadlines }}">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>
        Deadlines
      </button>
```

Match the exact `<span>`/text structure the other nav buttons use for their label (open the file and copy the Grades button's label markup pattern verbatim, substituting "Deadlines" for its text) — do not guess at a structure different from its siblings.

- [ ] **Step 2: Add state fields**

Find this line in the `state = {` block:

```javascript
    deleteCourseId: null, deleteCourseName: '', deleteCourseOpen: false,
    deleteCourseLoading: false, deleteCourseError: null
  };
```

Change it to:

```javascript
    deleteCourseId: null, deleteCourseName: '', deleteCourseOpen: false,
    deleteCourseLoading: false, deleteCourseError: null,
    deadlinesLoading: false, deadlinesError: null, allDeadlines: [], deadlineSyncingIds: {},
    deadlineModalOpen: false, deadlineEditingId: null, deadlineCourseId: '', deadlineDate: '',
    deadlineTime: '', deadlineTitle: '', deadlineType: 'other',
    deadlineModalLoading: false, deadlineModalError: null,
    deleteDeadlineId: null, deleteDeadlineTitle: '', deleteDeadlineOpen: false,
    deleteDeadlineLoading: false, deleteDeadlineError: null
  };
```

- [ ] **Step 3: Add a sequence counter**

Find:

```javascript
  _deleteCourseSeq = 0;
```

Change it to:

```javascript
  _deleteCourseSeq = 0;
  _deadlinesSeq = 0;
```

- [ ] **Step 4: Wire `setTab` to load deadlines when that tab opens**

Find this exact block (the start of `setTab`):

```javascript
    const setTab = (t) => {
      this._quizSeq++;
      this._chatSeq++;
      if (t === 'dashboard') {
        this.setState({ tab: t });
        this.loadDashboard();
        this.loadDashboardRecent(s.course);
        return;
      }
```

Replace it with (adding a `deadlines` branch that, like `dashboard`, returns early since this tab isn't course-scoped):

```javascript
    const setTab = (t) => {
      this._quizSeq++;
      this._chatSeq++;
      if (t === 'dashboard') {
        this.setState({ tab: t });
        this.loadDashboard();
        this.loadDashboardRecent(s.course);
        return;
      }
      if (t === 'deadlines') {
        this.setState({ tab: t });
        this.loadAllDeadlines();
        return;
      }
```

- [ ] **Step 5: Add the loading/CRUD/modal methods**

Find this exact block (the end of `loadDashboardRecent`, right before `loadChatSessions` begins):

```javascript
      .catch(e => {
        if (seq !== this._recentSeq) return;
        this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message });
      });
  }

  loadChatSessions(courseId) {
```

Replace it with (inserting the new methods between the two existing ones — nothing is deleted, `loadChatSessions(courseId) {` is preserved verbatim at the end):

```javascript
      .catch(e => {
        if (seq !== this._recentSeq) return;
        this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message });
      });
  }

  loadAllDeadlines() {
    const seq = ++this._deadlinesSeq;
    this.setState({ deadlinesLoading: true, deadlinesError: null });
    fetch('/api/deadlines/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._deadlinesSeq) return;
        if (!ok) { this.setState({ deadlinesLoading: false, deadlinesError: data.detail || 'Could not load deadlines.' }); return; }
        this.setState({ deadlinesLoading: false, allDeadlines: data });
      })
      .catch(e => {
        if (seq !== this._deadlinesSeq) return;
        this.setState({ deadlinesLoading: false, deadlinesError: 'Network error: ' + e.message });
      });
  }

  openAddDeadline() {
    this.setState({
      deadlineModalOpen: true, deadlineEditingId: null, deadlineCourseId: '',
      deadlineDate: '', deadlineTime: '', deadlineTitle: '', deadlineType: 'other',
      deadlineModalLoading: false, deadlineModalError: null
    });
  }

  openEditDeadline(event) {
    this.setState({
      deadlineModalOpen: true, deadlineEditingId: event.id, deadlineCourseId: event.course_id || '',
      deadlineDate: event.date, deadlineTime: event.time || '', deadlineTitle: event.title, deadlineType: event.type,
      deadlineModalLoading: false, deadlineModalError: null
    });
  }

  closeDeadlineModal() {
    this.setState({ deadlineModalOpen: false, deadlineEditingId: null, deadlineModalError: null });
  }

  submitDeadlineModal() {
    const s = this.state;
    if (!s.deadlineDate || !s.deadlineTitle.trim()) {
      this.setState({ deadlineModalError: 'Date and title are required.' });
      return;
    }
    this.setState({ deadlineModalLoading: true, deadlineModalError: null });
    const body = {
      course_id: s.deadlineCourseId || null,
      date: s.deadlineDate,
      time: s.deadlineTime || null,
      title: s.deadlineTitle,
      type: s.deadlineType
    };
    const url = s.deadlineEditingId ? `/api/deadlines/${s.deadlineEditingId}/` : '/api/deadlines/';
    const method = s.deadlineEditingId ? 'PATCH' : 'POST';
    fetch(url, {
      method: method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(body)
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) { this.setState({ deadlineModalLoading: false, deadlineModalError: data.detail || 'Could not save this deadline.' }); return; }
        this.closeDeadlineModal();
        this.loadAllDeadlines();
      })
      .catch(e => {
        this.setState({ deadlineModalLoading: false, deadlineModalError: 'Network error: ' + e.message });
      });
  }

  openDeleteDeadline(event) {
    this.setState({ deleteDeadlineOpen: true, deleteDeadlineId: event.id, deleteDeadlineTitle: event.title, deleteDeadlineError: null, deleteDeadlineLoading: false });
  }

  closeDeleteDeadline() {
    this.setState({ deleteDeadlineOpen: false, deleteDeadlineId: null, deleteDeadlineTitle: '', deleteDeadlineError: null, deleteDeadlineLoading: false });
  }

  confirmDeleteDeadline() {
    const id = this.state.deleteDeadlineId;
    this.setState({ deleteDeadlineLoading: true, deleteDeadlineError: null });
    fetch(`/api/deadlines/${id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
      .then(r => {
        if (!r.ok) return r.json().then(data => { throw new Error(data.detail || 'Could not delete this deadline.'); });
        this.closeDeleteDeadline();
        this.loadAllDeadlines();
      })
      .catch(e => {
        this.setState({ deleteDeadlineLoading: false, deleteDeadlineError: e.message });
      });
  }

  syncDeadlineToCalendar(event) {
    if (this.state.deadlineSyncingIds[event.id]) return;
    this.setState({ deadlineSyncingIds: Object.assign({}, this.state.deadlineSyncingIds, { [event.id]: true }) });
    fetch(`/api/deadlines/${event.id}/calendar-sync/`, { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok }) => {
        const syncing = Object.assign({}, this.state.deadlineSyncingIds);
        delete syncing[event.id];
        this.setState({ deadlineSyncingIds: syncing });
        if (ok) this.loadAllDeadlines();
      })
      .catch(() => {
        const syncing = Object.assign({}, this.state.deadlineSyncingIds);
        delete syncing[event.id];
        this.setState({ deadlineSyncingIds: syncing });
      });
  }

  loadChatSessions(courseId) {
```

Note: syllabus-sourced deadline rows (`source === "syllabus"`) can also be synced via this same method — `event.id` is `null` for those (per Task 2's `list_all_deadlines`), so route their sync action through the existing per-course endpoint instead (see Step 7's row markup) rather than `syncDeadlineToCalendar`, which only targets `/api/deadlines/<event_id>/calendar-sync/` (custom events only, since only they have a real `id`).

- [ ] **Step 6: Wire `renderVals()` — nav state, deadline rows, modal fields**

Find this exact block:

```javascript
      navBtnStyleGrades: this.navBtn(s.tab === 'grades'),
```

Change it to:

```javascript
      navBtnStyleGrades: this.navBtn(s.tab === 'grades'),
      navBtnStyleDeadlines: this.navBtn(s.tab === 'deadlines'),
```

Find:

```javascript
      isGradesAllCourses: s.tab === 'grades' && s.course === 'all',
```

Change it to:

```javascript
      isGradesAllCourses: s.tab === 'grades' && s.course === 'all',
      isDeadlines: s.tab === 'deadlines',
```

Find:

```javascript
      goDashboard: () => setTab('dashboard'),
      goChat: () => setTab('chat'),
      goProgress: () => setTab('progress'),
      goQuiz: () => setTab('quiz'),
      goGrades: () => setTab('grades'),
```

Change it to:

```javascript
      goDashboard: () => setTab('dashboard'),
      goChat: () => setTab('chat'),
      goProgress: () => setTab('progress'),
      goQuiz: () => setTab('quiz'),
      goGrades: () => setTab('grades'),
      goDeadlines: () => setTab('deadlines'),
```

Now find this exact block (the `deadlines` mapping already built for the Dashboard's Upcoming panel — leave it untouched, but use it as the anchor to insert the new Deadlines-tab-specific values right after it):

```javascript
    const deadlines = s.dashboardDeadlines.filter(d => s.course === 'all' || d.course_id === s.course).map(d => {
      const dp = dateParts(d.date);
      const key = d.date + '|' + d.title;
      return {
        month: dp.monthAbbrUpper, day: dp.day, title: d.title,
        typeLabel: d.type === 'exam' ? 'Exam' : d.type === 'assignment' ? 'Assignment' : 'Other',
        tagStyle: typeStyle(d.type),
        synced: !!d.synced,
        addButtonLabel: s.dashboardSyncingKeys[key] ? 'Adding…' : 'Add to Calendar',
        onAddToCalendar: () => this.addToCalendar(d.course_id, d.date, d.title, d.type, key)
      };
    });
```

Add this new block immediately after it (a separate mapping over `s.allDeadlines`, for the new tab — does not touch `deadlines` above):

```javascript
    const courseLabel = (id) => id ? id.toUpperCase() : 'General';
    const allDeadlinesRows = s.allDeadlines.map(d => {
      const dp = dateParts(d.date);
      const isCustom = d.source === 'custom';
      return {
        month: dp.monthAbbrUpper, day: dp.day, title: d.title,
        courseLabel: courseLabel(d.course_id),
        timeLabel: d.time ? d.time.slice(0, 5) : '',
        typeLabel: d.type === 'exam' ? 'Exam' : d.type === 'assignment' ? 'Assignment' : d.type === 'reading' ? 'Reading' : 'Other',
        tagStyle: typeStyle(d.type),
        synced: !!d.synced,
        isCustom: isCustom,
        syncButtonLabel: s.deadlineSyncingIds[d.id] ? 'Adding…' : 'Add to Calendar',
        onSync: isCustom ? (() => this.syncDeadlineToCalendar(d)) : (() => this.addToCalendar(d.course_id, d.date, d.title, d.type, d.course_id + '|' + d.date + '|' + d.title)),
        onEdit: () => this.openEditDeadline(d),
        onDelete: () => this.openDeleteDeadline(d)
      };
    });
    const deadlinesEmpty = !s.deadlinesLoading && !s.deadlinesError && allDeadlinesRows.length === 0;

    const deadlineCourseOptions = realCourseIds.map(id => ({ id: id, name: (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase() }));
    const onDeadlineCourseChange = (e) => this.setState({ deadlineCourseId: e.target.value });
    const onDeadlineDateChange = (e) => this.setState({ deadlineDate: e.target.value });
    const onDeadlineTimeChange = (e) => this.setState({ deadlineTime: e.target.value });
    const onDeadlineTitleChange = (e) => this.setState({ deadlineTitle: e.target.value });
    const onDeadlineTypeChange = (e) => this.setState({ deadlineType: e.target.value });
    const deadlineModalTitle = s.deadlineEditingId ? 'Edit deadline' : 'Add deadline';
    const deadlineSubmitLabel = s.deadlineEditingId ? 'Save' : 'Add deadline';
```

Now find this exact block (where `deadlines`/`weakTopics`/etc. get returned from `renderVals()`):

```javascript
      deadlines: deadlines, weakTopics: weakTopics, allTopics: allTopics, recentAttempts: dashboardRecentActivity, mcOptions: mcOptions, quizDots: quizDots,
```

Change it to:

```javascript
      deadlines: deadlines, weakTopics: weakTopics, allTopics: allTopics, recentAttempts: dashboardRecentActivity, mcOptions: mcOptions, quizDots: quizDots,
      allDeadlinesRows: allDeadlinesRows, deadlinesEmpty: deadlinesEmpty, deadlinesLoading: s.deadlinesLoading, deadlinesError: s.deadlinesError,
      openAddDeadline: () => this.openAddDeadline(),
      deadlineModalOpen: s.deadlineModalOpen, deadlineModalTitle: deadlineModalTitle, deadlineSubmitLabel: deadlineSubmitLabel,
      deadlineCourseId: s.deadlineCourseId, deadlineCourseOptions: deadlineCourseOptions, onDeadlineCourseChange: onDeadlineCourseChange,
      deadlineDate: s.deadlineDate, onDeadlineDateChange: onDeadlineDateChange,
      deadlineTime: s.deadlineTime, onDeadlineTimeChange: onDeadlineTimeChange,
      deadlineTitle: s.deadlineTitle, onDeadlineTitleChange: onDeadlineTitleChange,
      deadlineType: s.deadlineType, onDeadlineTypeChange: onDeadlineTypeChange,
      deadlineModalLoading: s.deadlineModalLoading, deadlineModalError: s.deadlineModalError,
      closeDeadlineModal: () => this.closeDeadlineModal(), submitDeadlineModal: () => this.submitDeadlineModal(),
      deleteDeadlineOpen: s.deleteDeadlineOpen, deleteDeadlineTitle: s.deleteDeadlineTitle,
      deleteDeadlineLoading: s.deleteDeadlineLoading, deleteDeadlineError: s.deleteDeadlineError,
      closeDeleteDeadline: () => this.closeDeleteDeadline(), confirmDeleteDeadline: () => this.confirmDeleteDeadline(),
      goToDeadlinesTab: () => setTab('deadlines'),
```

- [ ] **Step 7: Add the tab content, modal, and delete-confirmation markup**

Find this exact block (the closing of the Dashboard tab's `sc-if`, right before the Chat tab begins — search for the literal text `isChat` in a nearby `sc-if` to confirm you're at the right boundary):

```html
    </sc-if>

    <sc-if value="{{ isChat }}" hint-placeholder-val="{{ false }}">
```

Replace it with (inserting the whole new Deadlines tab between the two, nothing removed):

```html
    </sc-if>

    <sc-if value="{{ isDeadlines }}" hint-placeholder-val="{{ false }}">
      <div style="padding:var(--space-8) var(--space-8);max-width:1100px">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:var(--space-6)">
          <div>
            <h1 style="font-family:var(--font-heading);font-size:28px;margin:0 0 4px">Deadlines</h1>
            <p style="margin:0;opacity:.65;font-size:14.5px">Everything upcoming, across every course.</p>
          </div>
          <button type="button" class="btn btn-primary" onClick="{{ openAddDeadline }}">+ Add deadline</button>
        </div>

        <sc-if value="{{ deadlinesLoading }}" hint-placeholder-val="{{ false }}">
          <div class="card elev-sm" style="padding:var(--space-6);text-align:center;opacity:.7">Loading deadlines…</div>
        </sc-if>
        <sc-if value="{{ deadlinesError }}" hint-placeholder-val="{{ false }}">
          <div class="card elev-sm" style="padding:var(--space-6)">
            <p class="card-body" style="margin:0">{{ deadlinesError }}</p>
          </div>
        </sc-if>
        <sc-if value="{{ deadlinesEmpty }}" hint-placeholder-val="{{ false }}">
          <div class="card elev-sm" style="padding:var(--space-6);text-align:center;opacity:.7">No upcoming deadlines yet.</div>
        </sc-if>

        <div class="card elev-sm" style="padding:0">
          <sc-for list="{{ allDeadlinesRows }}" as="d" hint-placeholder-count="4">
            <div style="display:flex;align-items:center;gap:var(--space-3);padding:14px var(--space-6);border-bottom:1px solid var(--color-neutral-200)">
              <div style="width:44px;flex:none;text-align:center;font-family:var(--font-heading);font-size:12px;color:var(--color-accent-700);line-height:1.15">{{ d.month }}<br/><span style="font-size:16px">{{ d.day }}</span></div>
              <div style="flex:1;min-width:0">
                <div style="font-size:14px;font-weight:600">{{ d.title }}</div>
                <div style="font-size:12px;opacity:.6">{{ d.courseLabel }}<sc-if value="{{ d.timeLabel }}" hint-placeholder-val="{{ false }}"> · {{ d.timeLabel }}</sc-if></div>
              </div>
              <span style="{{ d.tagStyle }}">{{ d.typeLabel }}</span>
              <sc-if value="{{ d.synced }}" hint-placeholder-val="{{ false }}">
                <span class="tag tag-accent-2" style="flex:none">Added ✓</span>
              </sc-if>
              <sc-if value="{{ !d.synced }}" hint-placeholder-val="{{ true }}">
                <button type="button" class="btn btn-secondary" style="flex:none;padding:4px 10px;font-size:12px" onClick="{{ d.onSync }}">{{ d.syncButtonLabel }}</button>
              </sc-if>
              <sc-if value="{{ d.isCustom }}" hint-placeholder-val="{{ false }}">
                <button type="button" class="btn-icon btn-ghost" style="flex:none" onClick="{{ d.onEdit }}" title="Edit">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button type="button" class="btn-icon btn-ghost" style="flex:none" onClick="{{ d.onDelete }}" title="Delete">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </sc-if>
            </div>
          </sc-for>
        </div>
      </div>
    </sc-if>

    <sc-if value="{{ isChat }}" hint-placeholder-val="{{ false }}">
```

Now add the add/edit modal and the delete-confirmation modal. Find this exact block (the existing delete-course modal's closing tag, right after it — this keeps every modal grouped together at the end of the page's fixed-position overlays):

```html
        <sc-if value="{{ !deleteCourseLoading }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary" onClick="{{ closeDeleteCourse }}">Cancel</button>
            <button type="button" class="btn btn-primary" onClick="{{ confirmDeleteCourse }}">Delete</button>
          </div>
        </sc-if>
      </div>
    </div>
  </sc-if>
```

Replace it with (the delete-course modal is unchanged; the two new modals are appended right after it):

```html
        <sc-if value="{{ !deleteCourseLoading }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary" onClick="{{ closeDeleteCourse }}">Cancel</button>
            <button type="button" class="btn btn-primary" onClick="{{ confirmDeleteCourse }}">Delete</button>
          </div>
        </sc-if>
      </div>
    </div>
  </sc-if>

  <sc-if value="{{ deadlineModalOpen }}" hint-placeholder-val="{{ false }}">
    <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
      <div class="card elev-md" style="padding:var(--space-6);width:420px;max-width:90vw">
        <div class="card-title" style="margin:0 0 var(--space-4)">{{ deadlineModalTitle }}</div>

        <div style="display:flex;flex-direction:column;gap:12px;margin-bottom:var(--space-4)">
          <div>
            <div style="font-size:13px;margin-bottom:4px">Course</div>
            <select class="input" value="{{ deadlineCourseId }}" onChange="{{ onDeadlineCourseChange }}" style="width:100%">
              <option value="">General (all courses)</option>
              <sc-for list="{{ deadlineCourseOptions }}" as="c" hint-placeholder-count="2">
                <option value="{{ c.id }}">{{ c.name }}</option>
              </sc-for>
            </select>
          </div>
          <div style="display:flex;gap:12px">
            <div style="flex:1">
              <div style="font-size:13px;margin-bottom:4px">Date</div>
              <input class="input" type="date" value="{{ deadlineDate }}" onChange="{{ onDeadlineDateChange }}" style="width:100%"/>
            </div>
            <div style="flex:1">
              <div style="font-size:13px;margin-bottom:4px">Time (optional)</div>
              <input class="input" type="time" value="{{ deadlineTime }}" onChange="{{ onDeadlineTimeChange }}" style="width:100%"/>
            </div>
          </div>
          <div>
            <div style="font-size:13px;margin-bottom:4px">Title</div>
            <input class="input" value="{{ deadlineTitle }}" onChange="{{ onDeadlineTitleChange }}" style="width:100%"/>
          </div>
          <div>
            <div style="font-size:13px;margin-bottom:4px">Type</div>
            <select class="input" value="{{ deadlineType }}" onChange="{{ onDeadlineTypeChange }}" style="width:100%">
              <option value="exam">Exam</option>
              <option value="assignment">Assignment</option>
              <option value="reading">Reading</option>
              <option value="other">Other</option>
            </select>
          </div>
        </div>

        <sc-if value="{{ deadlineModalError }}" hint-placeholder-val="{{ false }}">
          <p style="font-size:13px;color:var(--color-accent-700);margin:0 0 var(--space-4)">{{ deadlineModalError }}</p>
        </sc-if>

        <sc-if value="{{ deadlineModalLoading }}" hint-placeholder-val="{{ false }}">
          <div style="font-size:13px;opacity:.7;padding:8px 0">Saving…</div>
        </sc-if>

        <sc-if value="{{ !deadlineModalLoading }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary" onClick="{{ closeDeadlineModal }}">Cancel</button>
            <button type="button" class="btn btn-primary" onClick="{{ submitDeadlineModal }}">{{ deadlineSubmitLabel }}</button>
          </div>
        </sc-if>
      </div>
    </div>
  </sc-if>

  <sc-if value="{{ deleteDeadlineOpen }}" hint-placeholder-val="{{ false }}">
    <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
      <div class="card elev-md" style="padding:var(--space-6);width:360px;max-width:90vw">
        <div class="card-title" style="margin:0 0 var(--space-3)">Delete {{ deleteDeadlineTitle }}?</div>
        <p class="card-body" style="margin:0 0 var(--space-4)">This can't be undone. If this deadline was already added to Google Calendar, that event stays — this only removes it from OnTrack.</p>
        <sc-if value="{{ deleteDeadlineError }}" hint-placeholder-val="{{ false }}">
          <p style="font-size:13px;color:var(--color-accent-700);margin:0 0 var(--space-4)">{{ deleteDeadlineError }}</p>
        </sc-if>
        <sc-if value="{{ deleteDeadlineLoading }}" hint-placeholder-val="{{ false }}">
          <div style="font-size:13px;opacity:.7;padding:8px 0">Deleting…</div>
        </sc-if>
        <sc-if value="{{ !deleteDeadlineLoading }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary" onClick="{{ closeDeleteDeadline }}">Cancel</button>
            <button type="button" class="btn btn-primary" onClick="{{ confirmDeleteDeadline }}">Delete</button>
          </div>
        </sc-if>
      </div>
    </div>
  </sc-if>
```

- [ ] **Step 8: Add the "See all →" link to the Dashboard's Upcoming panel**

Find this exact block:

```html
              <div style="display:flex;align-items:center;justify-content:between;gap:8px;margin-bottom:var(--space-4)">
                <div style="display:flex;align-items:center;gap:8px">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>
                  <div class="card-title" style="margin:0">Upcoming deadlines</div>
                </div>
              </div>
```

Replace it with:

```html
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:var(--space-4)">
                <div style="display:flex;align-items:center;gap:8px">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>
                  <div class="card-title" style="margin:0">Upcoming deadlines</div>
                </div>
                <button type="button" class="btn btn-ghost" style="font-size:12.5px" onClick="{{ goToDeadlinesTab }}">See all →</button>
              </div>
```

(Note: this also fixes a pre-existing typo in this block — `justify-content:between` isn't a valid CSS value, it silently does nothing; the correct value is `justify-content:space-between`. Harmless either way since this row currently has only one child, but correct it while you're here since you're touching this exact line.)

- [ ] **Step 9: Manual verification (required)**

Start the dev server: `venv/Scripts/python.exe -m uvicorn config.asgi:application --port 8000`

Sign in (or use an existing session) and:
1. Confirm a new "Deadlines" item appears in the sidebar nav, and clicking it shows every upcoming deadline across all courses (not capped at 14 days) — including any far-future syllabus dates.
2. Click "+ Add deadline". Fill in a course-specific deadline (pick a real course, a date, no time, a title, type "other") and submit. Confirm it appears in the list immediately with an "Add to Calendar" button and no sync badge.
3. Click "+ Add deadline" again. Leave Course as "General (all courses)", set a date and a time, submit. Confirm it appears with the time shown next to "General".
4. Click "Add to Calendar" on the general, timed one. With real Google credentials configured, confirm a real timed event appears on your Google Calendar at the right hour, and confirm the row now shows "Added ✓".
5. Click the edit (pencil) icon on the course-specific one, change its title, save. Confirm the row updates.
6. Click the delete (trash) icon on it, confirm the deletion, confirm it's gone from the list.
7. Go back to the Dashboard tab. Confirm the existing "Upcoming deadlines" panel is completely unchanged except for a new "See all →" link, and that link navigates to the Deadlines tab.
8. Confirm syllabus-extracted deadline rows in the new Deadlines tab do NOT show an edit or delete icon (only custom ones do).

Stop the dev server when done.

- [ ] **Step 10: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: add Deadlines tab with full CRUD and a Dashboard link to it"
```

---

## Self-Review Notes

- **Spec coverage:** implements every section of `docs/superpowers/specs/2026-08-20-custom-deadlines-design.md` — storage + CRUD (Task 1), Calendar sync reuse + the merged list (Task 2), the API surface (Task 3), and the full UI including the Dashboard link (Task 4). The spec's non-goals (recurring schedules, editing syllabus dates, a calendar grid, un-syncing) are deliberately not attempted anywhere in this plan.
- **Placeholder scan:** no TBDs; every step has complete code.
- **Type consistency checked:** `custom_events.create_event(course_id, date, time, title, event_type)` is defined once in Task 1 and called identically (same argument order) in Task 1's own tests and Task 3's view. `sync_event_to_calendar(user, event_id)` is defined in Task 2 and called identically in Task 2's tests, Task 3's view, and Task 3's tests. `EventNotFoundError`/`AlreadySyncedError`/`CalendarAuthError` are raised in Tasks 1/2 and caught by name in Task 3's views. `reminders.list_all_deadlines()`'s output shape (`source`, `synced`, `id`, `time`, `course_id`, `date`, `title`, `type`) is produced in Task 2 and consumed identically by Task 3's `DeadlinesView.get` (passed straight through) and Task 4's JS (`d.source`, `d.synced`, `d.id`, etc. — same spelling throughout, no drift).
- **`calendar_sync.get_credentials` reuse confirmed correct:** Task 2 renames the existing private `_get_credentials` to public `get_credentials` with no behavior change (verified its one pre-existing call site and its two test-file mentions are both safe — no test patches the private name directly, only `Credentials.refresh` and `agent.services.calendar_sync.build`), then `custom_events.sync_event_to_calendar` calls it via `calendar_sync.get_credentials(google_account)`, exactly mirroring `calendar_sync.add_deadline_to_calendar`'s own usage.
- **Google API mocking confirmed correct:** every new test patches `agent.services.custom_events.calendar_sync.build` (the name as looked up from `custom_events.py`'s own `calendar_sync` module reference), matching the existing Calendar sync feature's own convention of patching `agent.services.calendar_sync.build` from wherever it's consumed.
