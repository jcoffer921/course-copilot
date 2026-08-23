import pytest
from django.contrib.auth.models import User

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_read_flashcard_progress_returns_empty_when_no_rows(isolated_courses_dir):
    assert storage.read_flashcard_progress("cs101") == {"course_id": "cs101", "cards": {}}


@pytest.mark.django_db
def test_update_flashcard_progress_writes_and_annotates(isolated_courses_dir):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "mastered",
        "starred": True,
    })

    assert result["status"] == "mastered"
    progress = storage.read_flashcard_progress("cs101")
    assert progress["cards"][result["key"]]["term"] == "Closure"

    cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }])
    assert cards[0]["key"] == result["key"]
    assert cards[0]["status"] == "mastered"
    assert cards[0]["starred"] is True


@pytest.mark.django_db
def test_not_started_unstarred_removes_progress_record(isolated_courses_dir):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "in_progress",
        "starred": False,
    })

    storage.update_flashcard_progress("cs101", {
        "key": result["key"],
        "term": "Closure",
        "definition": "Captured state.",
        "status": "not_started",
        "starred": False,
    })

    assert storage.read_flashcard_progress("cs101")["cards"] == {}


@pytest.mark.django_db
def test_not_started_starred_preserves_star_without_progress_status(isolated_courses_dir):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "not_started",
        "starred": True,
    })

    assert result["status"] == "not_started"
    assert result["starred"] is True
    cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }])
    assert cards[0]["status"] == "not_started"
    assert cards[0]["starred"] is True


@pytest.mark.django_db
def test_reset_flashcard_progress_removes_only_requested_keys(isolated_courses_dir):
    first = storage.update_flashcard_progress("cs101", {
        "term": "A", "definition": "One", "status": "mastered", "starred": False,
    })
    second = storage.update_flashcard_progress("cs101", {
        "term": "B", "definition": "Two", "status": "mastered", "starred": False,
    })

    storage.reset_flashcard_progress("cs101", [first["key"]])

    cards = storage.read_flashcard_progress("cs101")["cards"]
    assert first["key"] not in cards
    assert second["key"] in cards


@pytest.mark.django_db
def test_reset_flashcard_progress_preserves_starred_cards(isolated_courses_dir):
    saved = storage.update_flashcard_progress("cs101", {
        "term": "A", "definition": "One", "status": "mastered", "starred": True,
    })

    storage.reset_flashcard_progress("cs101", [saved["key"]])

    card = storage.read_flashcard_progress("cs101")["cards"][saved["key"]]
    assert card["starred"] is True
    assert "status" not in card


@pytest.mark.django_db
def test_flashcard_progress_is_scoped_per_user(isolated_courses_dir):
    jordan = User.objects.create_user(username="jordan")
    alex = User.objects.create_user(username="alex")

    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "mastered",
        "starred": False,
    }, user=jordan)

    jordan_cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }], user=jordan)
    alex_cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }], user=alex)

    assert jordan_cards[0]["key"] == result["key"]
    assert jordan_cards[0]["status"] == "mastered"
    assert alex_cards[0]["status"] == "not_started"


@pytest.mark.django_db
def test_remember_generated_flashcards_makes_unstudied_cards_visible(isolated_courses_dir):
    storage.remember_generated_flashcards("cs101", [{
        "term": "Closure",
        "definition": "A function plus captured state.",
    }])

    cards = storage.read_flashcard_progress("cs101")["cards"]
    assert len(cards) == 1
    card = next(iter(cards.values()))
    assert card["term"] == "Closure"
    assert card["definition"] == "A function plus captured state."
    assert card["starred"] is False
    assert "status" not in card
