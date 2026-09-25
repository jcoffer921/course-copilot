from datetime import datetime, timedelta, timezone

import pytest

from agent.services import mastery, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_history(course_id, attempts, user):
    for a in attempts:
        storage.append_quiz_attempt(course_id, a, user=user)


def test_rebuild_scores_ewma_math(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="ewma-owner")
    course_id = "testcourse"
    _seed_history(course_id, [
        {"topic": "Recursion", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Recursion", "correct": True, "timestamp": "2026-01-02T00:00:00"},
        {"topic": "Recursion", "correct": False, "timestamp": "2026-01-03T00:00:00"},
    ], user)

    data = mastery.rebuild_scores(course_id, user=user)

    recursion = next(s for s in data["scores"] if s["topic"] == "Recursion")
    # By hand, ALPHA=0.3, start 0.5:
    #   correct:   0.3*1 + 0.7*0.5   = 0.65
    #   correct:   0.3*1 + 0.7*0.65  = 0.755
    #   incorrect: 0.3*0 + 0.7*0.755 = 0.5285
    assert recursion["score"] == pytest.approx(0.5285, abs=1e-4)
    assert recursion["attempts"] == 3
    assert recursion["status"] == "needs_review"


def test_weak_topics_sorted_weakest_first(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="weak-owner")
    course_id = "testcourse"
    _seed_history(course_id, [
        {"topic": "Strong Topic", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Strong Topic", "correct": True, "timestamp": "2026-01-02T00:00:00"},
        {"topic": "Weak Topic", "correct": False, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Weak Topic", "correct": False, "timestamp": "2026-01-02T00:00:00"},
    ], user)
    mastery.rebuild_scores(course_id, user=user)

    topics = [s["topic"] for s in mastery.weak_topics(course_id, user=user)]
    assert topics == ["Weak Topic", "Strong Topic"]


def test_weak_topics_empty_before_any_rebuild(isolated_courses_dir):
    assert mastery.weak_topics("nocourse") == []


def test_rebuild_is_idempotent(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="idempotent-owner")
    course_id = "testcourse"
    _seed_history(course_id, [{"topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00"}], user)

    first = mastery.rebuild_scores(course_id, user=user)
    second = mastery.rebuild_scores(course_id, user=user)

    assert first["scores"] == second["scores"]


def _topic(data, name):
    return next(s for s in data["scores"] if s["topic"] == name)


def test_status_learning_below_weak_threshold(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="learning-owner")
    _seed_history("testcourse", [
        {"topic": "X", "correct": False, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "X", "correct": False, "timestamp": "2026-01-02T00:00:00"},
    ], user)
    # 0.3*0+0.7*0.5=0.35; 0.3*0+0.7*0.35=0.245 — below WEAK_THRESHOLD (0.4).

    data = mastery.rebuild_scores("testcourse", user=user)

    topic = _topic(data, "X")
    assert topic["score"] == pytest.approx(0.245, abs=1e-4)
    assert topic["status"] == mastery.LEARNING
    assert "2 attempt" in topic["reason"]


def test_status_needs_review_for_high_score_with_too_few_attempts(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="thin-owner")
    _seed_history("testcourse", [
        {"topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "X", "correct": True, "timestamp": "2026-01-02T00:00:00"},
    ], user)
    # 0.65, then 0.755 — already "strong" by score, but only 2 attempts
    # (< MIN_ATTEMPTS_PROFICIENT=3), so it shouldn't be trusted as proficient yet.
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)  # 1 day after last attempt: fresh, isolates the attempt-count effect

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "X")
    assert topic["score"] == pytest.approx(0.755, abs=1e-4)
    assert topic["status"] == mastery.NEEDS_REVIEW
    assert "2 attempt" in topic["reason"]


def test_status_proficient_with_enough_recent_attempts(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="proficient-owner")
    _seed_history("testcourse", [
        {"topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "X", "correct": True, "timestamp": "2026-01-02T00:00:00"},
        {"topic": "X", "correct": True, "timestamp": "2026-01-03T00:00:00"},
    ], user)
    # 0.65, 0.755, 0.8285 — strong score, 3 attempts, but not yet exam-ready (< 0.85).
    now = datetime(2026, 1, 4, tzinfo=timezone.utc)  # 1 day after last attempt: fresh

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "X")
    assert topic["score"] == pytest.approx(0.8285, abs=1e-4)
    assert topic["status"] == mastery.PROFICIENT


def test_status_exam_ready_with_high_score_enough_attempts_and_recency(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="exam-ready-owner")
    _seed_history("testcourse", [
        {"topic": "X", "correct": True, "timestamp": f"2026-01-0{i}T00:00:00"} for i in range(1, 6)
    ], user)
    # 5 correct in a row: 0.65, 0.755, 0.8285, 0.87995, 0.915965 — crosses
    # EXAM_READY_THRESHOLD (0.85) with attempts (5) >= MIN_ATTEMPTS_EXAM_READY.
    now = datetime(2026, 1, 6, tzinfo=timezone.utc)  # 1 day after last attempt: fresh

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "X")
    assert topic["score"] == pytest.approx(0.916, abs=1e-3)
    assert topic["attempts"] == 5
    assert topic["status"] == mastery.EXAM_READY


def test_status_at_risk_when_strong_score_has_gone_stale(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="at-risk-owner")
    _seed_history("testcourse", [
        {"topic": "X", "correct": True, "timestamp": f"2026-01-0{i}T00:00:00"} for i in range(1, 6)
    ], user)
    # Same high score/attempts as the exam-ready case above, but `now` is
    # far past AT_RISK_STALE_DAYS (14) since the last attempt — recency
    # should demote what would otherwise be exam-ready down to at_risk.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=30)

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "X")
    assert topic["status"] == mastery.AT_RISK
    assert "days" in topic["reason"]


