from datetime import date, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from agent.models import CourseMaterial
from agent.services import calendar_events, custom_events, dashboard, reminders, storage


pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="calendar-owner", email="calendar@example.com")


def _future(days=7):
    return (date.today() + timedelta(days=days)).isoformat()


def _seed_syllabus(user, dates, course_id="cs101"):
    storage.write_syllabus(
        course_id,
        {
            "course_id": course_id,
            "course_name": "Computer Science",
            "dates": dates,
            "grading": [],
            "topics": [],
        },
        user,
    )


def _material(user, course_id="cs101", *, status="ready", review="confirmed", extracted_data=None):
    return CourseMaterial.objects.create(
        user=user,
        course_id=course_id,
        original_filename="syllabus.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS,
        processing_status=status,
        review_status=review,
        storage_key=f"material-{CourseMaterial.objects.count()}",
        size_bytes=10,
        content_type="application/pdf",
        extracted_data=extracted_data,
        confirmed_at=timezone.now() if review == CourseMaterial.REVIEW_CONFIRMED else None,
    )


def test_canonical_read_model_exposes_timed_all_day_and_source_fields(isolated_courses_dir, user):
    due = _future()
    _seed_syllabus(user, [{"date": due, "title": "Midterm", "type": "exam"}])
    material = _material(user)
    custom_events.create_event(
        "cs101",
        due,
        "13:00",
        "Review session",
        "class",
        user=user,
        end_time="14:30",
        estimated_effort_minutes=90,
        source_material_id=material.material_id,
    )

    events = calendar_events.all_events(user)
    syllabus_event = next(event for event in events if event["source"] == "syllabus")
    manual_event = next(event for event in events if event["source"] == "manual")

    assert syllabus_event["all_day"] is True
    assert syllabus_event["start_time"] is None
    assert syllabus_event["confirmed"] is True
    assert syllabus_event["source_material_id"] == str(material.material_id)
    assert syllabus_event["course_color"].startswith("#")
    assert manual_event["all_day"] is False
    assert manual_event["start_time"] == "13:00"
    assert manual_event["end_time"] == "14:30"
    assert manual_event["estimated_effort_minutes"] == 90
    assert manual_event["source_material_id"] == str(material.material_id)


def test_syllabus_event_id_is_stable_when_converted_to_editable_override(isolated_courses_dir, user):
    due = _future()
    _seed_syllabus(user, [{"date": due, "title": "Project", "type": "assignment"}])
    original = calendar_events.all_events(user)[0]

    replacement = custom_events.create_event(
        "cs101",
        due,
        "16:00",
        "Project",
        "assignment",
        user=user,
        replaces_syllabus_key=original["key"],
    )
    updated = custom_events.update_event(replacement["id"], user=user, title="Project final")
    visible = calendar_events.all_events(user)

    assert replacement["id"] == original["id"]
    assert updated["id"] == original["id"]
    assert [event["id"] for event in visible] == [original["id"]]
    assert visible[0]["title"] == "Project final"
    assert visible[0]["source"] == "manual"


def test_pending_syllabus_candidate_dates_are_not_calendar_events(isolated_courses_dir, user):
    trusted_date = _future(4)
    pending_date = _future(5)
    _seed_syllabus(user, [{"date": trusted_date, "title": "Confirmed quiz", "type": "quiz"}])
    _material(
        user,
        status=CourseMaterial.STATUS_NEEDS_REVIEW,
        review=CourseMaterial.REVIEW_PENDING,
        extracted_data={
            "course_id": "cs101",
            "dates": [{"date": pending_date, "title": "Unreviewed final", "type": "exam"}],
        },
    )

    events = calendar_events.all_events(user)

    assert [(event["date"], event["title"]) for event in events] == [
        (trusted_date, "Confirmed quiz")
    ]


def test_source_material_must_be_ready_owned_and_in_same_course(isolated_courses_dir, user, django_user_model):
    other = django_user_model.objects.create_user(username="other-calendar", email="other@example.com")
    other_material = _material(other)

    with pytest.raises(ValueError, match="ready material in this course"):
        custom_events.create_event(
            "cs101",
            _future(),
            None,
            "Private source test",
            "other",
            user=user,
            source_material_id=other_material.material_id,
        )


