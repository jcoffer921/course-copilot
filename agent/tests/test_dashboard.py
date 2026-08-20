import pytest

from agent.services import dashboard, mastery, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_course(course_id, topics, grading, dates, notes_count=0):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": course_id.upper(),
        "dates": dates,
        "grading": grading,
        "topics": topics,
    })
    for i in range(notes_count):
        lecture_id = f"lecture{i + 1:02d}"
        storage.write_notes(course_id, lecture_id, {
            "lecture_id": lecture_id,
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
        notes_count=1,
    )
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    mastery.rebuild_scores("cs101")

    data = dashboard.build_dashboard()

    course = data["courses"]["cs101"]
    assert course["course_name"] == "CS101"
    assert course["notes_count"] == 1
    assert course["topics_count"] == 3
    assert course["quizzed_count"] == 1
    assert course["grading"] == [{"component": "HW", "weight_pct": 100}]
    assert [t["topic"] for t in course["weak_topics"]] == ["A"]
    assert course["topics"] == [
        {"topic": "A", "score": pytest.approx(0.65), "status": "developing"},
        {"topic": "B", "score": None, "status": "unassessed"},
        {"topic": "C", "score": None, "status": "unassessed"},
    ]


def test_build_dashboard_topics_all_unassessed_without_quiz_history(isolated_courses_dir):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["courses"]["psyc201"]["topics"] == [
        {"topic": "X", "score": None, "status": "unassessed"},
        {"topic": "Y", "score": None, "status": "unassessed"},
    ]


def test_build_dashboard_topics_includes_off_syllabus_topic_without_inflating_quizzed_count(isolated_courses_dir):
    # chunk_notes.py's chunking prompt explicitly allows a chunk to be
    # tagged with its own topic name when it doesn't cleanly match a
    # syllabus topic — that topic still gets quizzed and scored, so it
    # must still show up in "topics" rather than silently vanishing, and
    # it must not be counted toward "quizzed_count" (which drives the
    # "X of Y topics quizzed" / syllabus-covered percentage and must never
    # exceed topics_count, since only Y=topics_count syllabus topics exist).
    _seed_course("cs101", topics=["A", "B"], grading=[], dates=[])
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "Off-syllabus topic", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    mastery.rebuild_scores("cs101")

    data = dashboard.build_dashboard()
    course = data["courses"]["cs101"]

    assert [t["topic"] for t in course["topics"]] == ["A", "B", "Off-syllabus topic"]
    assert course["topics_count"] == 2
    assert course["quizzed_count"] == 1


def test_build_dashboard_includes_streak(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["streak"] == 0


def test_build_dashboard_course_without_notes_or_mastery(isolated_courses_dir):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    course = data["courses"]["psyc201"]
    assert course["notes_count"] == 0
    assert course["quizzed_count"] == 0
    assert course["weak_topics"] == []
    assert course["next_deadline"] is None


def test_build_dashboard_next_deadline_uncapped_but_top_level_deadlines_windowed(isolated_courses_dir):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=20)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[{"date": far_date, "title": "Midterm", "type": "exam"}],
    )

    data = dashboard.build_dashboard()

    assert data["courses"]["cs101"]["next_deadline"] == {
        "course_id": "cs101", "date": far_date, "title": "Midterm", "type": "exam",
    }
    assert data["deadlines"] == []


def test_build_dashboard_isolates_corrupt_course(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    bad_dir = isolated_courses_dir / "badcourse"
    bad_dir.mkdir()
    (bad_dir / "syllabus.json").write_text("{not valid json", encoding="utf-8")

    data = dashboard.build_dashboard()

    assert "error" in data["courses"]["badcourse"]
    assert data["courses"]["cs101"]["topics_count"] == 1


def test_build_dashboard_notes_count_reflects_multiple_lectures(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], notes_count=2)

    data = dashboard.build_dashboard()

    assert data["courses"]["cs101"]["notes_count"] == 2


def test_build_dashboard_includes_drafts(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["drafts"] == [{
        "course_id": "newclass", "course_name": "New Class",
        "created_at": data["drafts"][0]["created_at"],
    }]
    assert "newclass" not in data["courses"]
    assert "cs101" in data["courses"]


def test_build_dashboard_drafts_empty_when_none_exist(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["drafts"] == []


def test_build_dashboard_marks_synced_deadlines(isolated_courses_dir):
    from datetime import date, timedelta

    midterm_date = (date.today() + timedelta(days=5)).isoformat()
    final_date = (date.today() + timedelta(days=10)).isoformat()

    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[
            {"date": midterm_date, "title": "Midterm", "type": "exam"},
            {"date": final_date, "title": "Final", "type": "exam"},
        ],
    )
    storage.append_calendar_sync_record("cs101", {
        "date": midterm_date, "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    })

    data = dashboard.build_dashboard()

    by_title = {d["title"]: d for d in data["deadlines"]}
    assert by_title["Midterm"]["synced"] is True
    assert by_title["Final"]["synced"] is False


def test_build_dashboard_deadlines_unsynced_when_no_calendar_sync_file(isolated_courses_dir):
    from datetime import date, timedelta

    midterm_date = (date.today() + timedelta(days=5)).isoformat()

    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": midterm_date, "title": "Midterm", "type": "exam"}],
    )

    data = dashboard.build_dashboard()

    assert data["deadlines"][0]["synced"] is False
