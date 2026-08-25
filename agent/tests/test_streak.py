from datetime import datetime, timedelta, timezone

import pytest

from agent.services import storage, streak

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


def _seed_syllabus(course_id, user):
    """current_streak() only scans courses reminders.list_courses() finds,
    which requires a syllabus.json to exist — a course with quiz attempts
    but no syllabus can't happen in practice (quizzing requires chunked
    notes, which requires a syllabus first), but streak.py still needs a
    real syllabus.json on disk for the course to be discovered at all."""
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": [], "grading": [], "topics": [],
    }, user)


def _attempt_at(d, topic="X", correct=True):
    return {"topic": topic, "correct": correct, "timestamp": d.isoformat() + "T12:00:00+00:00"}


def test_streak_zero_with_no_attempts_anywhere(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)

    assert streak.current_streak(user=user) == 0


def test_streak_counts_consecutive_days_across_courses(isolated_courses_dir, user):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101", user)
    _seed_syllabus("psyc201", user)
    storage.append_quiz_attempt("cs101", _attempt_at(today), user=user)
    storage.append_quiz_attempt("psyc201", _attempt_at(today - timedelta(days=1)), user=user)
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)), user=user)

    assert streak.current_streak(user=user) == 3


def test_streak_alive_with_activity_yesterday_but_not_today(isolated_courses_dir, user):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101", user)
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=1)), user=user)
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)), user=user)

    assert streak.current_streak(user=user) == 2


def test_streak_breaks_after_full_day_gap(isolated_courses_dir, user):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101", user)
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)), user=user)
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=3)), user=user)

    assert streak.current_streak(user=user) == 0


def test_streak_ignores_a_course_with_corrupt_quiz_history(isolated_courses_dir, tmp_path, user):
    today = datetime.now(timezone.utc).date()
    _seed_syllabus("cs101", user)
    _seed_syllabus("badcourse", user)
    storage.append_quiz_attempt("cs101", _attempt_at(today), user=user)
    (tmp_path / str(user.pk) / "badcourse" / "quiz_history.json").write_text("{not valid json", encoding="utf-8")

    assert streak.current_streak(user=user) == 1


def test_streak_is_scoped_to_authenticated_user(isolated_courses_dir, django_user_model):
    today = datetime.now(timezone.utc).date()
    jordan = django_user_model.objects.create_user(username="jordan")
    alex = django_user_model.objects.create_user(username="alex")
    _seed_syllabus("cs101", jordan)
    _seed_syllabus("cs101", alex)
    storage.append_quiz_attempt("cs101", _attempt_at(today), user=alex)

    assert streak.current_streak(user=jordan) == 0
    assert streak.current_streak(user=alex) == 1
