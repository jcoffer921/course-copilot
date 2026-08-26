"""Deterministic, explainable spaced-repetition scheduling (algorithm v1).

Deliberately not SM-2/Anki-weighted: a fixed rating -> interval ladder keeps
"why is this card due today" answerable in one sentence, at the cost of not
adapting per-card ease over time. Revisit only once real review data shows
this is too coarse.
"""

from datetime import datetime, timedelta, timezone

RATINGS = ("again", "hard", "good", "easy")


class InvalidRatingError(ValueError):
    pass


def next_interval_days(rating: str, current_interval_days: int) -> int:
    """Returns the new interval (in days) for a card given the rating just
    given and the interval it was scheduled on before this review.

    - again: forgotten — due again today (interval resets to 0).
    - hard: struggled — held at (or nudged to) a short interval.
    - good: known — grows the interval on a fixed ladder (1 -> 3 -> doubling).
    - easy: known easily — grows faster than "good".
    """
    if rating not in RATINGS:
        raise InvalidRatingError(f"rating must be one of {RATINGS}, got {rating!r}")

    current = max(0, int(current_interval_days or 0))

    if rating == "again":
        return 0
    if rating == "hard":
        return max(1, current)
    if rating == "good":
        if current <= 0:
            return 1
        if current == 1:
            return 3
        return current * 2
    # easy
    if current <= 0:
        return 3
    return round(current * 2.5)


def schedule_review(rating: str, current_interval_days: int, now: datetime = None) -> dict:
    """Computes the full result of reviewing a card right now: the new
    interval, and the timestamp it next becomes due. `now` is injectable so
    scheduling is deterministic under a fixed clock in tests."""
    reviewed_at = now or datetime.now(timezone.utc)
    interval_days = next_interval_days(rating, current_interval_days)
    next_review = reviewed_at + timedelta(days=interval_days)
    return {
        "reviewed_at": reviewed_at,
        "interval_days": interval_days,
        "next_review": next_review,
    }
