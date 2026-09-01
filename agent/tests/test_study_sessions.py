from datetime import datetime, timezone

import pytest

from agent.services import storage, study_sessions

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner(django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="study-session-owner")
    for course_id in ("cs101", "cs202"):
        storage.write_syllabus(course_id, {"course_id": course_id, "course_name": course_id, "dates": [], "grading": [], "topics": ["Recursion", "Sorting"]}, user)
    return user


def test_start_session_records_a_session_started_activity(isolated_courses_dir, owner):
    session = study_sessions.start_session(owner, "cs101", topic="Recursion", duration_minutes=15, mode="mixed")

    assert session["course_id"] == "cs101"
    assert session["topic"] == "Recursion"
    assert session["status"] == "in_progress"

    detail = study_sessions.session_detail(owner, session["session_id"])
    assert len(detail["activities"]) == 1
    assert detail["activities"][0]["kind"] == "session_started"
    assert detail["activities"][0]["position"] == 0


def test_grounded_plan_selects_a_recommended_topic_that_has_notes_and_references(isolated_courses_dir, owner):
    storage.write_notes("cs101", "lecture-2", {
        "lecture_id": "lecture-2",
        "topics": ["Sorting"],
        "chunks": [{"id": "sorting-basics", "topic": "Sorting", "text": "Comparison sorting."}],
    }, owner)
    storage.write_reference("cs101", "sorting-chapter", {
        "reference_id": "sorting-chapter",
        "title": "Sorting chapter",
        "source_filename": "chapter.pdf",
        "text": "Sorting algorithms include merge sort and quicksort.",
    }, owner)

    plan = study_sessions.build_grounded_plan(owner, "cs101", duration_minutes=20, mode="mixed")

    assert plan["topic"] == "Sorting"
    assert plan["grounded"] is True
    assert plan["source_counts"] == {"notes": 1, "references": 1}
    assert {source["kind"] for source in plan["sources"]} == {"note", "reference"}
    assert [step["kind"] for step in plan["steps"]] == ["flashcards", "quiz", "summary"]
    assert plan["steps"][0]["count"] == "10 cards"
    assert plan["steps"][1]["count"] == "5 questions"


def test_grounded_plan_falls_back_to_course_outline_when_topic_has_no_matching_sources(isolated_courses_dir, owner):
    plan = study_sessions.build_grounded_plan(
        owner, "cs101", topic="Recursion", duration_minutes=15, mode="quiz",
    )

    assert plan["topic"] == "Recursion"
    assert plan["grounded"] is False
    assert plan["sources"] == []
    assert [step["kind"] for step in plan["steps"]] == ["quiz", "summary"]
    assert "Add or process notes" in plan["rationale"]


def test_start_session_rejects_invalid_mode(isolated_courses_dir, owner):
    with pytest.raises(ValueError):
        study_sessions.start_session(owner, "cs101", mode="not-a-mode")


def test_start_session_rejects_unconfirmed_or_foreign_topic(isolated_courses_dir, owner):
    with pytest.raises(ValueError, match="confirmed course syllabus"):
        study_sessions.start_session(owner, "cs101", topic="Private foreign topic")


def test_start_session_is_idempotent_for_matching_active_session(isolated_courses_dir, owner):
    first = study_sessions.start_session(owner, "cs101", topic="Recursion", duration_minutes=45, mode="mixed")
    repeated = study_sessions.start_session(owner, "cs101", topic="Recursion", duration_minutes=45, mode="mixed")
    assert repeated["session_id"] == first["session_id"]


def test_record_activity_appends_in_order(isolated_courses_dir, owner):
    session = study_sessions.start_session(owner, "cs101")

    first = study_sessions.record_activity(owner, session["session_id"], "flashcard_reviewed", {"key": "a"})
    second = study_sessions.record_activity(owner, session["session_id"], "quiz_answered", {"correct": True})

    assert first["position"] == 1
    assert second["position"] == 2
    detail = study_sessions.session_detail(owner, session["session_id"])
    assert [a["kind"] for a in detail["activities"]] == ["session_started", "flashcard_reviewed", "quiz_answered"]


def test_record_activity_rejects_invalid_kind(isolated_courses_dir, owner):
    session = study_sessions.start_session(owner, "cs101")

    with pytest.raises(ValueError):
        study_sessions.record_activity(owner, session["session_id"], "not_a_kind", {})


def test_record_activity_rejects_once_session_is_completed(isolated_courses_dir, owner):
    session = study_sessions.start_session(owner, "cs101")
    study_sessions.complete_session(owner, session["session_id"])

    with pytest.raises(study_sessions.InvalidStudySessionStateError):
        study_sessions.record_activity(owner, session["session_id"], "flashcard_reviewed", {})


def test_complete_session_summarizes_activity_and_is_deterministic_under_fixed_clock(isolated_courses_dir, owner):
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session = study_sessions.start_session(owner, "cs101")
    study_sessions.record_activity(owner, session["session_id"], "flashcard_reviewed", {"key": "a"})
    study_sessions.record_activity(owner, session["session_id"], "flashcard_reviewed", {"key": "b"})
    study_sessions.record_activity(owner, session["session_id"], "quiz_answered", {"correct": True})
    study_sessions.record_activity(owner, session["session_id"], "quiz_answered", {"correct": False})

    result = study_sessions.complete_session(owner, session["session_id"], now=fixed_now)

    assert result["status"] == "completed"
    assert result["completed_at"] == fixed_now.isoformat()
    assert result["summary"] == {
        "flashcards_reviewed": 2,
        "questions_answered": 2,
        "questions_correct": 1,
    }


def test_complete_session_twice_raises(isolated_courses_dir, owner):
    session = study_sessions.start_session(owner, "cs101")
    study_sessions.complete_session(owner, session["session_id"])

    with pytest.raises(study_sessions.InvalidStudySessionStateError):
        study_sessions.complete_session(owner, session["session_id"])


def test_sessions_are_owner_scoped(isolated_courses_dir, owner, django_user_model):
    other = django_user_model.objects.create_user(username="study-session-other")
    session = study_sessions.start_session(owner, "cs101")

    with pytest.raises(study_sessions.StudySessionNotFoundError):
        study_sessions.session_detail(other, session["session_id"])
    with pytest.raises(study_sessions.StudySessionNotFoundError):
        study_sessions.record_activity(other, session["session_id"], "flashcard_reviewed", {})
    with pytest.raises(study_sessions.StudySessionNotFoundError):
        study_sessions.complete_session(other, session["session_id"])
    assert study_sessions.list_sessions(other, course_id="cs101") == []


def test_list_sessions_is_newest_first_and_filters_by_course(isolated_courses_dir, owner):
    first = study_sessions.start_session(owner, "cs101", topic="Recursion")
    study_sessions.start_session(owner, "cs202")
    third = study_sessions.start_session(owner, "cs101", topic="Sorting")

    sessions = study_sessions.list_sessions(owner, course_id="cs101")

    assert [s["session_id"] for s in sessions] == [third["session_id"], first["session_id"]]
    assert all(s["course_id"] == "cs101" for s in sessions)


def test_unknown_session_id_raises_not_found(isolated_courses_dir, owner):
    with pytest.raises(study_sessions.StudySessionNotFoundError):
        study_sessions.session_detail(owner, "00000000-0000-0000-0000-000000000000")
