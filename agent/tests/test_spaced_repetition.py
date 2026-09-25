from datetime import datetime, timedelta, timezone

import pytest

from agent.services import spaced_repetition as sr


def test_again_always_resets_interval_to_zero():
    assert sr.next_interval_days("again", 0) == 0
    assert sr.next_interval_days("again", 30) == 0


def test_hard_holds_at_current_interval_with_a_floor_of_one():
    assert sr.next_interval_days("hard", 0) == 1
    assert sr.next_interval_days("hard", 5) == 5


def test_good_grows_on_a_fixed_ladder():
    assert sr.next_interval_days("good", 0) == 1
    assert sr.next_interval_days("good", 1) == 3
    assert sr.next_interval_days("good", 3) == 6
    assert sr.next_interval_days("good", 6) == 12


def test_easy_grows_faster_than_good():
    assert sr.next_interval_days("easy", 0) == 3
    assert sr.next_interval_days("easy", 4) == 10
    assert sr.next_interval_days("easy", 6) > sr.next_interval_days("good", 6)


def test_invalid_rating_raises():
    with pytest.raises(sr.InvalidRatingError):
        sr.next_interval_days("meh", 0)


def test_schedule_review_is_deterministic_under_a_fixed_clock():
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = sr.schedule_review("good", 1, now=fixed_now)

    assert result["reviewed_at"] == fixed_now
    assert result["interval_days"] == 3
    assert result["next_review"] == fixed_now + timedelta(days=3)


def test_schedule_review_again_is_due_immediately():
    fixed_now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = sr.schedule_review("again", 12, now=fixed_now)

    assert result["interval_days"] == 0
    assert result["next_review"] == fixed_now
