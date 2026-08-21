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