def test_dashboard_and_calendar_use_identical_event_facts(isolated_courses_dir, user):
    due = _future(3)
    _seed_syllabus(user, [{"date": due, "title": "Quiz", "type": "quiz"}])
    custom_events.create_event("cs101", due, "15:00", "Study block", "class", user=user)

    calendar_rows = reminders.list_all_deadlines(user=user)
    dashboard_rows = dashboard.build_dashboard(user=user)["deadlines"]
    facts = lambda rows: {
        (row["id"], row["date"], row["title"], row["source"], row["start_time"])
        for row in rows
    }

    assert facts(dashboard_rows) == facts(calendar_rows)


def test_date_only_deadline_does_not_shift_with_display_timezone(isolated_courses_dir, user):
    due = _future(8)
    _seed_syllabus(user, [{"date": due, "title": "Date only", "type": "other"}])

    with override_settings(TIME_ZONE="Pacific/Kiritimati"):
        east_date = calendar_events.all_events(user)[0]["date"]
    with override_settings(TIME_ZONE="Pacific/Pago_Pago"):
        west_date = calendar_events.all_events(user)[0]["date"]

    assert east_date == west_date == due


def test_study_plan_events_are_explicitly_labeled(isolated_courses_dir, user):
    event = custom_events.create_event(
        None,
        _future(),
        None,
        "Plan reading",
        "other",
        user=user,
        source="study_plan",
        estimated_effort_minutes=30,
    )

    visible = calendar_events.all_events(user)

    assert visible[0]["id"] == event["id"]
    assert visible[0]["source"] == "study_plan"
    assert visible[0]["estimated_effort_minutes"] == 30


def test_calendar_snapshot_includes_course_metadata_and_general_events(isolated_courses_dir, user):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Computer Science",
        "dates": [{"date": "2026-09-03", "title": "Homework", "type": "hw"}],
        "grading": [], "topics": [],
    }, user)
    custom_events.create_event(None, "2026-09-04", "14:00", "Study group", "other", user=user)

    snapshot = calendar_events.calendar_snapshot(user)

    assert snapshot["courses"][0]["name"] == "Computer Science"
    assert {event["title"] for event in snapshot["events"]} == {"Homework", "Study group"}
    assert next(event for event in snapshot["events"] if event["title"] == "Study group")["course_name"] == "Unassigned"
    assert snapshot["warnings"] == []


def test_calendar_snapshot_isolates_corrupt_course(isolated_courses_dir, user):
    storage.write_syllabus("good101", {
        "course_id": "good101", "course_name": "Good",
        "dates": [{"date": "2026-09-03", "title": "Good event", "type": "hw"}],
        "grading": [], "topics": [],
    }, user)
    corrupt = isolated_courses_dir / str(user.pk) / "bad101"
    corrupt.mkdir(parents=True)
    (corrupt / "syllabus.json").write_text("{bad json", encoding="utf-8")

    snapshot = calendar_events.calendar_snapshot(user)

    assert [event["title"] for event in snapshot["events"]] == ["Good event"]
    assert snapshot["warnings"] == [{"scope": "bad101", "detail": "BAD101 could not be loaded."}]


def test_all_events_isolates_corrupt_course(isolated_courses_dir, user):
    # all_events() backs the exam workspace/plan/study-guide views, so it
    # must isolate a bad syllabus the same way its sibling calendar_snapshot()
    # already does — a single corrupt course shouldn't 500 every course's view.
    storage.write_syllabus("good101", {
        "course_id": "good101", "course_name": "Good",
        "dates": [{"date": "2026-09-03", "title": "Good event", "type": "hw"}],
        "grading": [], "topics": [],
    }, user)
    corrupt = isolated_courses_dir / str(user.pk) / "bad101"
    corrupt.mkdir(parents=True)
    (corrupt / "syllabus.json").write_text("{bad json", encoding="utf-8")

    events = calendar_events.all_events(user)

    assert [event["title"] for event in events] == ["Good event"]
