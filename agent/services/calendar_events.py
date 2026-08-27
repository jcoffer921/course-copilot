"""Canonical, user-scoped calendar read model.

Syllabus dates remain owned by the confirmed ``syllabus.json`` document and
manual/study-plan events remain database rows.  This module is the one place
where those sources are composed for the dashboard, calendar, reminders, and
API consumers.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

from django.db.utils import DatabaseError

from . import storage


OVERDUE_CATEGORIES = {"hw", "project", "test_quiz"}
COURSE_COLORS = (
    "#6D5EF6",
    "#168C7E",
    "#D26A3A",
    "#3478C7",
    "#A24D83",
    "#768436",
    "#B34E55",
    "#527B9B",
)
GENERAL_EVENT_COLOR = "#697386"
EVENT_TYPE_FILTERS = (
    {"id": "assignments", "label": "Assignments", "types": ["hw", "project"]},
    {"id": "exams", "label": "Exams", "types": ["test_quiz"]},
    {"id": "study", "label": "Study, meetings & personal", "types": ["other"]},
    {"id": "classes", "label": "Classes", "types": ["class"]},
)


def list_course_ids(user) -> list[str]:
    """Return course IDs with trusted syllabus content for ``user``."""
    user_dir = storage.COURSES_DIR / str(user.pk)
    if not user_dir.exists():
        return []
    return sorted(
        path.name
        for path in user_dir.iterdir()
        if path.is_dir() and (path / "syllabus.json").exists() and not storage.course_is_archived(path.name, user)
    )


def syllabus_deadline_key(deadline: dict) -> str:
    """Build the legacy replacement key used by existing edited deadlines."""
    return "|".join(
        [
            deadline.get("course_id") or "",
            deadline.get("date") or "",
            deadline.get("title") or "",
            deadline.get("type") or "other",
        ]
    )


def stable_syllabus_event_id(user, deadline_key: str) -> str:
    """Return a deterministic ID that is private to one user's namespace."""
    owner = str(getattr(user, "pk", "anonymous"))
    digest = hashlib.sha256(f"{owner}\0{deadline_key}".encode("utf-8")).hexdigest()
    return f"syllabus-{digest[:40]}"


def course_color(course_id: str | None) -> str:
    if not course_id:
        return GENERAL_EVENT_COLOR
    digest = hashlib.sha256(course_id.encode("utf-8")).digest()
    return COURSE_COLORS[digest[0] % len(COURSE_COLORS)]


def _confirmed_syllabus_material_id(user, course_id: str) -> str | None:
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        from agent.models import CourseMaterial

        material = (
            CourseMaterial.objects.filter(
                user=user,
                course_id=course_id,
                material_type=CourseMaterial.TYPE_SYLLABUS,
                processing_status=CourseMaterial.STATUS_READY,
                review_status=CourseMaterial.REVIEW_CONFIRMED,
            )
            .order_by("-confirmed_at", "-uploaded_at")
            .first()
        )
    except DatabaseError:
        return None
    return str(material.material_id) if material else None


def _sync_records(user, course_id: str, cache: dict) -> list | None:
    if course_id not in cache:
        try:
            cache[course_id] = storage.read_calendar_sync(course_id, user=user)
        except storage.CalendarSyncStorageError:
            cache[course_id] = None
    return cache[course_id]


