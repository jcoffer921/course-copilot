"""Owned course metadata, archive lifecycle, and Courses-page composition."""

from __future__ import annotations

import re
from datetime import date, datetime

from django.db.utils import DatabaseError

from agent.models import CourseMaterial

from . import calendar_events, mastery, materials, storage

SEMESTER_RE = re.compile(r"^(spring|summer|fall|winter)-(\d{4})$")
COURSE_COLORS = (
    "#527d47", "#db5427", "#7155b5", "#2f7d89",
    "#9b5b37", "#4c6fa9", "#9a4773", "#6f7c35",
)
SEASON_ORDER = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}


class SemesterMoveRequiresConfirmation(ValueError):
    pass


def current_semester(today: date | None = None) -> str:
    today = today or date.today()
    season = "spring" if today.month <= 5 else "summer" if today.month <= 7 else "fall"
    return f"{season}-{today.year}"


def semester_label(semester_id: str) -> str:
    match = SEMESTER_RE.fullmatch(str(semester_id or ""))
    if not match:
        raise ValueError("semester must look like fall-2026")
    return f"{match.group(1).title()} {match.group(2)}"


def _semester_sort_key(semester_id: str) -> tuple[int, int]:
    match = SEMESTER_RE.fullmatch(semester_id)
    return (int(match.group(2)), SEASON_ORDER[match.group(1)]) if match else (0, 0)


def _initials(name: str, code: str) -> str:
    source = code or name
    words = re.findall(r"[A-Za-z0-9]+", source)
    if not words:
        return "OT"
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(word[0] for word in words[:2]).upper()


def _all_course_ids(user) -> list[str]:
    user_dir = storage.COURSES_DIR / str(user.pk)
    if not user_dir.exists():
        return []
    return sorted(
        path.name for path in user_dir.iterdir()
        if path.is_dir() and storage.COURSE_ID_RE.fullmatch(path.name)
        and ((path / "course.json").exists() or (path / "syllabus.json").exists())
    )


def _legacy_created_at(course_id: str, user) -> str:
    course_dir = storage.COURSES_DIR / str(user.pk) / course_id
    candidates = [path for path in (course_dir / "course.json", course_dir / "syllabus.json") if path.exists()]
    timestamp = min((path.stat().st_mtime for path in candidates), default=datetime.now().timestamp())
    return datetime.fromtimestamp(timestamp).astimezone().isoformat()


def _base_record(course_id: str, user) -> dict:
    metadata = storage.read_course_metadata(course_id, user)
    syllabus = storage.read_syllabus(course_id, user)
    if metadata is None and syllabus is None:
        raise storage.CourseNotFoundError(f"no course '{course_id}' found")
    created_at = (metadata or {}).get("created_at") or _legacy_created_at(course_id, user)
    default_term = current_semester(datetime.fromisoformat(created_at).date())
    name = (metadata or {}).get("course_name") or (syllabus or {}).get("course_name") or course_id.upper()
    code = str((metadata or {}).get("course_code") or "").strip()
    color = (metadata or {}).get("color")
    if color not in COURSE_COLORS:
        color = calendar_events.course_color(course_id)
    semester = (metadata or {}).get("semester") or default_term
    if not SEMESTER_RE.fullmatch(str(semester)):
        semester = current_semester()
    return {
        "id": course_id,
        "name": name,
        "code": code,
        "instructor": str((metadata or {}).get("instructor") or "").strip(),
        "semester": semester,
        "semester_label": semester_label(semester),
        "color": color,
        "archived": bool((metadata or {}).get("archived", False)),
        "created_at": created_at,
        "is_draft": syllabus is None,
        "initials": _initials(name, code),
    }


def create_course(user, course_id: str, data: dict) -> dict:
    semester_label(data["semester"])
    color = data.get("color") or calendar_events.course_color(course_id)
    if color not in COURSE_COLORS and color != calendar_events.course_color(course_id):
        raise ValueError("color is not in the approved course palette")
    storage.write_course_draft(
        course_id, data["course_name"], user,
        course_code=data.get("course_code", ""), instructor=data.get("instructor", ""),
        semester=data["semester"], color=color, archived=False,
    )
    return _base_record(course_id, user)


def update_course(user, course_id: str, changes: dict) -> dict:
    existing = _base_record(course_id, user)
    new_semester = changes.get("semester", existing["semester"])
    semester_label(new_semester)
    if new_semester != existing["semester"] and not changes.pop("confirm_semester_move", False):
        raise SemesterMoveRequiresConfirmation("Moving a course to another semester requires confirmation.")
    color = changes.get("color", existing["color"])
    if color not in COURSE_COLORS and color != calendar_events.course_color(course_id):
        raise ValueError("color is not in the approved course palette")
    name = changes.get("course_name", existing["name"])
    storage.rename_course(course_id, name, user)
    metadata = storage.read_course_metadata(course_id, user) or {
        "course_id": course_id, "course_name": name, "created_at": existing["created_at"],
    }
    metadata.update({
        "course_name": name,
        "course_code": changes.get("course_code", existing["code"]),
        "instructor": changes.get("instructor", existing["instructor"]),
        "semester": new_semester,
        "color": color,
        "archived": existing["archived"],
    })
    storage.write_course_metadata(course_id, metadata, user)
    return _base_record(course_id, user)


def set_archived(user, course_id: str, archived: bool) -> dict:
    existing = _base_record(course_id, user)
    metadata = storage.read_course_metadata(course_id, user) or {
        "course_id": course_id, "course_name": existing["name"], "created_at": existing["created_at"],
        "course_code": existing["code"], "instructor": existing["instructor"],
        "semester": existing["semester"], "color": existing["color"],
    }
    metadata["archived"] = bool(archived)
    storage.write_course_metadata(course_id, metadata, user)
    return _base_record(course_id, user)


