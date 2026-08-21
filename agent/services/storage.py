"""
Flat-file JSON storage for course data.

Course data intentionally stays on disk as courses/<course_id>/*.json — this is
a personal-use project (one user), so a database layer would add complexity
without adding value. Django's own DB (sqlite) is only used for its own
auth/session/admin tables, never for course content.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
COURSES_DIR = BASE_DIR / "courses"

VALID_DATE_TYPES = {"exam", "assignment", "reading", "other"}

VALID_NOTE_SOURCES = {"notes", "slides"}

GRADING_CATEGORY_CHOICES = ["Homework", "Tests", "Quizzes", "Midterm", "Final", "Projects", "Other"]

# course_id becomes a path segment under COURSES_DIR — restrict it to a safe
# charset so values like "../../etc" or an absolute path can't escape courses/.
COURSE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# lecture_id becomes a filename under courses/<course_id>/notes/ — same
# defense as COURSE_ID_RE.
LECTURE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# reference_id becomes a filename under courses/<course_id>/references/ — same
# defense as LECTURE_ID_RE, and reuses it directly rather than duplicating the
# same safe charset under a new name.
REFERENCE_ID_RE = LECTURE_ID_RE


class SyllabusStorageError(Exception):
    """Raised when an existing syllabus.json on disk is corrupt/unreadable."""


class InvalidCourseIdError(ValueError):
    """Raised when course_id isn't a safe filesystem path segment."""


class InvalidLectureIdError(ValueError):
    """Raised when lecture_id isn't a safe filesystem path segment."""


class NotesStorageError(Exception):
    """Raised when an existing notes/<lecture_id>.json on disk is corrupt/unreadable."""


class InvalidReferenceIdError(ValueError):
    """Raised when reference_id isn't a safe filesystem path segment."""


class ReferencesStorageError(Exception):
    """Raised when an existing references/<reference_id>.json on disk is corrupt/unreadable."""


class TrustedDomainsStorageError(Exception):
    """Raised when an existing trusted_domains.json on disk is corrupt/unreadable."""


class QuizStorageError(Exception):
    """Raised when quiz_history.json or mastery_scores.json on disk is corrupt/unreadable."""


class GradesStorageError(Exception):
    """Raised when grades.json on disk is corrupt/unreadable."""


class CalendarSyncStorageError(Exception):
    """Raised when calendar_sync.json exists but is corrupt."""


class CustomEventsStorageError(Exception):
    """Raised when custom_events.json exists but is corrupt."""


class CourseNotFoundError(Exception):
    """Raised when no syllabus.json exists yet for the given course_id.

    Lives here (not in ask.py) so sessions.py can raise it too — a session
    can't be grounded in a course that doesn't exist — without ask.py and
    sessions.py importing each other.
    """


def _course_dir(course_id: str) -> Path:
    """Resolves courses/<course_id>, guarding against path traversal."""
    if not COURSE_ID_RE.fullmatch(course_id):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")
    resolved_courses_dir = COURSES_DIR.resolve()
    course_dir = (COURSES_DIR / course_id).resolve()
    if not course_dir.is_relative_to(resolved_courses_dir):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")
    return course_dir


def _lecture_path(course_id: str, lecture_id: str) -> Path:
    """Resolves courses/<course_id>/notes/<lecture_id>.json, guarding against
    path traversal via lecture_id the same way _course_dir does for course_id."""
    if not LECTURE_ID_RE.fullmatch(lecture_id):
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    notes_dir = _course_dir(course_id) / "notes"
    path = (notes_dir / f"{lecture_id}.json").resolve()
    if path.parent != notes_dir.resolve():
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    return path


def _reference_path(course_id: str, reference_id: str) -> Path:
    """Resolves courses/<course_id>/references/<reference_id>.json, guarding
    against path traversal via reference_id the same way _lecture_path does
    for lecture_id."""
    if not REFERENCE_ID_RE.fullmatch(reference_id):
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    references_dir = _course_dir(course_id) / "references"
    path = (references_dir / f"{reference_id}.json").resolve()
    if path.parent != references_dir.resolve():
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    return path


