"""Course Overview hub composition — read-only, ownership-aware.

Composes the `/courses/<course_id>/` landing page's preview cards purely by
calling existing domain services (course_catalog, exams, recommendations,
mastery, grades, calendar_events, sessions, study_sessions). No calculation
happens here that those services don't already own.

Each section is isolated in its own try/except, mirroring dashboard.py's
per-course isolation idiom but applied per-section within one course: a
section with `available=False, error=None` is a legitimate empty state
("nothing here yet"); `error` set is a genuine failure to surface as
"couldn't load." Only the whole-course lookup (via build_course_header) is
allowed to raise uncaught — that's the page-level 404/400 case.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from django.db.utils import DatabaseError

from agent.models import StudySession

from . import calendar_events, course_catalog, exams, grades, mastery, materials, recommendations, sessions, storage, study_sessions


def _priority_section(course_id: str, user, header_next_deadline: dict | None, today: date) -> dict:
    now = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    try:
        upcoming_exams = [row for row in exams.list_exams(user, course_id, now=now) if row["days_until"] >= 0]
    except (storage.SyllabusStorageError, storage.CustomEventsStorageError, DatabaseError) as e:
        return {"available": False, "error": str(e)}
    if upcoming_exams:
        return {"available": True, "error": None, "kind": "exam", "exam": upcoming_exams[0]}
    if header_next_deadline:
        return {"available": True, "error": None, "kind": "deadline", "deadline": header_next_deadline}
    return {"available": False, "error": None}


def _materials_section(course_id: str, user) -> dict:
    try:
        summary = course_catalog.material_summary(course_id, user)
        rows = materials.list_materials(user, course_id)
    except (storage.SyllabusStorageError, storage.NotesStorageError, storage.ReferencesStorageError, DatabaseError) as e:
        return {"available": False, "error": str(e)}
    # The workspace count represents every visible material, including items
    # still processing or awaiting review.  Keep the ready-only count for
    # callers that need to distinguish published course context.
    summary["ready_count"] = summary["count"]
    summary["count"] = len(rows)
    has_any = bool(rows)
    priority = {"needs_review": 0, "failed": 1, "processing": 2, "uploaded": 3, "ready": 4}
    rows.sort(key=lambda row: (priority.get(row.get("processing_status"), 5), str(row.get("uploaded_at") or "")), reverse=False)
    return {"available": has_any, "error": None, "recent": rows[:3], **summary}


def _study_section(course_id: str, user) -> dict:
    try:
        recent = study_sessions.list_sessions(user, course_id=course_id, limit=1)
        in_progress = recent[0] if recent and recent[0]["status"] == StudySession.STATUS_IN_PROGRESS else None
        top = recommendations.rank_recommendations(user, limit=1, course_ids=[course_id])
        recommendation = top[0] if top else None
    except (storage.SyllabusStorageError, storage.CustomEventsStorageError, DatabaseError) as e:
        return {"available": False, "error": str(e)}
    return {
        "available": bool(in_progress or recommendation),
        "error": None,
        "in_progress_session": in_progress,
        "recommendation": recommendation,
    }


def _mastery_section(course_id: str, user, header_mastery: dict) -> dict:
    try:
        scores = mastery.weak_topics(course_id, user=user)
    except DatabaseError as e:
        return {"available": False, "error": str(e)}
    return {
        "available": header_mastery["available"],
        "error": None,
        "score": header_mastery["score"],
        "label": header_mastery["label"],
        "strongest_topic": scores[-1] if scores else None,
        "weakest_topic": scores[0] if scores else None,
    }


def _grades_section(course_id: str, user) -> dict:
    try:
        grade = grades.current_grade(course_id, user=user)
    except storage.CourseNotFoundError:
        # No syllabus.json yet (a draft course) — a normal state, not a
        # failure. CourseNotFoundError is also the signal build_course_overview
        # relies on for the whole-request 404, so it must never propagate
        # out of a per-section helper.
        return {"available": False, "error": None}
    except (storage.SyllabusStorageError, storage.GradesStorageError) as e:
        return {"available": False, "error": str(e)}
    item_count = sum(category["entered_count"] for category in grade["categories"])
    return {
        "available": grade["overall_pct"] is not None,
        "error": None,
        "overall_pct": grade["overall_pct"],
        "letter": grade["letter"],
        "item_count": item_count,
    }


def _schedule_section(course_id: str, user, today: date) -> dict:
    try:
        events = [
            event for event in calendar_events.upcoming_events(
                user, course_ids=[course_id], within_days=None, today=today,
            )
            if not event.get("completed")
        ]
    except (storage.SyllabusStorageError, storage.CustomEventsStorageError, DatabaseError) as e:
        return {"available": False, "error": str(e)}
    events = events[:3]
    return {"available": bool(events), "error": None, "events": events}


def _cora_section(course_id: str, user) -> dict:
    try:
        rows = sessions.list_sessions(course_id, user=user)
    except (sessions.SessionStorageError, DatabaseError) as e:
        return {"available": False, "error": str(e)}
    return {"available": bool(rows), "error": None, "session": rows[0] if rows else None}


def build_course_overview(course_id: str, user, today: date | None = None) -> dict:
    """Course-level lookup is unwrapped: storage.CourseNotFoundError /
    InvalidCourseIdError here means the course doesn't exist or isn't owned
    by `user` — the whole-request failure, matching CourseHeaderView."""
    today = today or date.today()
    header = course_catalog.build_course_header(course_id, user, today=today)
    return {
        "course": header["course"],
        "priority": _priority_section(course_id, user, header["next_deadline"], today),
        "materials": _materials_section(course_id, user),
        "study": _study_section(course_id, user),
        "mastery": _mastery_section(course_id, user, header["mastery"]),
        "grades": _grades_section(course_id, user),
        "schedule": _schedule_section(course_id, user, today),
        "cora": _cora_section(course_id, user),
    }