def _mastery_summary(course_id: str, user) -> dict:
    scores = mastery.weak_topics(course_id, user=user)
    if not scores:
        return {"available": False, "score": None, "status": "not_started", "label": "Not enough data"}
    score = round(sum(row["score"] for row in scores) / len(scores) * 100)
    return {"available": True, "score": score, "status": scores[-1].get("status", "learning"), "label": f"{score}%"}


def material_summary(course_id: str, user) -> dict:
    rows = materials.list_materials(user, course_id)
    ready = [row for row in rows if row["processing_status"] == CourseMaterial.STATUS_READY and row.get("review_status") != CourseMaterial.REVIEW_SUPERSEDED]
    return {
        "count": len(ready),
        "needs_review": len([row for row in rows if row["processing_status"] == CourseMaterial.STATUS_NEEDS_REVIEW]),
        "failed": len([row for row in rows if row["processing_status"] == CourseMaterial.STATUS_FAILED]),
    }


def _relative_label(event_date: str, today: date) -> str:
    delta = (date.fromisoformat(event_date) - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return f"{delta} days"


def _in_semester(event_date: str, semester: str) -> bool:
    """Apply the v1 academic-term boundary used by Courses summaries."""
    match = SEMESTER_RE.fullmatch(semester)
    try:
        value = date.fromisoformat(event_date)
    except (TypeError, ValueError):
        return False
    if not match or value.year != int(match.group(2)):
        return False
    months = {
        "winter": {1},
        "spring": {1, 2, 3, 4, 5},
        "summer": {6, 7},
        "fall": {8, 9, 10, 11, 12},
    }
    return value.month in months[match.group(1)]


def build_course_header(course_id: str, user, today: date | None = None) -> dict:
    """Compose the course-workspace header: identity, next deadline, mastery."""
    today = today or date.today()
    record = _base_record(course_id, user)
    try:
        deadlines = [
            event for event in calendar_events.upcoming_events(
                user, course_ids=[course_id], within_days=None, today=today,
            )
            if not event.get("completed")
        ]
    except (storage.SyllabusStorageError, storage.CustomEventsStorageError, DatabaseError):
        deadlines = []
    next_deadline = deadlines[0] if deadlines else None
    if next_deadline:
        next_deadline = {**next_deadline, "relative_label": _relative_label(next_deadline["date"], today)}
    return {"course": record, "next_deadline": next_deadline, "mastery": _mastery_summary(course_id, user)}


def build_courses_page(user, semester: str | None = None, archived: bool = False, today: date | None = None) -> dict:
    """Compose course facts once; mastery averages are course-weighted over courses with evidence."""
    today = today or date.today()
    base_records = []
    warnings = []
    for course_id in _all_course_ids(user):
        try:
            base_records.append(_base_record(course_id, user))
        except (storage.CourseMetadataStorageError, storage.SyllabusStorageError, OSError, ValueError):
            warnings.append({"course_id": course_id, "detail": f"{course_id.upper()} could not be loaded."})

    terms = sorted({record["semester"] for record in base_records}, key=_semester_sort_key, reverse=True)
    requested = semester if semester and SEMESTER_RE.fullmatch(semester) else None
    selected = requested if requested else (current_semester(today) if current_semester(today) in terms else terms[0] if terms else current_semester(today))
    if selected not in terms:
        terms.append(selected)
        terms.sort(key=_semester_sort_key, reverse=True)

    selected_base = [record for record in base_records if record["semester"] == selected and record["archived"] is archived]
    active_ids = [record["id"] for record in base_records if record["semester"] == selected and not record["archived"] and not record["is_draft"]]
    try:
        all_deadlines = [
            event for event in calendar_events.upcoming_events(
                user, course_ids=active_ids, within_days=None, today=today,
            )
            if _in_semester(event.get("date"), selected)
        ]
    except (storage.SyllabusStorageError, storage.CustomEventsStorageError, DatabaseError):
        all_deadlines = []
        warnings.append({"course_id": None, "detail": "Deadline summaries are temporarily unavailable."})
    deadline_by_course = {}
    for event in all_deadlines:
        if event.get("completed"):
            continue
        deadline_by_course.setdefault(event.get("course_id"), event)

    courses = []
    for record in selected_base:
        try:
            material = material_summary(record["id"], user)
            mastery_data = _mastery_summary(record["id"], user)
        except (storage.NotesStorageError, storage.ReferencesStorageError, storage.QuizStorageError, DatabaseError):
            material = {"count": None, "needs_review": 0, "failed": 0}
            mastery_data = {"available": False, "score": None, "status": "unavailable", "label": "Unavailable"}
            warnings.append({"course_id": record["id"], "detail": f"Some details for {record['name']} could not be loaded."})
        next_deadline = deadline_by_course.get(record["id"])
        if next_deadline:
            next_deadline = {**next_deadline, "relative_label": _relative_label(next_deadline["date"], today)}
        courses.append({**record, "next_deadline": next_deadline, "materials": material, "mastery": mastery_data})

    available_scores = [course["mastery"]["score"] for course in courses if course["mastery"]["available"]]
    return {
        "semester": {"id": selected, "label": semester_label(selected)},
        "semesters": [{"id": term, "label": semester_label(term)} for term in terms],
        "archived": archived,
        "summary": {
            "active_courses": len([record for record in base_records if record["semester"] == selected and not record["archived"]]),
            "upcoming_deadlines": len({event["id"] for event in all_deadlines if not event.get("completed")}),
            "average_mastery": round(sum(available_scores) / len(available_scores)) if available_scores else None,
        },
        "courses": courses,
        "warnings": warnings,
        "palette": list(COURSE_COLORS),
    }