# --------------------------------------------------------------------------
# Validation — shared by the CLI command and the API view
# --------------------------------------------------------------------------

def validate_syllabus(data: dict) -> list:
    """Returns a list of error strings. Entries starting with 'WARNING' are
    non-blocking. An empty list means the data is valid."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("course_id", str)
    require("course_name", str)
    require("dates", list)
    require("grading", list)
    require("topics", list)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    for i, d in enumerate(data["dates"]):
        if not isinstance(d, dict):
            errors.append(f"dates[{i}] is not an object")
            continue
        if "date" not in d or "title" not in d or "type" not in d:
            errors.append(f"dates[{i}] missing one of date/title/type: {d}")
            continue
        try:
            datetime.strptime(d["date"], "%Y-%m-%d")
        except ValueError:
            errors.append(f"dates[{i}].date is not YYYY-MM-DD: {d['date']!r}")
        if d["type"] not in VALID_DATE_TYPES:
            errors.append(
                f"dates[{i}].type invalid: {d['type']!r} (must be one of {VALID_DATE_TYPES})"
            )

    for i, g in enumerate(data["grading"]):
        if not isinstance(g, dict) or "component" not in g or "weight_pct" not in g:
            errors.append(f"grading[{i}] malformed: {g}")
            continue
        if not isinstance(g["weight_pct"], (int, float)):
            errors.append(f"grading[{i}].weight_pct must be numeric: {g['weight_pct']!r}")

    for i, t in enumerate(data["topics"]):
        if not isinstance(t, str):
            errors.append(f"topics[{i}] is not a string: {t!r}")

    total_weight = sum(
        g.get("weight_pct", 0) for g in data["grading"]
        if isinstance(g.get("weight_pct"), (int, float))
    )
    if data["grading"] and abs(total_weight - 100) > 0.5:
        errors.append(
            f"WARNING: grading weights sum to {total_weight}, not 100 "
            f"(not blocking, but check the source)"
        )

    return errors


def validate_notes(data: dict) -> list:
    """Returns a list of error strings. Entries starting with 'WARNING' are
    non-blocking. An empty list means the data is valid."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("lecture_id", str)
    require("source", str)
    require("topics", list)
    require("chunks", list)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    if data["source"] not in VALID_NOTE_SOURCES:
        errors.append(f"'source' invalid: {data['source']!r} (must be one of {VALID_NOTE_SOURCES})")

    for i, t in enumerate(data["topics"]):
        if not isinstance(t, str):
            errors.append(f"topics[{i}] is not a string: {t!r}")

    if not data["chunks"]:
        errors.append("WARNING: chunks is empty — nothing to quiz or ground answers on for this lecture")

    seen_ids = set()
    for i, c in enumerate(data["chunks"]):
        if not isinstance(c, dict):
            errors.append(f"chunks[{i}] is not an object")
            continue
        if "id" not in c or "topic" not in c or "text" not in c:
            errors.append(f"chunks[{i}] missing one of id/topic/text: {c}")
            continue
        if c["id"] in seen_ids:
            errors.append(f"chunks[{i}].id is a duplicate: {c['id']!r}")
        seen_ids.add(c["id"])
        if not isinstance(c["text"], str) or not c["text"].strip():
            errors.append(f"chunks[{i}].text is empty — divider/heading-only chunks should be dropped, not written")

    return errors


