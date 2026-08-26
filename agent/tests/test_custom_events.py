from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from agent.models import GoogleCalendarConnection
from agent.services import calendar_sync, custom_events, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner():
    return User.objects.create_user(username="event-owner")


def test_create_event_assigns_id_and_defaults(isolated_courses_dir, owner):
    event = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other", user=owner)

    assert event["course_id"] == "cs101"
    assert event["date"] == "2026-09-01"
    assert event["time"] is None
    assert event["title"] == "Study group"
    assert event["type"] == "other"
    assert event["synced"] is False
    assert event["google_event_id"] is None
    assert isinstance(event["id"], str) and event["id"]


def test_create_event_accepts_duration_and_completion(isolated_courses_dir, owner):
    event = custom_events.create_event(
        "cs101", "2026-09-01", "09:00", "Project work", "project",
        end_time="10:30", completed=True, user=owner,
    )

    assert event["end_time"] == "10:30"
    assert event["completed"] is True
    assert custom_events.list_events(user=owner)[0]["end_time"] == "10:30"


def test_create_event_rejects_end_time_without_start(isolated_courses_dir):
    with pytest.raises(ValueError):
        custom_events.create_event("cs101", "2026-09-01", None, "Project work", "project", end_time="10:30")


def test_create_event_rejects_end_time_before_start(isolated_courses_dir):
    with pytest.raises(ValueError):
        custom_events.create_event("cs101", "2026-09-01", "11:00", "Project work", "project", end_time="10:30")


def test_create_event_maps_legacy_types(isolated_courses_dir, owner):
    event = custom_events.create_event("cs101", "2026-09-01", None, "Midterm", "exam", user=owner)

    assert event["type"] == "test_quiz"


def test_create_event_general_has_null_course_id(isolated_courses_dir, owner):
    event = custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other", user=owner)

    assert event["course_id"] is None


def test_create_event_rejects_invalid_type(isolated_courses_dir):
    with pytest.raises(ValueError):
        custom_events.create_event("cs101", "2026-09-01", None, "X", "not-a-real-type")


def test_list_events_returns_created_events(isolated_courses_dir, owner):
    custom_events.create_event("cs101", "2026-09-01", None, "A", "other", user=owner)
    custom_events.create_event(None, "2026-09-02", "14:00", "B", "other", user=owner)

    events = custom_events.list_events(user=owner)

    assert len(events) == 2
    assert {e["title"] for e in events} == {"A", "B"}


def test_update_event_changes_fields(isolated_courses_dir, owner):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Original", "other", user=owner)

    updated = custom_events.update_event(created["id"], user=owner, title="Renamed", time="15:30")

    assert updated["title"] == "Renamed"
    assert updated["time"] == "15:30"
    assert updated["date"] == "2026-09-01"  # untouched field preserved
    assert custom_events.list_events(user=owner)[0]["title"] == "Renamed"


def test_update_event_validates_duration(isolated_courses_dir, owner):
    created = custom_events.create_event("cs101", "2026-09-01", "09:00", "Original", "other", user=owner)

    with pytest.raises(ValueError):
        custom_events.update_event(created["id"], user=owner, end_time="08:30")


def test_update_event_rejects_invalid_type(isolated_courses_dir, owner):
    created = custom_events.create_event("cs101", "2026-09-01", None, "X", "other", user=owner)

    with pytest.raises(ValueError):
        custom_events.update_event(created["id"], user=owner, type="not-a-real-type")


def test_update_event_raises_when_not_found(isolated_courses_dir):
    with pytest.raises(custom_events.EventNotFoundError):
        custom_events.update_event("nonexistent-id", title="X")


def test_delete_event_removes_it(isolated_courses_dir, owner):
    created = custom_events.create_event("cs101", "2026-09-01", None, "X", "other", user=owner)

    custom_events.delete_event(created["id"], user=owner)

    assert custom_events.list_events(user=owner) == []


