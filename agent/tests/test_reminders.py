import pytest

from agent.services import custom_events, reminders, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="owner", email="owner@example.com")


def _seed_syllabus(course_id, dates, user):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": dates, "grading": [], "topics": [],
    }, user)


def test_list_all_deadlines_combines_syllabus_and_custom(isolated_courses_dir, user):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()  # well outside the 14-day dashboard window, proving this is unbounded
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}], user)
    custom_events.create_event("cs101", far_date, None, "Study session", "other", user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    sources = {d["title"]: d["source"] for d in deadlines}
    assert sources["Final Exam"] == "syllabus"
    assert sources["Study session"] == "manual"


def test_list_all_deadlines_can_filter_to_one_course(isolated_courses_dir, user):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "CS Final", "type": "exam"}], user)
    _seed_syllabus("math201", [{"date": far_date, "title": "Math Final", "type": "exam"}], user)
    custom_events.create_event(None, far_date, None, "General break", "other", user=user)

    deadlines = reminders.list_all_deadlines(user=user, course_id="cs101")

    assert [d["title"] for d in deadlines] == ["CS Final"]


def test_custom_replacement_hides_matching_syllabus_deadline(isolated_courses_dir, user):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Project Due", "type": "assignment"}], user)
    original = reminders.list_all_deadlines(user=user)[0]

    custom_events.create_event(
        "cs101",
        far_date,
        "15:00",
        "Project draft due",
        "assignment",
        replaces_syllabus_key=original["key"],
        user=user,
    )

    deadlines = reminders.list_all_deadlines(user=user, course_id="cs101")

    assert [d["title"] for d in deadlines] == ["Project draft due"]
    assert deadlines[0]["source"] == "manual"


def test_general_custom_replacement_hides_original_in_course_filter(isolated_courses_dir, user):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "No class", "type": "other"}], user)
    original = reminders.list_all_deadlines(user=user, course_id="cs101")[0]

    custom_events.create_event(
        None,
        far_date,
        None,
        "Campus holiday",
        "other",
        replaces_syllabus_key=original["key"],
        user=user,
    )

    assert reminders.list_all_deadlines(user=user, course_id="cs101") == []
    assert [d["title"] for d in reminders.list_all_deadlines(user=user)] == ["Campus holiday"]


def test_list_all_deadlines_marks_synced_syllabus_deadline(isolated_courses_dir, user):
    from datetime import date, timedelta
    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}], user)
    storage.append_calendar_sync_record("cs101", {
        "date": far_date, "title": "Final Exam", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    }, user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Final Exam"]["synced"] is True


def test_list_all_deadlines_marks_synced_custom_event(isolated_courses_dir, user):
    created = custom_events.create_event("cs101", "2026-09-01", None, "Study session", "other", user=user)
    custom_events.update_event(created["id"], user=user, synced=True, google_event_id="evt-2")

    deadlines = reminders.list_all_deadlines(user=user)

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Study session"]["synced"] is True


def test_list_all_deadlines_includes_general_custom_event(isolated_courses_dir, user):
    custom_events.create_event(None, "2026-11-26", None, "Thanksgiving break", "other", user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    assert any(d["title"] == "Thanksgiving break" and d["course_id"] is None for d in deadlines)


def test_list_all_deadlines_excludes_past_custom_events(isolated_courses_dir, user):
    custom_events.create_event("cs101", "2020-01-01", None, "Long past", "other", user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    assert deadlines == []


def test_list_all_deadlines_includes_incomplete_overdue_assignments(isolated_courses_dir, user):
    custom_events.create_event("cs101", "2020-01-01", None, "Past homework", "hw", user=user)
    custom_events.create_event("cs101", "2020-01-01", None, "Past project", "project", completed=True, user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    assert [d["title"] for d in deadlines] == ["Past homework"]


def test_list_all_deadlines_sorted_by_date(isolated_courses_dir, user):
    custom_events.create_event("cs101", "2099-03-01", None, "Later", "other", user=user)
    custom_events.create_event("cs101", "2099-01-01", None, "Earlier", "other", user=user)

    deadlines = reminders.list_all_deadlines(user=user)

    assert [d["title"] for d in deadlines] == ["Earlier", "Later"]


def test_list_all_deadlines_never_raises_on_corrupt_calendar_sync_file(isolated_courses_dir, user):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}], user)
    course_dir = isolated_courses_dir / str(user.pk) / "cs101"
    (course_dir / "calendar_sync.json").write_text("{not valid json", encoding="utf-8")

    deadlines = reminders.list_all_deadlines(user=user)

    by_title = {d["title"]: d for d in deadlines}
    assert by_title["Final Exam"]["synced"] is False


def test_list_all_deadlines_never_raises_on_corrupt_custom_events_file(isolated_courses_dir, user):
    # Mirrors the corrupt-calendar_sync-json case above: custom_events.json
    # corruption is isolated to an empty custom-events list rather than
    # failing the whole combined list.
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=60)).isoformat()
    _seed_syllabus("cs101", [{"date": far_date, "title": "Final Exam", "type": "exam"}], user)
    (isolated_courses_dir / str(user.pk) / "custom_events.json").write_text("{not valid json", encoding="utf-8")

    deadlines = reminders.list_all_deadlines(user=user)

    assert [d["title"] for d in deadlines] == ["Final Exam"]