def validate_reference(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is
    valid. Unlike notes/syllabus, there are no non-blocking WARNING entries
    here — a reference doc either has usable text or it doesn't."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("reference_id", str)
    require("title", str)
    require("source_filename", str)
    require("text", str)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    if not data["text"].strip():
        errors.append("'text' is empty — a reference with no extractable content shouldn't be written")

    return errors


def validate_trusted_domains(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is valid."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(
                f"field '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    require("course_id", str)
    require("domains", list)

    if errors:
        return errors

    for i, d in enumerate(data["domains"]):
        if not isinstance(d, str) or not d.strip():
            errors.append(f"domains[{i}] is not a non-empty string: {d!r}")

    return errors


def validate_grades(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is
    valid. No non-blocking WARNING entries here — a grade item either has a
    usable score or it doesn't."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(f"field '{key}' must be {expected_type.__name__}, got {type(data[key]).__name__}")

    require("course_id", str)
    require("items", list)
    if errors:
        return errors

    seen_ids = set()
    for i, item in enumerate(data["items"]):
        if not isinstance(item, dict):
            errors.append(f"items[{i}] is not an object")
            continue

        for key in ("id", "component", "title"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                errors.append(f"items[{i}].{key} must be a non-empty string")
        item_id = item.get("id")
        if item_id in seen_ids:
            errors.append(f"items[{i}].id is a duplicate: {item_id!r}")
        seen_ids.add(item_id)

        for key in ("score", "max_points"):
            value = item.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"items[{i}].{key} must be numeric")
            elif value < 0:
                errors.append(f"items[{i}].{key} must be non-negative")
        max_points = item.get("max_points")
        if isinstance(max_points, (int, float)) and not isinstance(max_points, bool) and max_points <= 0:
            errors.append(f"items[{i}].max_points must be greater than 0")

        if item.get("date"):
            try:
                datetime.strptime(item["date"], "%Y-%m-%d")
            except ValueError:
                errors.append(f"items[{i}].date is not YYYY-MM-DD: {item['date']!r}")

    return errors


def validate_grading_config(grading: list, grade_scale: dict = None) -> list:
    """Returns a list of error strings. Entries starting with 'WARNING' are
    non-blocking. An empty list means the data is valid."""
    errors = []
    if not isinstance(grading, list):
        return ["'grading' must be a list"]

    for i, g in enumerate(grading):
        if not isinstance(g, dict) or "component" not in g or "weight_pct" not in g:
            errors.append(f"grading[{i}] missing 'component' or 'weight_pct': {g}")
            continue
        if not isinstance(g["weight_pct"], (int, float)):
            errors.append(f"grading[{i}].weight_pct must be numeric: {g['weight_pct']!r}")
        if g["component"] not in GRADING_CATEGORY_CHOICES:
            errors.append(f"grading[{i}].component must be one of {GRADING_CATEGORY_CHOICES}: {g['component']!r}")

        total_items = g.get("total_items")
        if total_items is not None and (not isinstance(total_items, int) or isinstance(total_items, bool) or total_items < 1):
            errors.append(f"grading[{i}].total_items must be a positive integer: {total_items!r}")

        drop_lowest = g.get("drop_lowest")
        if drop_lowest is not None:
            if not isinstance(drop_lowest, int) or isinstance(drop_lowest, bool) or drop_lowest < 0:
                errors.append(f"grading[{i}].drop_lowest must be a non-negative integer: {drop_lowest!r}")
            elif isinstance(total_items, int) and drop_lowest >= total_items:
                errors.append(
                    f"WARNING: grading[{i}].drop_lowest ({drop_lowest}) >= total_items ({total_items}) "
                    f"— would drop every item in this category"
                )

    seen_components = set()
    duplicate_components = set()
    for g in grading:
        if isinstance(g, dict) and "component" in g:
            component = g["component"]
            if component in seen_components:
                duplicate_components.add(component)
            seen_components.add(component)
    for component in sorted(duplicate_components):
        errors.append(
            f"duplicate grading component {component!r}: current_grade()/grade_needed() "
            f"assume at most one entry per component name"
        )

    total_weight = sum(
        g.get("weight_pct", 0) for g in grading
        if isinstance(g, dict) and isinstance(g.get("weight_pct"), (int, float))
    )
    if grading and abs(total_weight - 100) > 0.5:
        errors.append(f"WARNING: grading weights sum to {total_weight}, not 100 (not blocking, but check the source)")

    if grade_scale is not None:
        if not isinstance(grade_scale, dict):
            errors.append("'grade_scale' must be an object")
        else:
            passing_pct = grade_scale.get("passing_pct")
            if passing_pct is not None and not isinstance(passing_pct, (int, float)):
                errors.append(f"grade_scale.passing_pct must be numeric: {passing_pct!r}")
            cutoffs = grade_scale.get("cutoffs", [])
            if not isinstance(cutoffs, list):
                errors.append("'grade_scale.cutoffs' must be a list")
            else:
                for i, c in enumerate(cutoffs):
                    if not isinstance(c, dict) or "letter" not in c or "min_pct" not in c:
                        errors.append(f"grade_scale.cutoffs[{i}] missing 'letter' or 'min_pct': {c}")
                    elif not isinstance(c["min_pct"], (int, float)):
                        errors.append(f"grade_scale.cutoffs[{i}].min_pct must be numeric: {c['min_pct']!r}")

    return errors


# --------------------------------------------------------------------------
# Read / write — plain sync I/O, wrapped with sync_to_async at the call site
# --------------------------------------------------------------------------

def read_syllabus(course_id: str):
    """Returns the parsed syllabus dict, or None if it doesn't exist."""
    path = _course_dir(course_id) / "syllabus.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SyllabusStorageError(f"existing syllabus.json for '{course_id}' is corrupt: {e}")


def read_notes(course_id: str) -> list:
    """Returns a list of parsed note dicts for every file under
    courses/<course_id>/notes/*.json, sorted by filename. Returns [] if
    notes/ doesn't exist yet — that's a normal state, not an error."""
    notes_dir = _course_dir(course_id) / "notes"
    if not notes_dir.exists():
        return []

    notes = []
    for path in sorted(notes_dir.glob("*.json")):
        try:
            notes.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise SyllabusStorageError(f"notes file '{path.name}' for '{course_id}' is corrupt: {e}")
    return notes


def read_lecture(course_id: str, lecture_id: str):
    """Returns the parsed notes/<lecture_id>.json dict, or None if it doesn't exist."""
    path = _lecture_path(course_id, lecture_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NotesStorageError(f"notes file '{lecture_id}' for '{course_id}' is corrupt: {e}")


def write_notes(course_id: str, lecture_id: str, data: dict, overwrite: bool = False) -> Path:
    """Writes notes/<lecture_id>.json. Raises FileExistsError if it already
    exists and overwrite=False — same plan-then-pause contract as
    write_syllabus (interactive prompt for CLI, explicit flag for API)."""
    notes_dir = _course_dir(course_id) / "notes"
    out_path = _lecture_path(course_id, lecture_id)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    notes_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def read_references(course_id: str) -> list:
    """Returns a list of parsed reference dicts for every file under
    courses/<course_id>/references/*.json, sorted by filename. Returns [] if
    references/ doesn't exist yet — that's a normal state, not an error."""
    references_dir = _course_dir(course_id) / "references"
    if not references_dir.exists():
        return []

    references = []
    for path in sorted(references_dir.glob("*.json")):
        try:
            references.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise ReferencesStorageError(f"reference file '{path.name}' for '{course_id}' is corrupt: {e}")
    return references


def read_reference(course_id: str, reference_id: str):
    """Returns the parsed references/<reference_id>.json dict, or None if it
    doesn't exist."""
    path = _reference_path(course_id, reference_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReferencesStorageError(f"reference file '{reference_id}' for '{course_id}' is corrupt: {e}")


def write_reference(course_id: str, reference_id: str, data: dict, overwrite: bool = False) -> Path:
    """Writes references/<reference_id>.json. Raises FileExistsError if it
    already exists and overwrite=False — same plan-then-pause contract as
    write_notes, even though in practice references.ingest_reference()
    generates reference_id fresh on every call and this path is rarely hit."""
    references_dir = _course_dir(course_id) / "references"
    out_path = _reference_path(course_id, reference_id)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    references_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def read_trusted_domains(course_id: str) -> list:
    """Returns the approved domains list, or [] if trusted_domains.json
    doesn't exist yet — no domains approved is the normal starting state,
    same "doesn't exist yet = normal state" convention as
    mastery_scores.json before any quiz attempt."""
    path = _course_dir(course_id) / "trusted_domains.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TrustedDomainsStorageError(f"trusted_domains.json for '{course_id}' is corrupt: {e}")

    domains = data.get("domains", [])
    errors = validate_trusted_domains({"course_id": course_id, "domains": domains})
    if errors:
        raise TrustedDomainsStorageError(
            f"trusted_domains.json for '{course_id}' failed validation: {errors}"
        )
    return domains


def write_trusted_domains(course_id: str, domains: list) -> Path:
    """Writes trusted_domains.json. Always overwrites — this is a
    user-controlled config list (the human approval step), not append-only
    data, so there's no destructive-conflict case to guard against the way
    write_syllabus/write_notes do."""
    out_dir = _course_dir(course_id)
    out_path = out_dir / "trusted_domains.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"course_id": course_id, "domains": domains}, indent=2), encoding="utf-8"
    )
    return out_path


def read_quiz_history(course_id: str) -> dict:
    """Returns the parsed quiz_history.json dict ({"course_id", "attempts"}).
    Returns an empty skeleton if it doesn't exist yet — a course with no quiz
    attempts yet is a normal state, not an error."""
    path = _course_dir(course_id) / "quiz_history.json"
    if not path.exists():
        return {"course_id": course_id, "attempts": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise QuizStorageError(f"quiz_history.json for '{course_id}' is corrupt: {e}")


def append_quiz_attempt(course_id: str, attempt: dict) -> Path:
    """Appends one attempt to quiz_history.json — an append-only event log,
    never rewritten or edited in place. mastery.py replays this from scratch
    to rebuild mastery_scores.json rather than updating scores incrementally."""
    history = read_quiz_history(course_id)
    history["attempts"].append(attempt)

    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "quiz_history.json"
    out_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return out_path


def read_calendar_sync(course_id: str) -> list:
    """Returns the list of deadlines already pushed to Google Calendar for
    this course, or [] if calendar_sync.json doesn't exist yet — no
    deadlines synced yet is the normal starting state, same "doesn't exist
    yet = normal state" convention as trusted_domains.json."""
    path = _course_dir(course_id) / "calendar_sync.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CalendarSyncStorageError(f"calendar_sync.json for '{course_id}' is corrupt: {e}")
    return data.get("synced", [])


def append_calendar_sync_record(course_id: str, record: dict) -> Path:
    """Appends one synced-deadline record to calendar_sync.json — an
    append-only log, mirroring append_quiz_attempt. OnTrack never un-syncs
    a Google Calendar event from its own side, so nothing ever rewrites or
    removes an existing entry."""
    synced = read_calendar_sync(course_id)
    synced.append(record)

    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "calendar_sync.json"
    out_path.write_text(json.dumps({"course_id": course_id, "synced": synced}, indent=2), encoding="utf-8")
    return out_path


def read_mastery_scores(course_id: str):
    """Returns the parsed mastery_scores.json dict, or None if it hasn't
    been built yet (call mastery.rebuild_scores() first)."""
    path = _course_dir(course_id) / "mastery_scores.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise QuizStorageError(f"mastery_scores.json for '{course_id}' is corrupt: {e}")


def write_mastery_scores(course_id: str, data: dict) -> Path:
    """Writes mastery_scores.json. Always overwrites — this is a derived,
    rebuildable view (per CLAUDE.md), never hand-edited, so unlike
    syllabus/notes writes there's no plan-then-pause confirmation here:
    rebuilding it is non-destructive by construction, since quiz_history.json
    (the source of truth) is untouched and a rebuild is always reproducible."""
    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "mastery_scores.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def read_grades(course_id: str) -> dict:
    """Returns the parsed grades.json dict ({"course_id", "items"}). Returns
    an empty skeleton if it doesn't exist yet — a course with no grades
    entered yet is a normal state, not an error, same convention as
    read_quiz_history."""
    path = _course_dir(course_id) / "grades.json"
    if not path.exists():
        return {"course_id": course_id, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GradesStorageError(f"grades.json for '{course_id}' is corrupt: {e}")


def write_grades(course_id: str, data: dict) -> Path:
    """Writes grades.json. Always overwrites — grade items are directly
    user-editable (add/edit/delete), not an append-only log like
    quiz_history.json, so there's no destructive-conflict case to guard
    against the way write_syllabus/write_notes do."""
    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "grades.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def read_custom_events() -> list:
    """Returns the list of manually-added deadlines/events, or [] if
    custom_events.json doesn't exist yet — no custom events yet is the
    normal starting state, same convention as trusted_domains.json. Unlike
    every other course JSON file, this one lives at the top level
    (COURSES_DIR itself), not under a specific course_id — a general event
    (course_id=None) has no single course to belong to."""
    path = COURSES_DIR / "custom_events.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CustomEventsStorageError(f"custom_events.json is corrupt: {e}")
    return data.get("events", [])


def write_custom_events(events: list) -> Path:
    """Writes custom_events.json. Always overwrites — directly
    user-editable (add/edit/delete), not append-only, same pattern as
    write_grades."""
    COURSES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = COURSES_DIR / "custom_events.json"
    out_path.write_text(json.dumps({"events": events}, indent=2), encoding="utf-8")
    return out_path


def write_syllabus(course_id: str, data: dict, overwrite: bool = False) -> Path:
    """Writes syllabus.json. Raises FileExistsError if it already exists and
    overwrite=False — callers are responsible for the plan-then-pause
    confirmation step (interactive prompt for CLI, explicit flag for API)."""
    out_dir = _course_dir(course_id)
    out_path = out_dir / "syllabus.json"

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def write_grading_config(course_id: str, grading: list, grade_scale: dict = None) -> Path:
    """Merges 'grading' and (if provided) 'grade_scale' into the course's
    existing syllabus.json. Raises CourseNotFoundError if no syllabus exists
    yet — grading categories can only be edited on a real course, not a
    draft. grade_scale is left untouched when omitted from the call, so
    editing categories doesn't require re-specifying the scale every time."""
    syllabus = read_syllabus(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus found for '{course_id}'")
    syllabus["grading"] = grading
    if grade_scale is not None:
        syllabus["grade_scale"] = grade_scale
    return write_syllabus(course_id, syllabus, overwrite=True)


class CourseAlreadyExistsError(Exception):
    """Raised when a course_id already has either course.json or syllabus.json."""


def write_course_draft(course_id: str, course_name: str) -> Path:
    """Writes course.json — a class that has a name but no syllabus yet.
    Raises InvalidCourseIdError (via _course_dir) for a bad slug, and
    CourseAlreadyExistsError if course_id already has course.json or
    syllabus.json — a draft can't collide with itself or a real course."""
    out_dir = _course_dir(course_id)
    course_path = out_dir / "course.json"
    syllabus_path = out_dir / "syllabus.json"

    if course_path.exists():
        raise CourseAlreadyExistsError(f"'{course_id}' already exists as a draft class")
    if syllabus_path.exists():
        raise CourseAlreadyExistsError(f"'{course_id}' already exists as a class")

    out_dir.mkdir(parents=True, exist_ok=True)
    course_path.write_text(
        json.dumps({
            "course_id": course_id,
            "course_name": course_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2),
        encoding="utf-8",
    )
    return course_path


def delete_course(course_id: str) -> None:
    """Deletes courses/<course_id>/ entirely — syllabus, notes, references,
    sessions, quiz_history, mastery_scores, everything. Raises
    CourseNotFoundError if course_id exists as neither a draft nor a real
    course. Irreversible; callers are responsible for confirming with the
    user before calling this (plan-then-pause per CLAUDE.md)."""
    course_dir = _course_dir(course_id)
    if not (course_dir / "course.json").exists() and not (course_dir / "syllabus.json").exists():
        raise CourseNotFoundError(f"no course '{course_id}' found")
    shutil.rmtree(course_dir)


def rename_course(course_id: str, course_name: str) -> None:
    """Updates course_name in place — course.json for a draft, syllabus.json
    for a real course, whichever exists. Raises CourseNotFoundError if
    neither exists."""
    course_dir = _course_dir(course_id)
    course_path = course_dir / "course.json"
    syllabus_path = course_dir / "syllabus.json"

    if course_path.exists():
        data = json.loads(course_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        course_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return

    if syllabus_path.exists():
        data = json.loads(syllabus_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        syllabus_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return

    raise CourseNotFoundError(f"no course '{course_id}' found")