def _syllabus_event(user, course_id: str, raw: dict, material_id: str | None, sync_cache: dict) -> dict | None:
    try:
        event_date = datetime.strptime(raw["date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None

    event_type = storage.normalize_date_type(raw.get("type", "other"))
    base = {
        "course_id": course_id,
        "date": event_date.isoformat(),
        "title": str(raw.get("title") or ""),
        "type": event_type,
    }
    key = syllabus_deadline_key(base)
    records = _sync_records(user, course_id, sync_cache)
    synced_record = next(
        (
            record
            for record in (records or [])
            if record.get("date") == base["date"] and record.get("title") == base["title"]
        ),
        None,
    )
    return {
        "id": stable_syllabus_event_id(user, key),
        "key": key,
        **base,
        "time": None,
        "start_time": None,
        "end_time": None,
        "all_day": True,
        "completed": False,
        "course_color": course_color(course_id),
        "source": "syllabus",
        "confirmed": True,
        "extraction_state": "confirmed",
        "estimated_effort_minutes": None,
        "source_material_id": material_id,
        "replaces_syllabus_key": None,
        "synced": synced_record is not None,
        "google_event_id": synced_record.get("google_event_id") if synced_record else None,
        "synced_at": synced_record.get("synced_at") if synced_record else None,
        "created_at": None,
    }


def _custom_event(raw: dict) -> dict:
    start_time = raw.get("time")
    source = raw.get("source") if raw.get("source") in {"manual", "study_plan"} else "manual"
    return {
        **raw,
        "key": raw.get("replaces_syllabus_key") or raw.get("id"),
        "start_time": start_time,
        "all_day": not bool(start_time),
        "course_color": course_color(raw.get("course_id")),
        "source": source,
        "confirmed": True,
        "extraction_state": "confirmed",
        "estimated_effort_minutes": raw.get("estimated_effort_minutes"),
        "source_material_id": raw.get("source_material_id"),
    }


def all_events(user, course_ids: list[str] | None = None, include_general: bool = False) -> list[dict]:
    """Compose every confirmed syllabus, manual, and study-plan event.

    Pending syllabus review candidates are intentionally absent: only the
    trusted, post-confirmation syllabus store is read here. A malformed
    syllabus is isolated to its course (skipped) rather than raising, same
    as calendar_snapshot(), so one bad upload cannot blank every exam
    workspace/plan/study-guide view that this function backs.
    """
    requested_ids = list_course_ids(user) if course_ids is None else list(course_ids)
    try:
        raw_custom = storage.read_custom_events(user=user)
    except (storage.CustomEventsStorageError, DatabaseError):
        raw_custom = []

    replaced_keys = {
        event.get("replaces_syllabus_key")
        for event in raw_custom
        if event.get("replaces_syllabus_key")
    }
    custom = [
        _custom_event(event)
        for event in raw_custom
        if course_ids is None
        or event.get("course_id") in requested_ids
        or (include_general and event.get("course_id") is None)
    ]

    sync_cache: dict = {}
    syllabus_events = []
    for course_id in requested_ids:
        try:
            syllabus = storage.read_syllabus(course_id, user)
        except storage.SyllabusStorageError:
            continue
        if syllabus is None:
            continue
        material_id = _confirmed_syllabus_material_id(user, course_id)
        for raw in syllabus.get("dates", []):
            event = _syllabus_event(user, course_id, raw, material_id, sync_cache)
            if event is not None and event["key"] not in replaced_keys:
                syllabus_events.append(event)

    combined = syllabus_events + custom
    combined.sort(key=lambda event: (event["date"], event.get("start_time") or "", event["title"], event["id"]))
    return combined


def calendar_snapshot(user) -> dict:
    """Return the complete internal-calendar contract for one user.

    A malformed syllabus is isolated to its course and reported as a warning,
    so one bad upload cannot blank the learner's entire calendar. Pending
    review candidates remain excluded because this reads only syllabus.json.
    """
    requested_ids = list_course_ids(user)
    warnings = []
    try:
        raw_custom = storage.read_custom_events(user=user)
    except (storage.CustomEventsStorageError, DatabaseError):
        raw_custom = []
        warnings.append({"scope": "events", "detail": "Some personal calendar events could not be loaded."})

    replaced_keys = {
        event.get("replaces_syllabus_key")
        for event in raw_custom
        if event.get("replaces_syllabus_key")
    }
    events = [_custom_event(event) for event in raw_custom]
    courses = []
    sync_cache = {}
    for course_id in requested_ids:
        try:
            syllabus = storage.read_syllabus(course_id, user)
        except storage.SyllabusStorageError:
            warnings.append({"scope": course_id, "detail": f"{course_id.upper()} could not be loaded."})
            continue
        if syllabus is None:
            continue
        courses.append({
            "id": course_id,
            "name": syllabus.get("course_name") or course_id.upper(),
            "color": course_color(course_id),
        })
        material_id = _confirmed_syllabus_material_id(user, course_id)
        for raw in syllabus.get("dates", []):
            event = _syllabus_event(user, course_id, raw, material_id, sync_cache)
            if event is not None and event["key"] not in replaced_keys:
                events.append(event)

    course_names = {course["id"]: course["name"] for course in courses}
    for event in events:
        event["course_name"] = course_names.get(event.get("course_id"), "Unassigned")
        event.setdefault("location", "")
        event.setdefault("notes", "")
    events.sort(key=lambda event: (event["date"], event.get("start_time") or "", event["title"], event["id"]))
    return {
        "events": events,
        "courses": courses,
        "event_types": list(EVENT_TYPE_FILTERS),
        "warnings": warnings,
    }


def upcoming_events(
    user,
    within_days: int | None = None,
    course_ids: list[str] | None = None,
    include_incomplete_overdue: bool = False,
    include_general: bool = False,
) -> list[dict]:
    today = date.today()
    cutoff = today + timedelta(days=within_days) if within_days is not None else None
    result = []
    for event in all_events(user, course_ids=course_ids, include_general=include_general):
        try:
            event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        is_overdue = event_date < today
        if is_overdue and not (
            include_incomplete_overdue
            and not event.get("completed")
            and storage.normalize_date_type(event.get("type")) in OVERDUE_CATEGORIES
        ):
            continue
        if not is_overdue and cutoff is not None and event_date > cutoff:
            continue
        result.append(event)
    return result


def validate_syllabus_replacement(user, course_id: str | None, deadline_key: str) -> None:
    """Reject attempts to override another user/course or an untrusted date."""
    if not course_id:
        course_id = str(deadline_key or "").split("|", 1)[0] or None
    if not course_id:
        raise ValueError("a syllabus deadline replacement requires a course-owned key")
    syllabus = storage.read_syllabus(course_id, user)
    if syllabus is None:
        raise ValueError(f"no confirmed syllabus found for '{course_id}'")
    for raw in syllabus.get("dates", []):
        event_type = storage.normalize_date_type(raw.get("type", "other"))
        candidate = syllabus_deadline_key(
            {
                "course_id": course_id,
                "date": raw.get("date"),
                "title": str(raw.get("title") or ""),
                "type": event_type,
            }
        )
        if candidate == deadline_key:
            return
    raise ValueError("replaces_syllabus_key does not match a confirmed deadline in this course")
