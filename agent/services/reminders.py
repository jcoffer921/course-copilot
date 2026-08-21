"""
Read-only deadline digest across all courses. No writes, no external side
effects — just scans every course's syllabus.json for upcoming dates and
returns them sorted. Meant to be run manually or on a schedule (e.g. a daily
cron / Task Scheduler entry) to see what's coming up, distinct from
calendar_sync.py which actually commits specific events to Google Calendar.
"""

from datetime import date, datetime, timedelta
import json

from . import custom_events, storage


def list_courses() -> list:
    """Returns every course_id that has a syllabus.json, sorted."""
    if not storage.COURSES_DIR.exists():
        return []
    return sorted(
        p.name for p in storage.COURSES_DIR.iterdir()
        if p.is_dir() and (p / "syllabus.json").exists()
    )


def list_draft_courses() -> list:
    """Returns every course as {"course_id", "course_name", "created_at"}
    that has course.json but not syllabus.json — a class with a name but no
    syllabus uploaded yet — sorted by course_id. A course.json that fails to
    parse is skipped rather than raising, matching list_courses()'s "never
    fail the whole scan over one bad entry" shape."""
    if not storage.COURSES_DIR.exists():
        return []
    drafts = []
    for p in sorted(storage.COURSES_DIR.iterdir(), key=lambda p: p.name):
        if not p.is_dir():
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


def upcoming_deadlines(within_days: int = None, course_ids: list = None) -> list:
    """Returns [{"course_id", "date", "title", "type"}, ...] across all (or
    the given) courses, sorted by date. Only today-or-later dates are
    included; within_days caps how far into the future, or None for no cap."""
    today = date.today()
    cutoff = today + timedelta(days=within_days) if within_days is not None else None

    courses = course_ids if course_ids is not None else list_courses()

    deadlines = []
    for course_id in courses:
        syllabus = storage.read_syllabus(course_id)
        if syllabus is None:
            continue
        for d in syllabus.get("dates", []):
            try:
                event_date = datetime.strptime(d["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError, TypeError):
                continue
            if event_date < today:
                continue
            if cutoff is not None and event_date > cutoff:
                continue
            deadlines.append({
                "course_id": course_id,
                "date": d["date"],
                "title": d.get("title", ""),
                "type": d.get("type", "other"),
            })

    deadlines.sort(key=lambda d: d["date"])
    return deadlines


def list_all_deadlines() -> list:
    """Every upcoming deadline from both sources — syllabus-extracted
    (read-only, tagged source="syllabus") and manually-added (full CRUD,
    tagged source="custom") — combined and sorted by date, unbounded (no
    14-day cap, unlike the Dashboard's own upcoming_deadlines() call).
    Powers the Deadlines tab's full list.

    The sync-status annotation for syllabus deadlines duplicates
    dashboard.py's _annotate_synced (same 4-line cross-reference against
    read_calendar_sync) rather than importing it — dashboard.py already
    imports this module, so importing back would be circular."""
    today = date.today()

    syllabus_deadlines = upcoming_deadlines(within_days=None)
    synced_by_course = {}
    for d in syllabus_deadlines:
        course_id = d["course_id"]
        if course_id not in synced_by_course:
            try:
                synced_by_course[course_id] = storage.read_calendar_sync(course_id)
            except storage.CalendarSyncStorageError:
                synced_by_course[course_id] = None
        course_synced = synced_by_course[course_id]
        d["synced"] = course_synced is not None and any(
            r["date"] == d["date"] and r["title"] == d["title"]
            for r in course_synced
        )
        d["source"] = "syllabus"
        d["id"] = None
        d["time"] = None

    try:
        custom = [
            dict(e, source="custom")
            for e in custom_events.list_events()
            if e["date"] >= today.isoformat()
        ]
    except storage.CustomEventsStorageError:
        custom = []

    combined = syllabus_deadlines + custom
    combined.sort(key=lambda d: (d["date"], d["time"] or ""))
    return combined
