from datetime import date, timedelta

import pytest

from agent.models import CourseMaterial
from agent.services import course_catalog, storage


pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _course(user, course_id, name, *, semester="fall-2026", dates=None):
    storage.write_course_draft(
        course_id, name, user, course_code=course_id.upper(), instructor="Dr. Owner",
        semester=semester, color="#527d47", archived=False,
    )
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": name, "dates": dates or [], "grading": [], "topics": [],
    }, user, overwrite=True)


def test_catalog_composes_confirmed_deadline_ready_materials_and_evidence_mastery(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="catalog-owner")
    due = (date(2026, 8, 26) + timedelta(days=3)).isoformat()
    _course(user, "cs101", "Computer Science", dates=[{"date": due, "title": "Project", "type": "assignment"}])
    CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename="notes.pdf", material_type="notes",
        processing_status="ready", review_status="not_required", storage_key="ready-notes",
        size_bytes=10, content_type="application/pdf",
    )
    CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename="old.pdf", material_type="notes",
        processing_status="ready", review_status="superseded", storage_key="old-notes",
        size_bytes=10, content_type="application/pdf",
    )
    storage.write_mastery_scores("cs101", {"course_id": "cs101", "scores": [
        {"topic": "Lists", "score": .8, "attempts": 3, "last_seen": None, "status": "proficient", "reason": "Evidence"},
        {"topic": "Trees", "score": .6, "attempts": 2, "last_seen": None, "status": "needs_review", "reason": "Evidence"},
    ], "updated_at": "2026-08-26T12:00:00+00:00"}, user=user)

    snapshot = course_catalog.build_courses_page(user, semester="fall-2026", today=date(2026, 8, 26))

    assert snapshot["summary"] == {"active_courses": 1, "upcoming_deadlines": 1, "average_mastery": 70}
    assert snapshot["courses"][0]["next_deadline"]["title"] == "Project"
    assert snapshot["courses"][0]["materials"]["count"] == 2  # confirmed syllabus + ready notes
    assert snapshot["courses"][0]["mastery"]["label"] == "70%"


def test_build_course_header_composes_identity_deadline_and_mastery(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="header-owner")
    due = (date(2026, 8, 26) + timedelta(days=3)).isoformat()
    _course(user, "cs101", "Computer Science", dates=[{"date": due, "title": "Project", "type": "assignment"}])
    storage.write_mastery_scores("cs101", {"course_id": "cs101", "scores": [
        {"topic": "Lists", "score": .8, "attempts": 3, "last_seen": None, "status": "proficient", "reason": "Evidence"},
    ], "updated_at": "2026-08-26T12:00:00+00:00"}, user=user)

    header = course_catalog.build_course_header("cs101", user, today=date(2026, 8, 26))

    assert header["course"]["name"] == "Computer Science"
    assert header["course"]["code"] == "CS101"
    assert header["course"]["instructor"] == "Dr. Owner"
    assert header["next_deadline"]["title"] == "Project"
    assert header["next_deadline"]["relative_label"] == "3 days"
    assert header["mastery"]["label"] == "80%"


def test_build_course_header_reports_not_enough_data_when_no_mastery_evidence(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="header-no-mastery")
    _course(user, "cs101", "Computer Science")

    header = course_catalog.build_course_header("cs101", user, today=date(2026, 8, 26))

    assert header["next_deadline"] is None
    assert header["mastery"] == {"available": False, "score": None, "status": "not_started", "label": "Not enough data"}


def test_build_course_header_is_owner_scoped(isolated_courses_dir, django_user_model):
    owner = django_user_model.objects.create_user(username="header-owner-2")
    other = django_user_model.objects.create_user(username="header-other")
    _course(owner, "cs101", "Computer Science")

    with pytest.raises(storage.CourseNotFoundError):
        course_catalog.build_course_header("cs101", other, today=date(2026, 8, 26))


def test_catalog_is_two_user_scoped_for_same_course_slug(isolated_courses_dir, django_user_model):
    owner = django_user_model.objects.create_user(username="catalog-a")
    other = django_user_model.objects.create_user(username="catalog-b")
    _course(owner, "shared", "Owner course")
    _course(other, "shared", "Other course")

    owner_snapshot = course_catalog.build_courses_page(owner, semester="fall-2026", today=date(2026, 8, 26))
    other_snapshot = course_catalog.build_courses_page(other, semester="fall-2026", today=date(2026, 8, 26))

    assert [row["name"] for row in owner_snapshot["courses"]] == ["Owner course"]
    assert [row["name"] for row in other_snapshot["courses"]] == ["Other course"]


def test_archive_preserves_data_and_removes_course_from_active_composition(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="archive-owner")
    _course(user, "cs101", "Computer Science")
    syllabus_path = isolated_courses_dir / str(user.pk) / "cs101" / "syllabus.json"

    course_catalog.set_archived(user, "cs101", True)
    active = course_catalog.build_courses_page(user, semester="fall-2026", today=date(2026, 8, 26))
    archived = course_catalog.build_courses_page(user, semester="fall-2026", archived=True, today=date(2026, 8, 26))

    assert syllabus_path.exists()
    assert active["courses"] == []
    assert [row["id"] for row in archived["courses"]] == ["cs101"]
    course_catalog.set_archived(user, "cs101", False)
    assert course_catalog.build_courses_page(user, semester="fall-2026", today=date(2026, 8, 26))["summary"]["active_courses"] == 1


def test_corrupt_course_is_isolated_as_warning(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="corrupt-catalog")
    _course(user, "good", "Good course")
    bad_dir = isolated_courses_dir / str(user.pk) / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "course.json").write_text("{broken", encoding="utf-8")

    snapshot = course_catalog.build_courses_page(user, semester="fall-2026", today=date(2026, 8, 26))

    assert [row["id"] for row in snapshot["courses"]] == ["good"]
    assert snapshot["warnings"][0]["course_id"] == "bad"
