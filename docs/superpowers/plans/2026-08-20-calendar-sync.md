# Google Calendar Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a signed-in user push an individual syllabus deadline into their real Google Calendar, one click at a time, from the Dashboard's existing "Upcoming deadlines" panel.

**Architecture:** A new `agent/services/calendar_sync.py` builds/refreshes a `google.oauth2.credentials.Credentials` object from the signed-in user's stored `GoogleAccount` tokens and calls the Google Calendar API (`google-api-python-client`, a new dependency) to insert one all-day event. A new per-course `calendar_sync.json` (read/write helpers added to `storage.py`, following the same "absent file = normal state" convention as `trusted_domains.json`) records every deadline already pushed, keyed by `(date, title)`, so `dashboard.py` can annotate each deadline `synced: true/false` and the UI can block duplicate pushes. One new endpoint, `POST /api/courses/<course_id>/calendar-sync/`, wires it to an "Add to Calendar" action added to each row of the Dashboard's existing Upcoming panel.

**Tech Stack:** Django (existing `GoogleAccount` model + OAuth tokens from the Google Sign-In feature), `google-api-python-client` (new dependency), `google-auth` (already installed), pytest + pytest-django, DC component templating in `ontrack.html`.

## Global Constraints

- One event at a time. No bulk "sync everything" action, no dry-run flag — clicking "Add to Calendar" on one specific deadline row IS the explicit per-event confirmation.
- `courses/<course_id>/calendar_sync.json` tracks every deadline already pushed, keyed by `(date, title)` (syllabus dates have no stable ID). A second push attempt for an already-synced `(date, title)` must be refused, not create a duplicate Google Calendar event.
- No `manage.py` CLI wrapper for this feature — UI + API only.
- New dependency: `google-api-python-client`.
- `GoogleAccount.access_token` may be expired by the time a user clicks "Add to Calendar." The service must refresh it transparently via the stored `refresh_token` and persist the refreshed token/expiry back onto `GoogleAccount`. If refresh itself fails, the endpoint must return a clean, handled error — never an unhandled 500.
- Events are all-day, matching `syllabus.json`'s date-only deadline data. Google Calendar's all-day event API requires an exclusive end date (start date + 1 day).
- Non-goals (do not build): a calendar grid/month view, two-way sync (reading the user's existing Google Calendar events back into OnTrack), un-syncing/deleting a previously-created event from OnTrack's side.

---

## Task 1: `calendar_sync.json` storage helpers + the calendar sync service

**Files:**
- Modify: `agent/services/storage.py`
- Create: `agent/services/calendar_sync.py`
- Modify: `requirements.txt`
- Test: `agent/tests/test_storage_calendar_sync.py`, `agent/tests/test_calendar_sync.py`

**Interfaces:**
- Consumes: `agent.models.GoogleAccount` (fields: `access_token`, `refresh_token`, `token_expiry`), `django.contrib.auth.models.User.google_account` (related_name from `GoogleAccount.user`)
- Produces: `agent.services.storage.read_calendar_sync(course_id: str) -> list`, `agent.services.storage.append_calendar_sync_record(course_id: str, record: dict) -> Path`, `agent.services.storage.CalendarSyncStorageError`, `agent.services.calendar_sync.add_deadline_to_calendar(user, course_id: str, date: str, title: str, event_type: str) -> dict`, `agent.services.calendar_sync.AlreadySyncedError`, `agent.services.calendar_sync.CalendarAuthError`

- [ ] **Step 1: Add the new dependency**

In `requirements.txt`, add after `google-auth-oauthlib>=1.2.0`:

```
google-api-python-client>=2.150.0
```

Run: `venv/Scripts/python.exe -m pip install -r requirements.txt`
Expected: installs `google-api-python-client` and its dependencies (`google-api-core`, `httplib2`, `uritemplate`, etc.) with no errors.

- [ ] **Step 2: Write the failing tests for the storage helpers**

Create `agent/tests/test_storage_calendar_sync.py`:

```python
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_calendar_sync_returns_empty_list_when_file_absent(isolated_courses_dir):
    assert storage.read_calendar_sync("cs101") == []


def test_append_calendar_sync_record_writes_and_reads_back(isolated_courses_dir):
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-123", "synced_at": "2026-08-20T00:00:00+00:00",
    })

    records = storage.read_calendar_sync("cs101")

    assert records == [{
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-123", "synced_at": "2026-08-20T00:00:00+00:00",
    }]


def test_append_calendar_sync_record_accumulates_across_calls(isolated_courses_dir):
    storage.append_calendar_sync_record("cs101", {"date": "2026-09-01", "title": "Midterm", "type": "exam", "google_event_id": "evt-1", "synced_at": "x"})
    storage.append_calendar_sync_record("cs101", {"date": "2026-09-15", "title": "Final", "type": "exam", "google_event_id": "evt-2", "synced_at": "x"})

    records = storage.read_calendar_sync("cs101")

    assert len(records) == 2
    assert {r["google_event_id"] for r in records} == {"evt-1", "evt-2"}


def test_read_calendar_sync_raises_on_corrupt_json(isolated_courses_dir):
    course_dir = isolated_courses_dir / "cs101"
    course_dir.mkdir(parents=True)
    (course_dir / "calendar_sync.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(storage.CalendarSyncStorageError):
        storage.read_calendar_sync("cs101")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_calendar_sync.py -v`
Expected: FAIL — `AttributeError: module 'agent.services.storage' has no attribute 'read_calendar_sync'` (and similarly for the other new names).

- [ ] **Step 4: Add the storage helpers**

In `agent/services/storage.py`, add this exception class alongside the other `*StorageError` classes (near `GradesStorageError`):

```python
class CalendarSyncStorageError(Exception):
    """Raised when calendar_sync.json exists but is corrupt."""
```

Then add these two functions near `read_quiz_history`/`append_quiz_attempt` (same append-only-log shape):

```python
def read_calendar_sync(course_id: str) -> list:
    """Returns the list of deadlines already pushed to Google Calendar for
    this course, or [] if calendar_sync.json doesn't exist yet — no
    deadlines synced yet is the normal starting state, same "doesn't exist
    yet = normal state" convention as trusted_domains.json."""
    path = _course_dir(course_id) / "calendar_sync.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CalendarSyncStorageError(f"calendar_sync.json for '{course_id}' is corrupt: {e}")
    return data.get("synced", [])


def append_calendar_sync_record(course_id: str, record: dict) -> Path:
    """Appends one synced-deadline record to calendar_sync.json — an
    append-only log, mirroring append_quiz_attempt. OnTrack never un-syncs
    a Google Calendar event from its own side, so nothing ever rewrites or
    removes an existing entry."""
    synced = read_calendar_sync(course_id)
    synced.append(record)

    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "calendar_sync.json"
    out_path.write_text(json.dumps({"course_id": course_id, "synced": synced}, indent=2), encoding="utf-8")
    return out_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_calendar_sync.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Write the failing tests for the calendar sync service**

Create `agent/tests/test_calendar_sync.py`:

```python
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from agent.models import GoogleAccount
from agent.services import calendar_sync, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


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
    """Mocks googleapiclient.discovery.build("calendar", "v3", ...) down to
    .events().insert(...).execute()."""
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": event_id}
    return mock_service


@pytest.mark.django_db
def test_add_deadline_to_calendar_creates_event_and_records_it(isolated_courses_dir, user_with_valid_token):
    with patch("agent.services.calendar_sync.build", return_value=_mock_calendar_build("event-abc")) as build:
        result = calendar_sync.add_deadline_to_calendar(
            user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam",
        )

    assert result == {"google_event_id": "event-abc"}
    build.assert_called_once()
    records = storage.read_calendar_sync("cs101")
    assert len(records) == 1
    assert records[0]["date"] == "2026-09-01"
    assert records[0]["title"] == "Midterm"
    assert records[0]["google_event_id"] == "event-abc"


@pytest.mark.django_db
def test_add_deadline_to_calendar_sends_an_all_day_event_with_exclusive_end_date(isolated_courses_dir, user_with_valid_token):
    mock_service = _mock_calendar_build()
    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert kwargs["body"]["start"] == {"date": "2026-09-01"}
    assert kwargs["body"]["end"] == {"date": "2026-09-02"}


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_when_already_synced(isolated_courses_dir, user_with_valid_token):
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "event-abc", "synced_at": "2026-08-20T00:00:00+00:00",
    })

    with patch("agent.services.calendar_sync.build") as build:
        with pytest.raises(calendar_sync.AlreadySyncedError):
            calendar_sync.add_deadline_to_calendar(user_with_valid_token, "cs101", "2026-09-01", "Midterm", "exam")

    build.assert_not_called()


