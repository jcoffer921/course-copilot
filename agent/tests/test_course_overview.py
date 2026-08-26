from datetime import date

import pytest
from rest_framework.test import APIClient

from agent.models import CourseMaterial, CourseSession, StudySession
from agent.services import course_overview, mastery, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def api_client(django_user_model):
    user = django_user_model.objects.create_user(username="overview-api-user")
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


TODAY = date(2026, 8, 26)


def _seed_syllabus(course_id, user, *, name="Data Structures", topics=None, dates=None, grading=None, overwrite=False):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": name,
        "dates": dates or [], "grading": grading or [], "topics": topics or [],
    }, user, overwrite=overwrite)


def _seed_full_course(course_id, user):
    _seed_syllabus(
        course_id, user,
        topics=["Recursion", "Sorting"],
        dates=[
            {"date": "2026-09-05", "title": "Midterm", "type": "test_quiz"},
            {"date": "2026-08-30", "title": "Homework 1", "type": "hw"},
        ],
        grading=[{"component": "Tests", "weight_pct": 100}],
    )
    storage.write_notes(course_id, "lecture-01", {
        "lecture_id": "lecture-01", "source": "notes", "topics": ["Recursion"],
        "chunks": [{"id": "c1", "topic": "Recursion", "text": "Base case stops recursion."}],
    }, user)
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="lecture-01.txt", material_type="notes",
        source_key="lecture-01", storage_key="a" * 32 + ".txt", size_bytes=10,
        processing_status="ready", review_status="not_required",
    )
    storage.append_quiz_attempt(course_id, {"topic": "Recursion", "correct": True, "timestamp": "2026-08-20T00:00:00"}, user=user)
    storage.append_quiz_attempt(course_id, {"topic": "Sorting", "correct": False, "timestamp": "2026-08-20T00:00:00"}, user=user)
    mastery.rebuild_scores(course_id, user=user)
    storage.write_grades(course_id, {"items": [
        {"id": "g1", "component": "Tests", "title": "Quiz 1", "score": 9, "max_points": 10, "date": "2026-08-01"},
    ]}, user=user)
    StudySession.objects.create(user=user, course_id=course_id, topic="Recursion", mode="flashcards", status=StudySession.STATUS_IN_PROGRESS)
    CourseSession.objects.create(
        session_id="sess-1", course_id=course_id, user=user, title="About recursion",
        created_at="2026-08-20T00:00:00+00:00", updated_at="2026-08-20T00:00:00+00:00",
    )


