import pytest

from agent.services import storage

pytestmark = pytest.mark.django_db


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


def test_read_calendar_sync_ignores_legacy_corrupt_json(isolated_courses_dir):
    course_dir = isolated_courses_dir / "cs101"
    course_dir.mkdir(parents=True)
    (course_dir / "calendar_sync.json").write_text("{not valid json", encoding="utf-8")

    assert storage.read_calendar_sync("cs101") == []