@pytest.mark.django_db
def test_add_deadline_to_calendar_refreshes_an_expired_token_and_persists_it(isolated_courses_dir, db):
    user = User.objects.create_user(username="sub-456", email="alex@example.com")
    account = GoogleAccount.objects.create(
        user=user, google_sub="sub-456", email="alex@example.com",
        access_token="stale-access-token", refresh_token="refresh-token-value",
        token_expiry=timezone.now() - timedelta(hours=1),
    )

    def _fake_refresh(self, request):
        self.token = "refreshed-access-token"
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    with patch("agent.services.calendar_sync.build", return_value=_mock_calendar_build()), \
         patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh):
        calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    account.refresh_from_db()
    assert account.access_token == "refreshed-access-token"
    assert account.token_expiry > timezone.now()


@pytest.mark.django_db
def test_add_deadline_to_calendar_raises_calendar_auth_error_when_refresh_fails(isolated_courses_dir, db):
    from google.auth.exceptions import RefreshError

    user = User.objects.create_user(username="sub-789", email="sam@example.com")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-789", email="sam@example.com",
        access_token="stale-access-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )

    def _fake_refresh_failure(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with patch("agent.services.calendar_sync.build") as build, \
         patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        with pytest.raises(calendar_sync.CalendarAuthError):
            calendar_sync.add_deadline_to_calendar(user, "cs101", "2026-09-01", "Midterm", "exam")

    build.assert_not_called()
    assert storage.read_calendar_sync("cs101") == []
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_calendar_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.services.calendar_sync'`.

- [ ] **Step 8: Create `agent/services/calendar_sync.py`**

```python
"""
Pushes individual syllabus deadlines into the signed-in user's real Google
Calendar, one event at a time. Distinct from reminders.py, which only
reads/browses deadlines and never writes anywhere.
"""

import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from . import storage


class AlreadySyncedError(Exception):
    """Raised when a (date, title) deadline has already been pushed to
    Google Calendar for this course — the UI's own synced state should
    normally prevent this call from happening at all; this is the
    server-side guard against a stale-UI or race-condition double-push."""


class CalendarAuthError(Exception):
    """Raised when the signed-in user's stored Google credentials can't be
    refreshed (revoked access, deleted consent, etc.) — callers should
    surface this as a clear, actionable message, not a raw 500."""


def _get_credentials(google_account) -> Credentials:
    """Builds a Credentials object from the stored tokens, refreshing (and
    persisting the refresh back onto google_account) if expired.

    google-auth's Credentials.expiry is a naive UTC datetime (same
    convention documented in agent/services/google_oauth.py's
    get_or_create_account) — Django's token_expiry field is timezone-aware,
    so tzinfo is stripped going in and re-attached going out."""
    expiry = google_account.token_expiry
    if expiry.tzinfo is not None:
        expiry = expiry.replace(tzinfo=None)

    credentials = Credentials(
        token=google_account.access_token,
        refresh_token=google_account.refresh_token,
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

        google_account.access_token = credentials.token
        new_expiry = credentials.expiry
        google_account.token_expiry = (
            new_expiry.replace(tzinfo=dt_timezone.utc) if new_expiry.tzinfo is None else new_expiry
        )
        google_account.save()

    return credentials


def add_deadline_to_calendar(user, course_id: str, date: str, title: str, event_type: str) -> dict:
    """Pushes one deadline into the signed-in user's Google Calendar as an
    all-day event, and records it so it's never pushed twice. Raises
    AlreadySyncedError if (date, title) is already recorded for this
    course, or CalendarAuthError if the stored Google credentials can't be
    refreshed. Returns {"google_event_id": "..."}."""
    already_synced = storage.read_calendar_sync(course_id)
    if any(r["date"] == date and r["title"] == title for r in already_synced):
        raise AlreadySyncedError(f"'{title}' on {date} is already on your Google Calendar")

    credentials = _get_credentials(user.google_account)

    start_date = datetime.strptime(date, "%Y-%m-%d").date()
    end_date = (start_date + timedelta(days=1)).isoformat()

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

    storage.append_calendar_sync_record(course_id, {
        "date": date, "title": title, "type": event_type,
        "google_event_id": event["id"], "synced_at": timezone.now().isoformat(),
    })

    return {"google_event_id": event["id"]}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_calendar_sync.py -v`
Expected: PASS (5 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures (the 9 new tests plus every pre-existing test, unchanged).

- [ ] **Step 10: Commit**

```bash
git add requirements.txt agent/services/storage.py agent/services/calendar_sync.py agent/tests/test_storage_calendar_sync.py agent/tests/test_calendar_sync.py
git commit -m "feat: add Google Calendar sync service (push one deadline at a time)"
```

---

## Task 2: Annotate dashboard deadlines with sync status

**Files:**
- Modify: `agent/services/dashboard.py`
- Test: `agent/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `agent.services.storage.read_calendar_sync` (Task 1)
- Produces: every deadline dict in `build_dashboard()`'s `"deadlines"` list now includes a `"synced": bool` key

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_dashboard.py` (the file already defines `isolated_courses_dir` and `_seed_course` — reuse them):

```python
def test_build_dashboard_marks_synced_deadlines(isolated_courses_dir):
    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[
            {"date": "2099-01-05", "title": "Midterm", "type": "exam"},
            {"date": "2099-01-20", "title": "Final", "type": "exam"},
        ],
    )
    storage.append_calendar_sync_record("cs101", {
        "date": "2099-01-05", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    })

    data = dashboard.build_dashboard()

    by_title = {d["title"]: d for d in data["deadlines"]}
    assert by_title["Midterm"]["synced"] is True
    assert by_title["Final"]["synced"] is False


def test_build_dashboard_deadlines_unsynced_when_no_calendar_sync_file(isolated_courses_dir):
    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": "2099-01-05", "title": "Midterm", "type": "exam"}],
    )

    data = dashboard.build_dashboard()

    assert data["deadlines"][0]["synced"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -k synced -v`
Expected: FAIL — `KeyError: 'synced'`.

- [ ] **Step 3: Add the annotation in `dashboard.py`**

Add this function above `build_dashboard()`:

```python
def _annotate_synced(deadlines: list) -> list:
    """Marks each deadline with whether it's already been pushed to Google
    Calendar, by cross-referencing that course's calendar_sync.json (read
    once per distinct course_id present in the list, not once per
    deadline)."""
    synced_by_course = {}
    annotated = []
    for d in deadlines:
        course_id = d["course_id"]
        if course_id not in synced_by_course:
            synced_by_course[course_id] = storage.read_calendar_sync(course_id)
        is_synced = any(
            r["date"] == d["date"] and r["title"] == d["title"]
            for r in synced_by_course[course_id]
        )
        annotated.append(dict(d, synced=is_synced))
    return annotated
```

Then change the `"deadlines"` line inside `build_dashboard()`:

```python
        "deadlines": reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids),
```

to:

```python
        "deadlines": _annotate_synced(reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids)),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: all PASS.

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 5: Commit**

```bash
git add agent/services/dashboard.py agent/tests/test_dashboard.py
git commit -m "feat: annotate dashboard deadlines with Google Calendar sync status"
```

---

## Task 3: API endpoint

**Files:**
- Modify: `agent/serializers.py`
- Modify: `agent/views.py`
- Modify: `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `agent.services.calendar_sync.add_deadline_to_calendar`, `agent.services.calendar_sync.AlreadySyncedError`, `agent.services.calendar_sync.CalendarAuthError` (Task 1)
- Produces: `POST /api/courses/<course_id>/calendar-sync/`, URL name `calendar-sync`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`. First check the top of the file for its existing `api_client` fixture (it authenticates a plain `django_user_model` user with no `GoogleAccount` — these new tests need a real `GoogleAccount` on that user, so build their own client rather than reusing the shared fixture):

```python
@pytest.mark.django_db
def test_calendar_sync_creates_event(isolated_courses_dir):
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

    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "event-abc"}
    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        response = client.post(
            "/api/courses/cs101/calendar-sync/",
            {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
            format="json",
        )

    assert response.status_code == 201
    assert response.data == {"google_event_id": "event-abc"}


@pytest.mark.django_db
def test_calendar_sync_rejects_duplicate(isolated_courses_dir):
    from datetime import timedelta

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleAccount
    from agent.services import storage

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    })
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/courses/cs101/calendar-sync/",
        {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
        format="json",
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_calendar_sync_returns_502_when_google_auth_fails(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
        access_token="stale-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    def _fake_refresh_failure(self, request):
        from google.auth.exceptions import RefreshError
        raise RefreshError("invalid_grant")

    with patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        response = client.post(
            "/api/courses/cs101/calendar-sync/",
            {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
            format="json",
        )

    assert response.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k calendar_sync -v`
Expected: FAIL — 404s (route doesn't exist yet).

- [ ] **Step 3: Add the request serializer**

In `agent/serializers.py`, at the very top of the file, change:

```python
from rest_framework import serializers


class ExtractSyllabusRequestSerializer(serializers.Serializer):
```

to:

```python
from rest_framework import serializers


class CalendarSyncRequestSerializer(serializers.Serializer):
    date = serializers.CharField(allow_blank=False)
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)


class ExtractSyllabusRequestSerializer(serializers.Serializer):
```

- [ ] **Step 4: Add the view**

In `agent/views.py`, change the two import lines:

```python
from .serializers import (
    AddGradeItemRequestSerializer,
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    ChunkNotesRequestSerializer,
    CreateCourseDraftRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
    UpdateGradeItemRequestSerializer,
)
from .services import chunk_notes, dashboard, domain_suggestions, grades, mastery, quiz, references, reminders, sessions, storage
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
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
    UpdateGradeItemRequestSerializer,
)
from .services import calendar_sync, chunk_notes, dashboard, domain_suggestions, grades, mastery, quiz, references, reminders, sessions, storage
```

Then add this class right after `DashboardView` (i.e., immediately before `class SyllabusDetailView(APIView):`):

```python
class CalendarSyncView(APIView):
    """
    POST /api/courses/<course_id>/calendar-sync/
    body: {"date": "YYYY-MM-DD", "title": "...", "type": "exam|assignment|reading|other"}

    Pushes one deadline into the signed-in user's real Google Calendar as
    an all-day event. 409 if that (date, title) was already synced; 502 if
    the user's stored Google credentials can't be refreshed.
    """

    async def post(self, request, course_id):
        serializer = CalendarSyncRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = await sync_to_async(calendar_sync.add_deadline_to_calendar)(
                request.user, course_id,
                serializer.validated_data["date"],
                serializer.validated_data["title"],
                serializer.validated_data["type"],
            )
        except calendar_sync.AlreadySyncedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except calendar_sync.CalendarAuthError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_201_CREATED)
