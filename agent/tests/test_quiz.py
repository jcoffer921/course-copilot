import pytest

from agent.services import quiz, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_recent_attempts_newest_first(isolated_courses_dir):
    storage.append_quiz_attempt("cs101", {"topic": "A", "timestamp": "2026-01-01T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "B", "timestamp": "2026-01-03T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "C", "timestamp": "2026-01-02T00:00:00"})

    attempts = quiz.recent_attempts("cs101")

    assert [a["topic"] for a in attempts] == ["B", "C", "A"]


def test_recent_attempts_respects_limit(isolated_courses_dir):
    for i in range(5):
        storage.append_quiz_attempt("cs101", {"topic": str(i), "timestamp": f"2026-01-0{i + 1}T00:00:00"})

    attempts = quiz.recent_attempts("cs101", limit=2)

    assert len(attempts) == 2
    assert [a["topic"] for a in attempts] == ["4", "3"]


def test_recent_attempts_empty_for_new_course(isolated_courses_dir):
    assert quiz.recent_attempts("brandnew") == []