def test_flashcard_ratings_alone_can_reach_proficient(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="flashcard-only-owner")
    storage.remember_generated_flashcards("testcourse", [
        {"key": "c1", "term": "A", "definition": "1"},
        {"key": "c2", "term": "B", "definition": "2"},
        {"key": "c3", "term": "C", "definition": "3"},
    ], user=user, topic="Loops")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    storage.review_flashcard("testcourse", "c1", "good", user=user, now=now)
    storage.review_flashcard("testcourse", "c2", "good", user=user, now=now)
    storage.review_flashcard("testcourse", "c3", "easy", user=user, now=now)
    # avg rating = (0.7 + 0.7 + 1.0) / 3 = 0.8 — no quiz attempts at all for
    # this topic, so the flashcard signal alone must drive the score.

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "Loops")
    assert topic["score"] == pytest.approx(0.8, abs=1e-4)
    assert topic["attempts"] == 3
    assert topic["status"] == mastery.PROFICIENT


def test_quiz_and_flashcard_signals_are_blended_when_both_exist(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="blend-owner")
    storage.append_quiz_attempt("testcourse", {
        "topic": "Recursion", "correct": True, "timestamp": "2026-01-01T00:00:00",
    }, user=user)  # quiz EWMA: 0.3*1 + 0.7*0.5 = 0.65
    storage.remember_generated_flashcards("testcourse", [
        {"key": "c1", "term": "A", "definition": "1"},
        {"key": "c2", "term": "B", "definition": "2"},
    ], user=user, topic="Recursion")
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    storage.review_flashcard("testcourse", "c1", "again", user=user, now=now)  # 0.0
    storage.review_flashcard("testcourse", "c2", "hard", user=user, now=now)  # 0.35
    # flashcard avg = 0.175. Blended: 0.7*0.65 + 0.3*0.175 = 0.455 + 0.0525 = 0.5075.

    data = mastery.rebuild_scores("testcourse", user=user, now=now)

    topic = _topic(data, "Recursion")
    assert topic["score"] == pytest.approx(0.5075, abs=1e-4)
    assert topic["attempts"] == 3  # 1 quiz attempt + 2 flashcard reviews


def test_a_topic_with_no_quiz_or_flashcard_activity_never_appears(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="no-activity-owner")
    _seed_history("testcourse", [{"topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00"}], user)

    data = mastery.rebuild_scores("testcourse", user=user)

    assert [s["topic"] for s in data["scores"]] == ["X"]


def test_rebuild_is_idempotent_with_blended_quiz_and_flashcard_inputs(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="idempotent-blend-owner")
    storage.append_quiz_attempt("testcourse", {
        "topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00",
    }, user=user)
    storage.remember_generated_flashcards("testcourse", [
        {"key": "c1", "term": "A", "definition": "1"},
    ], user=user, topic="X")
    storage.review_flashcard("testcourse", "c1", "good", user=user, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    fixed_now = datetime(2026, 1, 5, tzinfo=timezone.utc)

    first = mastery.rebuild_scores("testcourse", user=user, now=fixed_now)
    second = mastery.rebuild_scores("testcourse", user=user, now=fixed_now)

    assert first["scores"] == second["scores"]
