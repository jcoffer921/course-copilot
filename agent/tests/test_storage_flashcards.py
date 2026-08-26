from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    from agent.models import FlashcardProgress
    FlashcardProgress.objects.all().delete()
    return tmp_path


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner")


@pytest.mark.django_db
def test_read_flashcard_progress_returns_empty_when_no_rows(isolated_courses_dir):
    assert storage.read_flashcard_progress("cs101") == {"course_id": "cs101", "cards": {}}


@pytest.mark.django_db
def test_update_flashcard_progress_writes_and_annotates(isolated_courses_dir, owner):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "mastered",
        "starred": True,
    }, user=owner)

    assert result["status"] == "mastered"
    progress = storage.read_flashcard_progress("cs101", user=owner)
    assert progress["cards"][result["key"]]["term"] == "Closure"

    cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }], user=owner)
    assert cards[0]["key"] == result["key"]
    assert cards[0]["status"] == "mastered"
    assert cards[0]["starred"] is True


@pytest.mark.django_db
def test_not_started_unstarred_clears_progress_but_keeps_card(isolated_courses_dir, owner):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "in_progress",
        "starred": False,
    }, user=owner)

    storage.update_flashcard_progress("cs101", {
        "key": result["key"],
        "term": "Closure",
        "definition": "Captured state.",
        "status": "not_started",
        "starred": False,
    }, user=owner)

    card = storage.read_flashcard_progress("cs101", user=owner)["cards"][result["key"]]
    assert card["term"] == "Closure"
    assert card["definition"] == "Captured state."
    assert card["starred"] is False
    assert "status" not in card


@pytest.mark.django_db
def test_not_started_starred_preserves_star_without_progress_status(isolated_courses_dir, owner):
    result = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "not_started",
        "starred": True,
    }, user=owner)

    assert result["status"] == "not_started"
    assert result["starred"] is True
    cards = storage.annotate_flashcards_with_progress("cs101", [{
        "term": "Closure",
        "definition": "Captured state.",
    }], user=owner)
    assert cards[0]["status"] == "not_started"
    assert cards[0]["starred"] is True


@pytest.mark.django_db
def test_reset_flashcard_progress_clears_only_requested_keys(isolated_courses_dir, owner):
    first = storage.update_flashcard_progress("cs101", {
        "term": "A", "definition": "One", "status": "mastered", "starred": False,
    }, user=owner)
    second = storage.update_flashcard_progress("cs101", {
        "term": "B", "definition": "Two", "status": "mastered", "starred": False,
    }, user=owner)

    storage.reset_flashcard_progress("cs101", [first["key"]], user=owner)

    cards = storage.read_flashcard_progress("cs101", user=owner)["cards"]
    assert "status" not in cards[first["key"]]
    assert second["key"] in cards
    assert cards[second["key"]]["status"] == "mastered"


@pytest.mark.django_db
def test_reset_flashcard_progress_preserves_starred_cards(isolated_courses_dir, owner):
    saved = storage.update_flashcard_progress("cs101", {
        "term": "A", "definition": "One", "status": "mastered", "starred": True,
    }, user=owner)

    storage.reset_flashcard_progress("cs101", [saved["key"]], user=owner)

    card = storage.read_flashcard_progress("cs101", user=owner)["cards"][saved["key"]]
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
def test_remember_generated_flashcards_makes_unstudied_cards_visible(isolated_courses_dir, owner):
    storage.remember_generated_flashcards("cs101", [{
        "term": "Closure",
        "definition": "A function plus captured state.",
    }], user=owner)

    cards = storage.read_flashcard_progress("cs101", user=owner)["cards"]
    assert len(cards) == 1
    card = next(iter(cards.values()))
    assert card["term"] == "Closure"
    assert card["definition"] == "A function plus captured state."
    assert card["starred"] is False
    assert "status" not in card


@pytest.mark.django_db
def test_review_flashcard_creates_row_and_schedules_next_review(isolated_courses_dir, owner):
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = storage.review_flashcard("cs101", "card-1", "good", user=owner, now=fixed_now)

    assert result["review_count"] == 1
    assert result["interval_days"] == 1
    assert result["rating"] == "good"
    assert result["last_reviewed"] == fixed_now.isoformat()
    assert result["next_review"] == (fixed_now + timedelta(days=1)).isoformat()


@pytest.mark.django_db
def test_review_flashcard_second_review_grows_interval_from_first(isolated_courses_dir, owner):
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = datetime(2026, 1, 2, tzinfo=timezone.utc)

    storage.review_flashcard("cs101", "card-1", "good", user=owner, now=first)
    result = storage.review_flashcard("cs101", "card-1", "good", user=owner, now=second)

    assert result["review_count"] == 2
    assert result["interval_days"] == 3
    assert result["next_review"] == (second + timedelta(days=3)).isoformat()


