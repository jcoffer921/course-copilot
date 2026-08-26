import pytest
from django.contrib.auth.models import User

from agent.services import storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner")


def test_read_custom_events_returns_empty_list_when_file_absent(isolated_courses_dir):
    assert storage.read_custom_events() == []


def test_write_custom_events_writes_and_reads_back(isolated_courses_dir, owner):
    storage.write_custom_events([
        {"id": "abc123", "course_id": "cs101", "date": "2026-09-01", "time": None, "title": "Study group", "type": "other",
         "replaces_syllabus_key": "cs101|2026-09-01|Original|other",
         "source": "study_plan", "estimated_effort_minutes": 45,
         "synced": False, "google_event_id": None, "synced_at": None, "created_at": "2026-08-20T00:00:00+00:00"},
    ], user=owner)

    events = storage.read_custom_events(user=owner)

    assert len(events) == 1
    assert events[0]["id"] == "abc123"
    assert events[0]["title"] == "Study group"
    assert events[0]["replaces_syllabus_key"] == "cs101|2026-09-01|Original|other"
    assert events[0]["source"] == "study_plan"
    assert events[0]["estimated_effort_minutes"] == 45


def test_write_custom_events_overwrites_whole_file(isolated_courses_dir, owner):
    storage.write_custom_events([{"id": "a", "course_id": None, "date": "2026-09-01", "time": None, "title": "X", "type": "other",
                                   "synced": False, "google_event_id": None, "synced_at": None, "created_at": "x"}], user=owner)
    storage.write_custom_events([{"id": "b", "course_id": None, "date": "2026-09-02", "time": None, "title": "Y", "type": "other",
                                   "synced": False, "google_event_id": None, "synced_at": None, "created_at": "x"}], user=owner)

    events = storage.read_custom_events(user=owner)

    assert len(events) == 1
    assert events[0]["id"] == "b"


def test_read_custom_events_ignores_legacy_corrupt_json(isolated_courses_dir):
    (isolated_courses_dir / "custom_events.json").write_text("{not valid json", encoding="utf-8")

    assert storage.read_custom_events() == []


def test_private_state_rejects_anonymous_legacy_events(isolated_courses_dir):
    user = User.objects.create_user(username="jordan")
    other = User.objects.create_user(username="alex")
    storage.write_custom_events([
        {"id": "user-event", "course_id": "cs101", "date": "2026-09-02", "time": None, "title": "User", "type": "other",
         "synced": False, "google_event_id": None, "synced_at": None, "created_at": "x"},
    ], user=user)

    event_ids = {event["id"] for event in storage.read_custom_events(user=user)}
    assert event_ids == {"user-event"}
    assert storage.read_custom_events(user=other) == []
