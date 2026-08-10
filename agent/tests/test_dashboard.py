import pytest

from agent.services import dashboard, mastery, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_course(course_id, topics, grading, dates, has_notes=False):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": course_id.upper(),
        "dates": dates,
        "grading": grading,
        "topics": topics,
    })
    if has_notes:
        storage.write_notes(course_id, "lecture01", {
            "lecture_id": "lecture01",
            "source": "notes",
            "date": "2026-01-01",
            "topics": topics[:1],
            "chunks": [{"id": "c1", "topic": topics[0], "text": "..."}],
        })


def test_build_dashboard_composes_course_data(isolated_courses_dir):
    _seed_course(
        "cs101", topics=["A", "B", "C"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": "2026-08-10", "title": "Quiz 1", "type": "assignment"}],
        has_notes=True,
    )
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    mastery.rebuild_scores("cs101")

    data = dashboard.build_dashboard()

    course = data["courses"]["cs101"]
    assert course["course_name"] == "CS101"
    assert course["has_notes"] is True
    assert course["topics_count"] == 3
    assert course["quizzed_count"] == 1
    assert course["grading"] == [{"component": "HW", "weight_pct": 100}]
    assert [t["topic"] for t in course["weak_topics"]] == ["A"]


def test_build_dashboard_course_without_notes_or_mastery(isolated_courses_dir):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[], has_notes=False)

    data = dashboard.build_dashboard()

    course = data["courses"]["psyc201"]
    assert course["has_notes"] is False
    assert course["quizzed_count"] == 0
    assert course["weak_topics"] == []
    assert course["next_deadline"] is None


def test_build_dashboard_next_deadline_uncapped_but_top_level_deadlines_windowed(isolated_courses_dir):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=20)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[{"date": far_date, "title": "Midterm", "type": "exam"}], has_notes=False,
    )

    data = dashboard.build_dashboard()

    assert data["courses"]["cs101"]["next_deadline"] == {
        "course_id": "cs101", "date": far_date, "title": "Midterm", "type": "exam",
    }
    assert data["deadlines"] == []


def test_build_dashboard_isolates_corrupt_course(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], has_notes=False)

    bad_dir = isolated_courses_dir / "badcourse"
    bad_dir.mkdir()
    (bad_dir / "syllabus.json").write_text("{not valid json", encoding="utf-8")

    data = dashboard.build_dashboard()

    assert "error" in data["courses"]["badcourse"]
    assert data["courses"]["cs101"]["topics_count"] == 1
