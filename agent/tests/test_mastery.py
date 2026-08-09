import pytest

from agent.services import mastery, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_history(course_id, attempts):
    for a in attempts:
        storage.append_quiz_attempt(course_id, a)


def test_rebuild_scores_ewma_math(isolated_courses_dir):
    course_id = "testcourse"
    _seed_history(course_id, [
        {"topic": "Recursion", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Recursion", "correct": True, "timestamp": "2026-01-02T00:00:00"},
        {"topic": "Recursion", "correct": False, "timestamp": "2026-01-03T00:00:00"},
    ])

    data = mastery.rebuild_scores(course_id)

    recursion = next(s for s in data["scores"] if s["topic"] == "Recursion")
    # By hand, ALPHA=0.3, start 0.5:
    #   correct:   0.3*1 + 0.7*0.5   = 0.65
    #   correct:   0.3*1 + 0.7*0.65  = 0.755
    #   incorrect: 0.3*0 + 0.7*0.755 = 0.5285
    assert recursion["score"] == pytest.approx(0.5285, abs=1e-4)
    assert recursion["attempts"] == 3
    assert recursion["status"] == "developing"


def test_weak_topics_sorted_weakest_first(isolated_courses_dir):
    course_id = "testcourse"
    _seed_history(course_id, [
        {"topic": "Strong Topic", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Strong Topic", "correct": True, "timestamp": "2026-01-02T00:00:00"},
        {"topic": "Weak Topic", "correct": False, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Weak Topic", "correct": False, "timestamp": "2026-01-02T00:00:00"},
    ])
    mastery.rebuild_scores(course_id)

    topics = [s["topic"] for s in mastery.weak_topics(course_id)]
    assert topics == ["Weak Topic", "Strong Topic"]


def test_weak_topics_empty_before_any_rebuild(isolated_courses_dir):
    assert mastery.weak_topics("nocourse") == []


def test_rebuild_is_idempotent(isolated_courses_dir):
    course_id = "testcourse"
    _seed_history(course_id, [{"topic": "X", "correct": True, "timestamp": "2026-01-01T00:00:00"}])

    first = mastery.rebuild_scores(course_id)
    second = mastery.rebuild_scores(course_id)

    assert first["scores"] == second["scores"]
