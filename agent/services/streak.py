"""
Global (cross-course) study streak: consecutive UTC calendar days with at
least one quiz attempt logged anywhere. Read-only, no writes — mirrors
reminders.py's cross-course scanning style. Deliberately global rather than
per-course: studying any course on a given day keeps the streak alive.
"""

from datetime import date, datetime, timedelta

from . import reminders, storage


def _attempt_dates(course_id: str) -> set:
    """Returns the set of UTC calendar dates this course has at least one
    quiz attempt on. A corrupt quiz_history.json contributes no dates rather
    than failing the whole streak computation — matches build_dashboard()'s
    per-course isolation contract in dashboard.py."""
    try:
        history = storage.read_quiz_history(course_id)
    except storage.QuizStorageError:
        return set()

    dates = set()
    for attempt in history.get("attempts", []):
        timestamp = attempt.get("timestamp")
        if not timestamp:
            continue
        try:
            dates.add(datetime.fromisoformat(timestamp).date())
        except ValueError:
            continue
    return dates


def current_streak() -> int:
    """Consecutive calendar days, across ALL courses combined, with at least
    one quiz attempt. Counts backward from today if today has activity, or
    from yesterday if today doesn't (yet) but yesterday does — the streak
    stays alive until a full day passes with zero activity anywhere, rather
    than resetting the instant today has no entry yet. 0 if neither today
    nor yesterday has any activity, including a brand-new install."""
    all_dates = set()
    for course_id in reminders.list_courses():
        all_dates |= _attempt_dates(course_id)

    today = date.today()
    if today in all_dates:
        cursor = today
    elif (today - timedelta(days=1)) in all_dates:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak_length = 0
    while cursor in all_dates:
        streak_length += 1
        cursor -= timedelta(days=1)
    return streak_length