```

- [ ] **Step 5: Wire the URL**

In `agent/urls.py`, add (right after the `grading-config` line, keeping the course-scoped routes grouped together):

```python
    path("courses/<slug:course_id>/calendar-sync/", views.CalendarSyncView.as_view(), name="calendar-sync"),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k calendar_sync -v`
Expected: PASS (3 passed).

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 7: Commit**

```bash
git add agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add POST /api/courses/<id>/calendar-sync/ endpoint"
```

---

## Task 4: Wire "Add to Calendar" into the Dashboard's Upcoming panel

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `POST /api/courses/<course_id>/calendar-sync/` (Task 3), `data.deadlines[].synced` from `GET /api/dashboard/` (Task 2)

This task is browser-side only — no new Python. All edits are to `agent/templates/agent/ontrack.html`. Search for each block by its exact content, not by line number (this file has shifted line numbers repeatedly across prior work).

- [ ] **Step 1: Add sync-tracking state**

Find this line in the `state = {` block:

```javascript
    courseMeta: null, courseDrafts: [], dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
```

Change it to:

```javascript
    courseMeta: null, courseDrafts: [], dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
    dashboardSyncingKeys: {}, dashboardSyncError: null,
```

- [ ] **Step 2: Add the `addToCalendar` method**

Find this exact block (the end of `loadDashboardRecent`, right before `loadChatSessions` begins):

```javascript
      .catch(e => {
        if (seq !== this._recentSeq) return;
        this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message });
      });
  }

  loadChatSessions(courseId) {
```

Replace it with (inserting the new method between the two existing ones):

```javascript
      .catch(e => {
        if (seq !== this._recentSeq) return;
        this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message });
      });
  }

  addToCalendar(courseId, date, title, type, key) {
    if (this.state.dashboardSyncingKeys[key]) return;
    this.setState({
      dashboardSyncingKeys: Object.assign({}, this.state.dashboardSyncingKeys, { [key]: true }),
      dashboardSyncError: null
    });
    fetch(`/api/courses/${courseId}/calendar-sync/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ date: date, title: title, type: type })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        if (!ok) { this.setState({ dashboardSyncingKeys: syncing, dashboardSyncError: data.detail || 'Could not add to Google Calendar.' }); return; }
        const deadlines = this.state.dashboardDeadlines.map(d =>
          (d.date === date && d.title === title) ? Object.assign({}, d, { synced: true }) : d
        );
        this.setState({ dashboardSyncingKeys: syncing, dashboardDeadlines: deadlines });
      })
      .catch(e => {
        const syncing = Object.assign({}, this.state.dashboardSyncingKeys);
        delete syncing[key];
        this.setState({ dashboardSyncingKeys: syncing, dashboardSyncError: 'Network error: ' + e.message });
      });
  }

  loadChatSessions(courseId) {
```

Note: the original `loadChatSessions(courseId) {` line is part of the matched block above and must be preserved verbatim at the end of the replacement — the new method is inserted between the two existing ones, nothing is deleted.

- [ ] **Step 3: Wire the deadlines row mapping in `renderVals()`**

Find this exact block:

```javascript
    const deadlines = s.dashboardDeadlines.filter(d => s.course === 'all' || d.course_id === s.course).map(d => {
      const dp = dateParts(d.date);
      return {
        month: dp.monthAbbrUpper, day: dp.day, title: d.title,
        typeLabel: d.type === 'exam' ? 'Exam' : d.type === 'assignment' ? 'Assignment' : 'Other',
        tagStyle: typeStyle(d.type)
      };
    });
```

Replace it with:

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

- [ ] **Step 4: Expose `dashboardSyncError` from `renderVals()`**

Find this line (the top-level dashboard error wiring):

```javascript
      showDashboardError: !!s.dashboardError && !s.courseMeta,
      dashboardError: s.dashboardError,
      retryDashboard: retryDashboard,
```

Change it to:

```javascript
      showDashboardError: !!s.dashboardError && !s.courseMeta,
      dashboardError: s.dashboardError,
      retryDashboard: retryDashboard,
      showDashboardSyncError: !!s.dashboardSyncError,
      dashboardSyncError: s.dashboardSyncError,
```

- [ ] **Step 5: Add the "Add to Calendar" action and synced badge to each deadline row**

Find this exact block in the template markup (the Upcoming deadlines panel's row):

```html
                <sc-for list="{{ deadlines }}" as="d" hint-placeholder-count="4">
                  <div style="display:flex;align-items:center;gap:var(--space-3);padding:11px 4px;border-bottom:1px solid var(--color-neutral-200)">
                    <div style="width:44px;flex:none;text-align:center;font-family:var(--font-heading);font-size:12px;color:var(--color-accent-700);line-height:1.15">{{ d.month }}<br/><span style="font-size:16px">{{ d.day }}</span></div>
                    <div style="flex:1;min-width:0;font-size:14px;font-weight:600">{{ d.title }}</div>
                    <span style="{{ d.tagStyle }}">{{ d.typeLabel }}</span>
                  </div>
                </sc-for>
```

Replace it with:

```html
                <sc-for list="{{ deadlines }}" as="d" hint-placeholder-count="4">
                  <div style="display:flex;align-items:center;gap:var(--space-3);padding:11px 4px;border-bottom:1px solid var(--color-neutral-200)">
                    <div style="width:44px;flex:none;text-align:center;font-family:var(--font-heading);font-size:12px;color:var(--color-accent-700);line-height:1.15">{{ d.month }}<br/><span style="font-size:16px">{{ d.day }}</span></div>
                    <div style="flex:1;min-width:0;font-size:14px;font-weight:600">{{ d.title }}</div>
                    <span style="{{ d.tagStyle }}">{{ d.typeLabel }}</span>
                    <sc-if value="{{ d.synced }}" hint-placeholder-val="{{ false }}">
                      <span class="tag tag-accent-2" style="flex:none">Added ✓</span>
                    </sc-if>
                    <sc-if value="{{ !d.synced }}" hint-placeholder-val="{{ true }}">
                      <button type="button" class="btn btn-secondary" style="flex:none;padding:4px 10px;font-size:12px" onClick="{{ d.onAddToCalendar }}">{{ d.addButtonLabel }}</button>
                    </sc-if>
                  </div>
                </sc-for>
```

- [ ] **Step 6: Show sync errors inline**

Find this exact block (right after the panel's description text):

```html
              <p style="font-size:13px;opacity:.75;margin:0 0 var(--space-4)">For {{ scopeLabel }} in the next two weeks.</p>
              <div style="display:flex;flex-direction:column;gap:0">
```

Replace it with:

```html
              <p style="font-size:13px;opacity:.75;margin:0 0 var(--space-4)">For {{ scopeLabel }} in the next two weeks.</p>
              <sc-if value="{{ showDashboardSyncError }}" hint-placeholder-val="{{ false }}">
                <p style="font-size:12.5px;color:var(--color-accent-700);margin:0 0 var(--space-3)">{{ dashboardSyncError }}</p>
              </sc-if>
              <div style="display:flex;flex-direction:column;gap:0">
```

- [ ] **Step 7: Manual verification (required)**

Start the dev server: `venv/Scripts/python.exe -m uvicorn config.asgi:application --port 8000`

With a real Google Cloud OAuth client and `ALLOWED_GOOGLE_EMAILS` already configured (per the Google Sign-In feature's own setup) and at least one course with a future-dated syllabus deadline:

1. Sign in, land on the Dashboard. Confirm each row in "Upcoming deadlines" now shows an "Add to Calendar" button.
2. Click it on one deadline. Confirm the button briefly reads "Adding…", then the row switches to an "Added ✓" badge with no button — with no full-page reload.
3. Open your actual Google Calendar (calendar.google.com) and confirm the event appears on the correct date, as an all-day event, titled with the deadline's title and course.
4. Refresh the OnTrack page. Confirm the same deadline still shows "Added ✓" (not a fresh "Add to Calendar" button) — proves the `synced` annotation round-trips correctly from `calendar_sync.json`.
5. Manually edit that course's `courses/<course_id>/calendar_sync.json` to confirm it recorded the real Google event ID and a `synced_at` timestamp.

Stop the dev server when done.

- [ ] **Step 8: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: add \"Add to Calendar\" action to the Dashboard's Upcoming panel"
```

---

## Self-Review Notes

- **Spec coverage:** implements every section of `docs/superpowers/specs/2026-08-20-calendar-sync-design.md` — the service + credential refresh (Task 1), the `synced` annotation (Task 2), the API endpoint (Task 3), and the UI wiring (Task 4). The spec's non-goals (calendar grid view, two-way sync, un-syncing, CLI wrapper) are deliberately not attempted anywhere in this plan.
- **Placeholder scan:** no TBDs; every step has complete code.
- **Type consistency checked:** `calendar_sync.add_deadline_to_calendar(user, course_id, date, title, event_type)` is defined once in Task 1 and called identically (same argument order) in Task 1's own tests, Task 3's view, and Task 3's tests. `AlreadySyncedError`/`CalendarAuthError` are raised in Task 1 and caught by name in Task 3's view. `storage.read_calendar_sync`/`append_calendar_sync_record` are defined in Task 1 and consumed identically by Task 1's own service, Task 2's `dashboard.py`, and every test file that seeds fixture data. The `synced` key name is produced by Task 2 and consumed identically by Task 4's JS (`d.synced`) — same spelling throughout.
- **Google API mocking confirmed correct:** `googleapiclient.discovery.build` is imported directly into `agent.services.calendar_sync`'s module namespace (`from googleapiclient.discovery import build`), so every test patches `agent.services.calendar_sync.build` (not `googleapiclient.discovery.build`) — patching the name where it's looked up, not where it's defined, matching this codebase's existing mocking convention for `google_oauth.build_flow` in the Google Sign-In feature's own tests.
