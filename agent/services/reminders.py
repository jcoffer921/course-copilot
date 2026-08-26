"""
Read-only deadline digest across all courses. No writes, no external side
effects — just scans every course's syllabus.json for upcoming dates and
returns them sorted. Meant to be run manually or on a schedule (e.g. a daily
cron / Task Scheduler entry) to see what's coming up, distinct from
calendar_sync.py which actually commits specific events to Google Calendar.
"""

import json
from . import calendar_events, storage


def list_courses(user) -> list:
    """Returns every course_id that has a syllabus.json for this user, sorted."""
    return calendar_events.list_course_ids(user)


def list_draft_courses(user) -> list:
    """Returns every course as {"course_id", "course_name", "created_at"}
    for this user that has course.json but not syllabus.json — a class
    with a name but no syllabus uploaded yet — sorted by course_id. A
    course.json that fails to parse is skipped rather than raising,
    matching list_courses()'s "never fail the whole scan over one bad
    entry" shape."""
    user_dir = storage.COURSES_DIR / str(user.pk)
    if not user_dir.exists():
        return []
    drafts = []
    for p in sorted(user_dir.iterdir(), key=lambda p: p.name):
        if not p.is_dir():
            continue
        if storage.course_is_archived(p.name, user):
            continue
        if (p / "syllabus.json").exists():
            continue
        course_json = p / "course.json"
        if not course_json.exists():
            continue
        try:
            parsed = json.loads(course_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(parsed, dict) or "course_id" not in parsed:
            continue
        drafts.append(parsed)
    return drafts


def _syllabus_deadline_key(deadline: dict) -> str:
    return calendar_events.syllabus_deadline_key(deadline)


def upcoming_deadlines(user, within_days: int = None, course_ids: list = None, include_general: bool = False) -> list:
    """Returns [{"course_id", "date", "title", "type"}, ...] across all (or
    the given) of this user's courses, sorted by date. Only today-or-later
    dates are included; within_days caps how far into the future, or None
    for no cap."""
    return calendar_events.upcoming_events(
        user,
        within_days=within_days,
        course_ids=course_ids,
        include_general=include_general,
    )


def list_all_deadlines(user=None, course_id: str = None) -> list:
    """Every visible confirmed event for the internal calendar."""
    return calendar_events.upcoming_events(
        user,
        within_days=None,
        course_ids=[course_id] if course_id else None,
        include_incomplete_overdue=True,
    )
