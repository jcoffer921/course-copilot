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
