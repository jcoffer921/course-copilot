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


def test_list_all_deadlines_never_raises_on_corrupt_calendar_sync_file(isolated_courses_dir):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}])
    course_dir = isolated_courses_dir / "cs101"
    (course_dir / "calendar_sync.json").write_text("{not valid json", encoding="utf-8")

    deadlines = reminders.list_all_deadlines()

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Final Exam"]["synced"] is False
