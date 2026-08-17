from datetime import datetime, timedelta, timezone

import pytest

from agent.services import storage, streak


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_syllabus(course_id):
    """current_streak() only scans courses reminders.list_courses() finds,
    which requires a syllabus.json to exist — a course with quiz attempts
    but no syllabus can't happen in practice (quizzing requires chunked
    notes, which requires a syllabus first), but streak.py still needs a
    real syllabus.json on disk for the course to be discovered at all."""
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": [], "grading": [], "topics": [],
    })


def _attempt_at(d, topic="X", correct=True):
    return {"topic": topic, "correct": correct, "timestamp": d.isoformat() + "T12:00:00+00:00"}


def test_streak_zero_with_no_attempts_anywhere(isolated_courses_dir):
    _seed_syllabus("cs101")

    assert streak.current_streak() == 0


def test_streak_counts_consecutive_days_across_courses(isolated_courses_dir):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101")
    _seed_syllabus("psyc201")
    storage.append_quiz_attempt("cs101", _attempt_at(today))
    storage.append_quiz_attempt("psyc201", _attempt_at(today - timedelta(days=1)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))

    assert streak.current_streak() == 3


def test_streak_alive_with_activity_yesterday_but_not_today(isolated_courses_dir):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101")
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=1)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))

    assert streak.current_streak() == 2


def test_streak_breaks_after_full_day_gap(isolated_courses_dir):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101")
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=3)))

    assert streak.current_streak() == 0


def test_streak_ignores_a_course_with_corrupt_quiz_history(isolated_courses_dir, tmp_path):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101")
    _seed_syllabus("badcourse")
    storage.append_quiz_attempt("cs101", _attempt_at(today))
    (tmp_path / "badcourse" / "quiz_history.json").write_text("{not valid json", encoding="utf-8")

    assert streak.current_streak() == 1