@pytest.mark.django_db
def test_review_flashcard_preserves_term_definition_and_status(isolated_courses_dir, owner):
    saved = storage.update_flashcard_progress("cs101", {
        "term": "Closure", "definition": "Captured state.", "status": "mastered", "starred": True,
    }, user=owner)

    storage.review_flashcard("cs101", saved["key"], "hard", user=owner)

    card = storage.read_flashcard_progress("cs101", user=owner)["cards"][saved["key"]]
    assert card["term"] == "Closure"
    assert card["status"] == "mastered"
    assert card["starred"] is True


@pytest.mark.django_db
def test_review_flashcard_rejects_invalid_rating(isolated_courses_dir, owner):
    with pytest.raises(ValueError):
        storage.review_flashcard("cs101", "card-1", "meh", user=owner)


@pytest.mark.django_db
def test_reviewing_a_suspended_card_is_rejected_not_silently_reactivated(isolated_courses_dir, owner):
    storage.review_flashcard("cs101", "card-1", "good", user=owner)
    storage.suspend_flashcard("cs101", "card-1", user=owner)

    with pytest.raises(storage.FlashcardSuspendedError):
        storage.review_flashcard("cs101", "card-1", "good", user=owner)


@pytest.mark.django_db
def test_suspend_then_unsuspend_flashcard(isolated_courses_dir, owner):
    storage.review_flashcard("cs101", "card-1", "good", user=owner)

    suspended = storage.suspend_flashcard("cs101", "card-1", user=owner)
    assert suspended["suspended"] is True

    resumed = storage.suspend_flashcard("cs101", "card-1", suspended=False, user=owner)
    assert resumed["suspended"] is False


@pytest.mark.django_db
def test_due_flashcards_excludes_suspended_and_not_yet_due_cards(isolated_courses_dir, owner):
    fixed_now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    storage.remember_generated_flashcards("cs101", [
        {"key": "overdue", "term": "Overdue", "definition": "Due already."},
        {"key": "not-due-yet", "term": "Not due", "definition": "Reviewed recently."},
        {"key": "suspended-but-due", "term": "Suspended", "definition": "Would be due."},
        {"term": "Never reviewed", "definition": "Due immediately."},
    ], user=owner)
    storage.review_flashcard("cs101", "overdue", "good", user=owner, now=fixed_now - timedelta(days=5))
    storage.review_flashcard("cs101", "not-due-yet", "easy", user=owner, now=fixed_now)
    storage.review_flashcard("cs101", "suspended-but-due", "good", user=owner, now=fixed_now - timedelta(days=5))
    storage.suspend_flashcard("cs101", "suspended-but-due", user=owner)

    due = storage.due_flashcards("cs101", user=owner, now=fixed_now)
    due_keys = {card["key"] for card in due}

    assert "overdue" in due_keys
    assert "not-due-yet" not in due_keys
    assert "suspended-but-due" not in due_keys
    assert any(card["term"] == "Never reviewed" for card in due)


@pytest.mark.django_db
def test_due_flashcards_is_scoped_per_user(isolated_courses_dir):
    jordan = User.objects.create_user(username="jordan")
    alex = User.objects.create_user(username="alex")
    storage.remember_generated_flashcards("cs101", [
        {"key": "card-1", "term": "Closure", "definition": "Captured state."},
    ], user=jordan)
    storage.review_flashcard("cs101", "card-1", "again", user=jordan)

    assert len(storage.due_flashcards("cs101", user=jordan)) == 1
    assert len(storage.due_flashcards("cs101", user=alex)) == 0


@pytest.mark.django_db
def test_remember_generated_flashcards_does_not_reset_spaced_repetition_state(isolated_courses_dir, owner):
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    storage.remember_generated_flashcards("cs101", [
        {"key": "card-1", "term": "Closure", "definition": "Captured state."},
    ], user=owner)
    storage.review_flashcard("cs101", "card-1", "good", user=owner, now=fixed_now)

    storage.remember_generated_flashcards("cs101", [
        {"key": "card-1", "term": "Closure", "definition": "Captured state."},
    ], user=owner)

    card = storage.read_flashcard_progress("cs101", user=owner)["cards"]["card-1"]
    assert card["term"] == "Closure"
    due = storage.due_flashcards("cs101", user=owner, now=fixed_now + timedelta(days=1))
    assert due[0]["review_count"] == 1
