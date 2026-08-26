import pytest

from agent.services import dashboard, mastery, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="owner", email="owner@example.com")


def _seed_course(course_id, topics, grading, dates, user, notes_count=0):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": course_id.upper(),
        "dates": dates,
        "grading": grading,
        "topics": topics,
    }, user)
    for i in range(notes_count):
        lecture_id = f"lecture{i + 1:02d}"
        storage.write_notes(course_id, lecture_id, {
            "lecture_id": lecture_id,
            "source": "notes",
            "date": "2026-01-01",
            "topics": topics[:1],
            "chunks": [{"id": "c1", "topic": topics[0], "text": "..."}],
        }, user)


def test_build_dashboard_composes_course_data(isolated_courses_dir, user):
    _seed_course(
        "cs101", topics=["A", "B", "C"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": "2026-08-10", "title": "Quiz 1", "type": "assignment"}],
        user=user,
        notes_count=1,
    )
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    mastery.rebuild_scores("cs101", user=user)

    data = dashboard.build_dashboard(user=user)

    course = data["courses"]["cs101"]
    assert course["course_name"] == "CS101"
    assert course["notes_count"] == 1
    assert course["topics_count"] == 3
    assert course["quizzed_count"] == 1
    assert course["quiz_attempts_count"] == 1
    assert course["quiz_correct_count"] == 1
    assert course["grading"] == [{"component": "HW", "weight_pct": 100}]
    assert [t["topic"] for t in course["weak_topics"]] == ["A"]
    assert course["topics"] == [
        {
            "topic": "A", "score": pytest.approx(0.65), "status": "needs_review",
            "reason": "65% mastery over 1 attempt(s) — needs more practice.",
        },
        {"topic": "B", "score": None, "status": "not_started", "reason": "Not started yet."},
        {"topic": "C", "score": None, "status": "not_started", "reason": "Not started yet."},
    ]


def test_build_dashboard_topics_all_not_started_without_quiz_history(isolated_courses_dir, user):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["psyc201"]["topics"] == [
        {"topic": "X", "score": None, "status": "not_started", "reason": "Not started yet."},
        {"topic": "Y", "score": None, "status": "not_started", "reason": "Not started yet."},
    ]


def test_build_dashboard_topics_includes_off_syllabus_topic_without_inflating_quizzed_count(isolated_courses_dir, user):
    # chunk_notes.py's chunking prompt explicitly allows a chunk to be
    # tagged with its own topic name when it doesn't cleanly match a
    # syllabus topic — that topic still gets quizzed and scored, so it
    # must still show up in "topics" rather than silently vanishing, and
    # it must not be counted toward "quizzed_count" (which drives the
    # "X of Y topics quizzed" / syllabus-covered percentage and must never
    # exceed topics_count, since only Y=topics_count syllabus topics exist).
    _seed_course("cs101", topics=["A", "B"], grading=[], dates=[], user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "Off-syllabus topic", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    mastery.rebuild_scores("cs101", user=user)

    data = dashboard.build_dashboard(user=user)
    course = data["courses"]["cs101"]

    assert [t["topic"] for t in course["topics"]] == ["A", "B", "Off-syllabus topic"]
    assert course["topics_count"] == 2
    assert course["quizzed_count"] == 1


def test_build_dashboard_includes_streak(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["streak"] == 0


def test_build_dashboard_course_without_notes_or_mastery(isolated_courses_dir, user):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    course = data["courses"]["psyc201"]
    assert course["notes_count"] == 0
    assert course["quizzed_count"] == 0
    assert course["quiz_attempts_count"] == 0
    assert course["quiz_correct_count"] == 0
    assert course["weak_topics"] == []
    assert course["mastery_pct"] is None
    assert course["next_deadline"] is None


def test_build_dashboard_quiz_accuracy_counts_all_attempts(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": False, "timestamp": "2026-01-02T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-03T00:00:00"}, user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["quiz_attempts_count"] == 3
    assert data["courses"]["cs101"]["quiz_correct_count"] == 2


def test_build_dashboard_next_deadline_uncapped_but_top_level_deadlines_windowed(isolated_courses_dir, user):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=20)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[{"date": far_date, "title": "Midterm", "type": "exam"}],
        user=user,
    )

    data = dashboard.build_dashboard(user=user)

    next_deadline = data["courses"]["cs101"]["next_deadline"]
    assert {
        key: next_deadline[key]
        for key in ("course_id", "date", "title", "type", "key")
    } == {
        # reminders.upcoming_deadlines() normalizes syllabus date types through
        # storage.normalize_date_type() — "exam" is a legacy alias for "test_quiz" —
        # and tags each deadline with its replaces_syllabus_key-matching "key".
        "course_id": "cs101", "date": far_date, "title": "Midterm", "type": "test_quiz",
        "key": f"cs101|{far_date}|Midterm|test_quiz",
    }
    assert next_deadline["source"] == "syllabus"
    assert next_deadline["all_day"] is True
    assert data["deadlines"] == []
    # Top-level next_deadline/next_exam are derived from the windowed
    # `deadlines` list (14 days), not the uncapped per-course one above.
    assert data["next_deadline"] is None
    assert data["next_exam"] is None


def test_build_dashboard_top_level_next_deadline_and_next_exam(isolated_courses_dir, user):
    from datetime import date, timedelta

    hw_date = (date.today() + timedelta(days=2)).isoformat()
    exam_date = (date.today() + timedelta(days=5)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[
            {"date": exam_date, "title": "Midterm", "type": "test_quiz"},
            {"date": hw_date, "title": "Homework 1", "type": "hw"},
        ],
        user=user,
    )

    data = dashboard.build_dashboard(user=user)

    assert data["next_deadline"]["title"] == "Homework 1"  # soonest overall
    assert data["next_exam"]["title"] == "Midterm"  # soonest test_quiz specifically


def test_build_dashboard_streak_week_is_present(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert [day["label"] for day in data["streak_week"]] == ["M", "T", "W", "T", "F", "S", "S"]


def test_build_dashboard_today_plan_prefers_deadlines_with_effort_estimates(isolated_courses_dir, user):
    from datetime import date, timedelta

    from agent.services import custom_events

    due = (date.today() + timedelta(days=1)).isoformat()
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)
    custom_events.create_event(
        "cs101", due, None, "Build a To-Do List App", "project", user=user, estimated_effort_minutes=90,
    )

    data = dashboard.build_dashboard(user=user)

    assert len(data["today_plan"]) == 1
    task = data["today_plan"][0]
    assert task["kind"] == "deadline"
    assert task["title"] == "Build a To-Do List App"
    assert task["effort_minutes"] == 90
    assert task["course_id"] == "cs101"


def test_build_dashboard_today_plan_never_fabricates_an_effort_estimate(isolated_courses_dir, user):
    from datetime import date, timedelta

    due = (date.today() + timedelta(days=1)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[{"date": due, "title": "Reading", "type": "class"}],  # no estimated_effort_minutes on a syllabus date
        user=user,
    )

    data = dashboard.build_dashboard(user=user)

    assert all(task["title"] != "Reading" for task in data["today_plan"])


def test_build_dashboard_today_plan_fills_remaining_slots_with_recommendations(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert len(data["today_plan"]) == 1
    task = data["today_plan"][0]
    assert task["kind"] == "recommendation"
    assert task["course_id"] == "cs101"
    assert task["title"] == "Review Recursion"
    assert task["effort_minutes"] == dashboard.RECOMMENDATION_TASK_EFFORT_MINUTES


def test_course_mastery_pct_averages_syllabus_topics_including_unstarted_as_zero(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A", "B"], grading=[], dates=[], user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-02T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-03T00:00:00"}, user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-04T00:00:00"}, user=user)
    # A's score after 4 correct answers is high (~0.92); B has never been
    # touched, so it must drag the course average down rather than being
    # skipped — (0.92 + 0)/2 ≈ 46%, not A's own ~92%.
    mastery.rebuild_scores("cs101", user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["mastery_pct"] == pytest.approx(46, abs=2)


def test_course_mastery_pct_is_none_without_syllabus_topics(isolated_courses_dir, user):
    _seed_course("cs101", topics=[], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["mastery_pct"] is None


def test_build_dashboard_today_plan_skips_completed_deadlines(isolated_courses_dir, user):
    from datetime import date, timedelta

    from agent.services import custom_events

    due = (date.today() + timedelta(days=1)).isoformat()
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)
    event = custom_events.create_event(
        "cs101", due, None, "Finished already", "hw", user=user, estimated_effort_minutes=30,
    )
    custom_events.update_event(event["id"], user=user, completed=True)

    data = dashboard.build_dashboard(user=user)

    assert all(task["title"] != "Finished already" for task in data["today_plan"])


def test_build_dashboard_isolates_corrupt_course(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)

    bad_dir = isolated_courses_dir / str(user.pk) / "badcourse"
    bad_dir.mkdir()
    (bad_dir / "syllabus.json").write_text("{not valid json", encoding="utf-8")

    data = dashboard.build_dashboard(user=user)

    assert "error" in data["courses"]["badcourse"]
    assert data["courses"]["cs101"]["topics_count"] == 1


def test_build_dashboard_notes_count_reflects_multiple_lectures(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user, notes_count=2)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["notes_count"] == 2


def test_build_dashboard_includes_drafts(isolated_courses_dir, user):
    storage.write_course_draft("newclass", "New Class", user)
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["drafts"] == [{
        "course_id": "newclass", "course_name": "New Class",
        "created_at": data["drafts"][0]["created_at"],
    }]
    assert "newclass" not in data["courses"]
    assert "cs101" in data["courses"]


def test_build_dashboard_drafts_empty_when_none_exist(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], user=user)

    data = dashboard.build_dashboard(user=user)

    assert data["drafts"] == []


def test_build_dashboard_isolates_two_users_with_same_course_slug(isolated_courses_dir, django_user_model):
    alice = django_user_model.objects.create_user(username="alice")
    bob = django_user_model.objects.create_user(username="bob")
    _seed_course("cs101", topics=["Alice topic"], grading=[], dates=[], user=alice)
    _seed_course("cs101", topics=["Bob topic"], grading=[], dates=[], user=bob)
    storage.append_quiz_attempt(
        "cs101", {"topic": "Alice topic", "correct": True, "timestamp": "2026-01-01T00:00:00Z"}, user=alice,
    )
    mastery.rebuild_scores("cs101", user=alice)

    alice_data = dashboard.build_dashboard(user=alice)
    bob_data = dashboard.build_dashboard(user=bob)

    assert [topic["topic"] for topic in alice_data["courses"]["cs101"]["topics"]] == ["Alice topic"]
    assert [topic["topic"] for topic in bob_data["courses"]["cs101"]["topics"]] == ["Bob topic"]
    assert alice_data["courses"]["cs101"]["quiz_attempts_count"] == 1
    assert bob_data["courses"]["cs101"]["quiz_attempts_count"] == 0
    assert bob_data["courses"]["cs101"]["mastery_pct"] is None


def test_dashboard_uses_server_course_color_and_display_name_for_deadlines(isolated_courses_dir, user):
    from datetime import date, timedelta

    due = (date.today() + timedelta(days=2)).isoformat()
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Computer Science", "topics": ["A"], "grading": [],
        "dates": [{"date": due, "title": "Project", "type": "project"}],
    }, user)

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["course_color"] == data["next_deadline"]["course_color"]
    assert data["next_deadline"]["course_name"] == "Computer Science"


def test_build_dashboard_marks_synced_deadlines(isolated_courses_dir, user):
    from datetime import date, timedelta

    # Dates must be within build_dashboard()'s 14-day upcoming_deadlines()
    # window to appear in data["deadlines"] at all — a fixed far-future date
    # (e.g. year 2099) would fall outside that window and never show up,
    # making the assertions below fail with a KeyError instead of testing
    # anything.
    midterm_date = (date.today() + timedelta(days=5)).isoformat()
    final_date = (date.today() + timedelta(days=10)).isoformat()

    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[
            {"date": midterm_date, "title": "Midterm", "type": "exam"},
            {"date": final_date, "title": "Final", "type": "exam"},
        ],
        user=user,
    )
    storage.append_calendar_sync_record("cs101", {
        "date": midterm_date, "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    }, user=user)

    data = dashboard.build_dashboard(user=user)

    by_title = {d["title"]: d for d in data["deadlines"]}
    assert by_title["Midterm"]["synced"] is True
    assert by_title["Final"]["synced"] is False


def test_build_dashboard_deadlines_unsynced_when_no_calendar_sync_file(isolated_courses_dir, user):
    from datetime import date, timedelta

    midterm_date = (date.today() + timedelta(days=5)).isoformat()

    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": midterm_date, "title": "Midterm", "type": "exam"}],
        user=user,
    )

    data = dashboard.build_dashboard(user=user)

    assert data["deadlines"][0]["synced"] is False


def test_build_dashboard_never_raises_on_corrupt_calendar_sync_file(isolated_courses_dir, user):
    # _annotate_synced() is called outside build_dashboard()'s per-course
    # try/except, at the return statement — a corrupt calendar_sync.json
    # must not be allowed to 500 the whole dashboard for every course.
    from datetime import date, timedelta

    midterm_date = (date.today() + timedelta(days=5)).isoformat()

    _seed_course(
        "cs101", topics=["A"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": midterm_date, "title": "Midterm", "type": "exam"}],
        user=user,
    )
    course_dir = isolated_courses_dir / str(user.pk) / "cs101"
    (course_dir / "calendar_sync.json").write_text("{not valid json", encoding="utf-8")

    data = dashboard.build_dashboard(user=user)

    assert data["courses"]["cs101"]["topics_count"] == 1
    assert data["deadlines"][0]["synced"] is False