def test_build_course_overview_composes_all_sections_with_real_data(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-owner")
    _seed_full_course("cs101", user)

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    assert overview["course"]["name"] == "Data Structures"
    assert overview["priority"]["available"] is True
    assert overview["priority"]["kind"] == "exam"
    assert overview["priority"]["exam"]["title"] == "Midterm"
    # 1 real "ready" notes material + 1 synthesized legacy "Existing syllabus"
    # entry (course.py's list_materials adds one for any course with a
    # confirmed syllabus.json not otherwise represented by a real row).
    assert overview["materials"]["count"] == 2
    assert overview["materials"]["needs_review"] == 0
    assert overview["materials"]["failed"] == 0
    assert len(overview["materials"]["recent"]) == 2
    assert overview["study"]["available"] is True
    assert overview["study"]["in_progress_session"]["topic"] == "Recursion"
    assert overview["mastery"]["available"] is True
    assert overview["mastery"]["strongest_topic"]["topic"] == "Recursion"
    assert overview["mastery"]["weakest_topic"]["topic"] == "Sorting"
    assert overview["grades"] == {"available": True, "error": None, "overall_pct": 90.0, "letter": "A-", "item_count": 1}
    assert overview["schedule"]["available"] is True
    assert [e["title"] for e in overview["schedule"]["events"]] == ["Homework 1", "Midterm"]
    assert overview["cora"]["available"] is True
    assert overview["cora"]["session"]["title"] == "About recursion"


def test_priority_section_falls_back_to_deadline_when_no_upcoming_exam(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-no-exam")
    _seed_syllabus("cs101", user, topics=["Recursion"], dates=[{"date": "2026-08-30", "title": "Homework 1", "type": "hw"}])

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    assert overview["priority"]["available"] is True
    assert overview["priority"]["kind"] == "deadline"
    assert overview["priority"]["deadline"]["title"] == "Homework 1"


def test_priority_section_ignores_past_exams(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-past-exam")
    _seed_syllabus("cs101", user, topics=["Recursion"], dates=[{"date": "2026-01-01", "title": "Old Midterm", "type": "test_quiz"}])

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    assert overview["priority"] == {"available": False, "error": None}


def test_sections_report_empty_not_error_on_syllabus_only_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-empty")
    _seed_syllabus("cs101", user, topics=["Recursion"])

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    # materials is the one legitimate exception: a confirmed syllabus is
    # itself always a legacy material entry, so it correctly shows as
    # available=True with count=1 even with nothing else uploaded.
    assert overview["materials"]["count"] == 1
    assert overview["materials"]["recent"][0]["material_id"] == "legacy-syllabus"
    # study is the other legitimate exception: recommendations.py offers a
    # "start studying" candidate for any syllabus topic even with zero
    # activity — a useful starter action, not fabricated ranking data.
    assert overview["study"]["available"] is True
    assert overview["study"]["recommendation"]["topic"] == "Recursion"
    assert overview["study"]["in_progress_session"] is None
    for section in ("priority", "mastery", "grades", "schedule", "cora"):
        assert overview[section]["available"] is False, section
        assert overview[section]["error"] is None, section
        assert overview[section]["error"] is None, section


def test_grades_section_is_empty_not_error_for_draft_course_while_others_still_work(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-draft")
    storage.write_course_draft("cs101", "New Course", user)

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    assert overview["grades"] == {"available": False, "error": None}
    for section in ("priority", "materials", "study", "mastery", "schedule", "cora"):
        assert overview[section]["error"] is None, section


def test_one_section_failure_does_not_affect_others(isolated_courses_dir, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="overview-partial-failure")
    _seed_full_course("cs101", user)

    def boom(*args, **kwargs):
        raise storage.CustomEventsStorageError("corrupt custom_events.json")

    monkeypatch.setattr(course_overview.calendar_events, "upcoming_events", boom)

    overview = course_overview.build_course_overview("cs101", user, today=TODAY)

    assert overview["schedule"]["available"] is False
    assert overview["schedule"]["error"] == "corrupt custom_events.json"
    assert overview["materials"]["available"] is True
    assert overview["grades"]["available"] is True
    assert overview["mastery"]["available"] is True
    assert overview["cora"]["available"] is True


def test_course_not_found_propagates_uncaught(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="overview-missing-course")

    with pytest.raises(storage.CourseNotFoundError):
        course_overview.build_course_overview("nocourse", user, today=TODAY)


def test_two_user_isolation_across_all_sections(isolated_courses_dir, django_user_model):
    owner = django_user_model.objects.create_user(username="overview-owner-2")
    other = django_user_model.objects.create_user(username="overview-other")
    _seed_full_course("cs101", owner)
    _seed_syllabus("cs101", other, name="Other Course", topics=["Other Topic"])

    overview = course_overview.build_course_overview("cs101", other, today=TODAY)

    assert overview["course"]["name"] == "Other Course"
    # Just `other`'s own synthesized legacy-syllabus entry — none of
    # owner's real "lecture-01.txt" notes material leaks across users.
    assert overview["materials"]["count"] == 1
    assert overview["cora"]["available"] is False
    assert overview["study"]["in_progress_session"] is None
    assert overview["grades"]["item_count"] == 0


# --- API-level ---

def test_overview_endpoint_returns_full_payload_for_owned_course(isolated_courses_dir, api_client):
    _seed_full_course("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/overview/")

    assert response.status_code == 200
    assert response.data["course"]["name"] == "Data Structures"
    assert response.data["priority"]["kind"] == "exam"
    assert set(response.data.keys()) == {"course", "priority", "materials", "study", "mastery", "grades", "schedule", "cora"}


def test_overview_endpoint_404_for_foreign_course(isolated_courses_dir, api_client, django_user_model):
    other = django_user_model.objects.create_user(username="overview-endpoint-other")
    _seed_full_course("cs101", other)

    response = api_client.get("/api/courses/cs101/overview/")

    assert response.status_code == 404
    assert "Data Structures" not in str(response.data)


def test_overview_endpoint_400_for_invalid_course_id(isolated_courses_dir, api_client):
    too_long = "a" * 65  # matches the URL slug converter but exceeds COURSE_ID_RE's 64-char cap

    response = api_client.get(f"/api/courses/{too_long}/overview/")

    assert response.status_code == 400