def test_delete_event_raises_when_not_found(isolated_courses_dir):
    with pytest.raises(custom_events.EventNotFoundError):
        custom_events.delete_event("nonexistent-id")


def test_delete_events_for_course_removes_matching_events(isolated_courses_dir, owner):
    custom_events.create_event("cs101", "2026-09-01", None, "A", "other", user=owner)
    custom_events.create_event("cs101", "2026-09-02", None, "B", "other", user=owner)

    custom_events.delete_events_for_course("cs101", user=owner)

    assert custom_events.list_events(user=owner) == []


def test_delete_events_for_course_leaves_other_courses_and_general_events(isolated_courses_dir, owner):
    custom_events.create_event("cs101", "2026-09-01", None, "Delete me", "other", user=owner)
    custom_events.create_event("cs102", "2026-09-01", None, "Keep me (other course)", "other", user=owner)
    custom_events.create_event(None, "2026-09-01", None, "Keep me (general)", "other", user=owner)

    custom_events.delete_events_for_course("cs101", user=owner)

    remaining_titles = {e["title"] for e in custom_events.list_events(user=owner)}
    assert remaining_titles == {"Keep me (other course)", "Keep me (general)"}


def test_delete_events_for_course_is_a_no_op_when_none_match(isolated_courses_dir, owner):
    custom_events.create_event(None, "2026-09-01", None, "General event", "other", user=owner)

    custom_events.delete_events_for_course("cs101", user=owner)

    assert len(custom_events.list_events(user=owner)) == 1


@pytest.fixture
def user_with_valid_token(db):
    user = User.objects.create_user(username="sub-123", email="jordan@example.com")
    GoogleCalendarConnection.objects.create(
        user=user,
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
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other", user=user_with_valid_token)

    with patch("agent.services.custom_events.calendar_sync.build", return_value=_mock_calendar_build("evt-1")) as build:
        result = custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    assert result == {"google_event_id": "evt-1"}
    _, kwargs = build.return_value.events.return_value.insert.call_args
    assert kwargs["body"]["start"] == {"date": "2026-09-01"}
    assert kwargs["body"]["end"] == {"date": "2026-09-02"}

    # Syncing a legacy (pre-auth, user=NULL) event claims it for the acting
    # user — sync status is inherently per-user (each user has their own
    # Google Calendar), so it must not silently mutate what other users see.
    updated = custom_events.list_events(user=user_with_valid_token)[0]
    assert updated["synced"] is True
    assert updated["google_event_id"] == "evt-1"
    assert updated["synced_at"] is not None


@pytest.mark.django_db
def test_sync_event_to_calendar_creates_timed_event_when_time_set(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", "14:00", "Study group", "other", user=user_with_valid_token)

    mock_service = _mock_calendar_build("evt-2")
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert kwargs["body"]["start"]["dateTime"] == "2026-09-01T14:00:00"
    assert kwargs["body"]["end"]["dateTime"] == "2026-09-01T15:00:00"
    assert "timeZone" in kwargs["body"]["start"]


@pytest.mark.django_db
def test_sync_event_to_calendar_uses_explicit_end_time(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", "14:00", "Project block", "project", end_time="16:30", user=user_with_valid_token)

    mock_service = _mock_calendar_build("evt-2b")
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert kwargs["body"]["start"]["dateTime"] == "2026-09-01T14:00:00"
    assert kwargs["body"]["end"]["dateTime"] == "2026-09-01T16:30:00"


@pytest.mark.django_db
def test_sync_event_to_calendar_raises_when_already_synced(isolated_courses_dir, user_with_valid_token):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study group", "other", user=user_with_valid_token)
    custom_events.update_event(created["id"], user=user_with_valid_token, synced=True, google_event_id="already-there")

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
    created = custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other", user=user_with_valid_token)

    mock_service = _mock_calendar_build("evt-3")
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        custom_events.sync_event_to_calendar(user_with_valid_token, created["id"])

    _, kwargs = mock_service.events.return_value.insert.call_args
    assert "General" in kwargs["body"]["summary"]
