"""
Flat-file JSON storage for course data.

Course data intentionally stays on disk as courses/<course_id>/*.json — this is
still the source for extracted syllabus/notes content. Mutable tester/user
state can live in Django's SQLite database where transactions matter.
"""

import json
import re
import shutil
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
COURSES_DIR = BASE_DIR / "courses"

VALID_DATE_TYPES = {"hw", "project", "test_quiz", "class", "other"}
LEGACY_DATE_TYPE_MAP = {
    "assignment": "hw",
    "homework": "hw",
    "exam": "test_quiz",
    "test": "test_quiz",
    "quiz": "test_quiz",
    "reading": "class",
    "lesson": "class",
}


def normalize_date_type(value: str) -> str:
    normalized = str(value or "other").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = LEGACY_DATE_TYPE_MAP.get(normalized, normalized)
    return normalized if normalized in VALID_DATE_TYPES else "other"

VALID_NOTE_SOURCES = {"notes", "slides"}

GRADING_CATEGORY_CHOICES = [
    "Homework",
    "Tests",
    "Quizzes",
    "Midterm",
    "Final",
    "Projects",
    "Lab and Demo",
    "Final Project",
    "Class Participation",
    "Other",
]

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

# image_id becomes a filename under courses/<course_id>/images/<lecture_id>/ —
# same defense as LECTURE_ID_RE.
IMAGE_ID_RE = LECTURE_ID_RE

VALID_IMAGE_MATCH_METHODS = {"proximity"}


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


class InvalidImageIdError(ValueError):
    """Raised when image_id isn't a safe filesystem path segment."""


class ImageManifestStorageError(Exception):
    """Raised when images/<lecture_id>/manifest.json on disk is corrupt/unreadable,
    or a set of extracted manifest entries fails schema validation before a write."""


class TrustedDomainsStorageError(Exception):
    """Raised when an existing trusted_domains.json on disk is corrupt/unreadable."""


class QuizStorageError(Exception):
    """Raised when quiz_history.json or mastery_scores.json on disk is corrupt/unreadable."""


class CourseMetadataStorageError(Exception):
    """Raised when an existing user-managed course.json is corrupt."""


class FlashcardProgressStorageError(Exception):
    """Raised when flashcard progress cannot be read or written."""


class GradesStorageError(Exception):
    """Raised when grades.json on disk is corrupt/unreadable."""


class SavedSiteStorageError(Exception):
    """Raised when saved site metadata cannot be read or written."""


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


def _validate_course_id(course_id: str) -> None:
    """Raises InvalidCourseIdError if course_id isn't a safe slug. Shared by
    _course_dir (which also resolves a per-user filesystem path) and every
    DB-scoped function below that only ever needed course_id validated, not
    a directory resolved — they called _course_dir(course_id) purely for
    this check and discarded its return value."""
    if not COURSE_ID_RE.fullmatch(course_id):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")


def _course_dir(course_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>, guarding against path
    traversal. `user` is required — course content has no valid unowned
    state now that storage is per-user; a missing or anonymous user is a
    caller bug, not a runtime condition to handle gracefully (fails loudly
    per CLAUDE.md). Checking is_authenticated rather than `user is None`
    matters here: an AnonymousUser has pk=None, and pk=None would otherwise
    resolve to a shared courses/None/<course_id> bucket instead of failing."""
    if not getattr(user, "is_authenticated", False):
        raise ValueError("_course_dir requires an authenticated user — course content is always user-scoped")
    _validate_course_id(course_id)
    resolved_user_dir = (COURSES_DIR / str(user.pk)).resolve()
    course_dir = (COURSES_DIR / str(user.pk) / course_id).resolve()
    if not course_dir.is_relative_to(resolved_user_dir):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")
    return course_dir


def _lecture_path(course_id: str, lecture_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/notes/<lecture_id>.json,
    guarding against path traversal via lecture_id the same way _course_dir
    does for course_id."""
    if not LECTURE_ID_RE.fullmatch(lecture_id):
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    notes_dir = _course_dir(course_id, user) / "notes"
    path = (notes_dir / f"{lecture_id}.json").resolve()
    if path.parent != notes_dir.resolve():
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    return path


def _reference_path(course_id: str, reference_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/references/<reference_id>.json,
    guarding against path traversal via reference_id the same way
    _lecture_path does for lecture_id."""
    if not REFERENCE_ID_RE.fullmatch(reference_id):
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    references_dir = _course_dir(course_id, user) / "references"
    path = (references_dir / f"{reference_id}.json").resolve()
    if path.parent != references_dir.resolve():
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    return path


def _lecture_images_dir(course_id: str, lecture_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/images/<lecture_id>/, guarding
    against path traversal via lecture_id the same way _lecture_path does."""
    if not LECTURE_ID_RE.fullmatch(lecture_id):
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    images_dir = _course_dir(course_id, user) / "images"
    path = (images_dir / lecture_id).resolve()
    if path.parent != images_dir.resolve():
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    return path


def lecture_image_path(course_id: str, lecture_id: str, image_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/images/<lecture_id>/<image_id>.png,
    guarding against path traversal via image_id the same way _reference_path
    does for reference_id."""
    if not IMAGE_ID_RE.fullmatch(image_id):
        raise InvalidImageIdError(f"invalid image_id: {image_id!r}")
    lecture_dir = _lecture_images_dir(course_id, lecture_id, user)
    path = (lecture_dir / f"{image_id}.png").resolve()
    if path.parent != lecture_dir.resolve():
        raise InvalidImageIdError(f"invalid image_id: {image_id!r}")
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

        # "page" and "image_ids" are optional, additive fields — absent means
        # no figure-extraction pass has run for this lecture yet, which is a
        # normal state, not an error. extract_figures.py is what populates
        # them (proximity-matched page number, and the figures linked to it).
        if "page" in c and c["page"] is not None:
            page = c["page"]
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                errors.append(f"chunks[{i}].page must be a positive integer or null: {page!r}")
        if "image_ids" in c:
            image_ids = c["image_ids"]
            if not isinstance(image_ids, list) or not all(
                isinstance(image_id, str) and image_id.strip() for image_id in image_ids
            ):
                errors.append(f"chunks[{i}].image_ids must be a list of non-empty strings")

    return errors


def validate_image_manifest(entries: list) -> list:
    """Returns a list of error strings for an images/<lecture_id>/manifest.json
    entry list — see extract_figures.py for how entries are produced. An
    empty list means the data is valid. No non-blocking WARNING entries here,
    same as validate_reference: an entry either has a real, safely-named
    figure and a positive source page or it doesn't."""
    if not isinstance(entries, list):
        return ["manifest must be a list"]

    errors = []
    seen_ids = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{i}] is not an object")
            continue

        image_id = entry.get("image_id")
        if not isinstance(image_id, str) or not image_id.strip():
            errors.append(f"entries[{i}].image_id must be a non-empty string")
        elif not IMAGE_ID_RE.fullmatch(image_id):
            errors.append(f"entries[{i}].image_id is not a safe identifier: {image_id!r}")
        elif image_id in seen_ids:
            errors.append(f"entries[{i}].image_id is a duplicate: {image_id!r}")
        else:
            seen_ids.add(image_id)

        source_page = entry.get("source_page")
        if not isinstance(source_page, int) or isinstance(source_page, bool) or source_page < 1:
            errors.append(f"entries[{i}].source_page must be a positive integer: {source_page!r}")

        chunk_ids = entry.get("chunk_ids")
        if not isinstance(chunk_ids, list) or not all(
            isinstance(chunk_id, str) and chunk_id.strip() for chunk_id in chunk_ids
        ):
            errors.append(f"entries[{i}].chunk_ids must be a list of non-empty strings")

        if entry.get("match_method") not in VALID_IMAGE_MATCH_METHODS:
            errors.append(
                f"entries[{i}].match_method must be one of {VALID_IMAGE_MATCH_METHODS}: "
                f"{entry.get('match_method')!r}"
            )

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

def read_syllabus(course_id: str, user):
    """Returns the parsed syllabus dict, or None if it doesn't exist."""
    path = _course_dir(course_id, user) / "syllabus.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SyllabusStorageError(f"existing syllabus.json for '{course_id}' is corrupt: {e}")


def read_notes(course_id: str, user) -> list:
    """Returns a list of parsed note dicts for every file under
    courses/<course_id>/notes/*.json, sorted by filename. Returns [] if
    notes/ doesn't exist yet — that's a normal state, not an error."""
    notes_dir = _course_dir(course_id, user) / "notes"
    if not notes_dir.exists():
        return []

    notes = []
    for path in sorted(notes_dir.glob("*.json")):
        try:
            notes.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise SyllabusStorageError(f"notes file '{path.name}' for '{course_id}' is corrupt: {e}")
    return notes


def read_lecture(course_id: str, lecture_id: str, user):
    """Returns the parsed notes/<lecture_id>.json dict, or None if it doesn't exist."""
    path = _lecture_path(course_id, lecture_id, user)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NotesStorageError(f"notes file '{lecture_id}' for '{course_id}' is corrupt: {e}")


def write_notes(course_id: str, lecture_id: str, data: dict, user, overwrite: bool = False) -> Path:
    """Writes notes/<lecture_id>.json. Raises FileExistsError if it already
    exists and overwrite=False — same plan-then-pause contract as
    write_syllabus (interactive prompt for CLI, explicit flag for API)."""
    notes_dir = _course_dir(course_id, user) / "notes"
    out_path = _lecture_path(course_id, lecture_id, user)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    notes_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def delete_lecture(course_id: str, lecture_id: str, user) -> None:
    """Delete one owned validated lecture file, if present."""
    path = _lecture_path(course_id, lecture_id, user)
    if path.exists():
        path.unlink()


def read_references(course_id: str, user) -> list:
    """Returns a list of parsed reference dicts for every file under
    courses/<course_id>/references/*.json, sorted by filename. Returns [] if
    references/ doesn't exist yet — that's a normal state, not an error."""
    references_dir = _course_dir(course_id, user) / "references"
    if not references_dir.exists():
        return []

    references = []
    for path in sorted(references_dir.glob("*.json")):
        try:
            references.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise ReferencesStorageError(f"reference file '{path.name}' for '{course_id}' is corrupt: {e}")
    return references


def read_reference(course_id: str, reference_id: str, user):
    """Returns the parsed references/<reference_id>.json dict, or None if it
    doesn't exist."""
    path = _reference_path(course_id, reference_id, user)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReferencesStorageError(f"reference file '{reference_id}' for '{course_id}' is corrupt: {e}")


def write_reference(course_id: str, reference_id: str, data: dict, user, overwrite: bool = False) -> Path:
    """Writes references/<reference_id>.json. Raises FileExistsError if it
    already exists and overwrite=False — same plan-then-pause contract as
    write_notes, even though in practice references.ingest_reference()
    generates reference_id fresh on every call and this path is rarely hit."""
    references_dir = _course_dir(course_id, user) / "references"
    out_path = _reference_path(course_id, reference_id, user)

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    references_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def delete_reference(course_id: str, reference_id: str, user) -> None:
    """Delete one owned validated reference file, if present."""
    path = _reference_path(course_id, reference_id, user)
    if path.exists():
        path.unlink()


def read_image_manifest(course_id: str, lecture_id: str, user):
    """Returns the parsed images/<lecture_id>/manifest.json list, or None if
    this lecture's figures have never been extracted — a normal state, same
    "doesn't exist yet" convention as read_syllabus."""
    path = _lecture_images_dir(course_id, lecture_id, user) / "manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ImageManifestStorageError(f"manifest.json for '{course_id}/{lecture_id}' is corrupt: {e}")
    errors = validate_image_manifest(data)
    if errors:
        raise ImageManifestStorageError(
            f"manifest.json for '{course_id}/{lecture_id}' failed validation: {errors}"
        )
    return data


def write_image_manifest(course_id: str, lecture_id: str, entries: list, user, overwrite: bool = False) -> Path:
    """Writes images/<lecture_id>/manifest.json. Raises ImageManifestStorageError
    if entries fail schema validation — callers must validate before writing,
    never persist unvalidated extracted data. Raises FileExistsError if the
    manifest already exists and overwrite=False — same plan-then-pause
    contract as write_notes/write_syllabus."""
    errors = validate_image_manifest(entries)
    if errors:
        raise ImageManifestStorageError(f"manifest entries failed validation: {errors}")

    lecture_dir = _lecture_images_dir(course_id, lecture_id, user)
    out_path = lecture_dir / "manifest.json"
    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    lecture_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return out_path


def write_lecture_image(course_id: str, lecture_id: str, image_id: str, png_bytes: bytes, user, overwrite: bool = False) -> Path:
    """Writes one extracted figure PNG under images/<lecture_id>/<image_id>.png.
    Raises FileExistsError if it already exists and overwrite=False."""
    out_path = lecture_image_path(course_id, lecture_id, image_id, user)
    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    return out_path


def delete_lecture_images(course_id: str, lecture_id: str, user) -> None:
    """Deletes images/<lecture_id>/ entirely (manifest + every PNG), if
    present — used to clean-slate re-extract a lecture's figures rather than
    trying to reconcile individual file adds/removes."""
    lecture_dir = _lecture_images_dir(course_id, lecture_id, user)
    if lecture_dir.exists():
        shutil.rmtree(lecture_dir)


def read_trusted_domains(course_id: str, user) -> list:
    """Returns the approved domains list, or [] if trusted_domains.json
    doesn't exist yet — no domains approved is the normal starting state,
    same "doesn't exist yet = normal state" convention as
    mastery_scores.json before any quiz attempt."""
    path = _course_dir(course_id, user) / "trusted_domains.json"
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


def write_trusted_domains(course_id: str, domains: list, user) -> Path:
    """Writes trusted_domains.json. Always overwrites — this is a
    user-controlled config list (the human approval step), not append-only
    data, so there's no destructive-conflict case to guard against the way
    write_syllabus/write_notes do."""
    out_dir = _course_dir(course_id, user)
    out_path = out_dir / "trusted_domains.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"course_id": course_id, "domains": domains}, indent=2), encoding="utf-8"
    )
    return out_path


def read_quiz_history(course_id: str, user=None) -> dict:
    """Returns quiz attempts from SQLite in the historical JSON shape."""
    _validate_course_id(course_id)
    from agent.models import QuizAttempt

    attempts = []
    records = _scope_user_queryset(QuizAttempt.objects.filter(course_id=course_id), user).order_by("timestamp", "id")
    for record in records:
        attempts.append({
            "lecture_id": record.lecture_id,
            "chunk_id": record.chunk_id,
            "topic": record.topic,
            "question": record.question,
            "correct_answer": record.correct_answer,
            "user_answer": record.user_answer,
            "correct": record.correct,
            "timestamp": record.timestamp,
        })
    return {"course_id": course_id, "attempts": attempts}


def append_quiz_attempt(course_id: str, attempt: dict, user=None) -> None:
    """Appends one quiz attempt to SQLite."""
    _validate_course_id(course_id)
    from agent.models import QuizAttempt

    QuizAttempt.objects.create(
        course_id=course_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        lecture_id=attempt.get("lecture_id", ""),
        chunk_id=attempt.get("chunk_id", ""),
        topic=attempt.get("topic", ""),
        question=attempt.get("question", ""),
        correct_answer=attempt.get("correct_answer", ""),
        user_answer=attempt.get("user_answer", ""),
        correct=bool(attempt.get("correct")),
        timestamp=attempt.get("timestamp", datetime.now(timezone.utc).isoformat()),
    )


def flashcard_key(term: str, definition: str) -> str:
    """Stable key for generated flashcards so progress survives regeneration
    when the same term/definition pair appears again."""
    normalized = " ".join(f"{term or ''}\n{definition or ''}".lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _flashcard_user_filter(user=None) -> dict:
    if getattr(user, "is_authenticated", False):
        return {"user": user}
    return {"user__isnull": True}


def _scope_user_queryset(queryset, user=None, include_legacy: bool = False):
    if not getattr(user, "is_authenticated", False):
        # An anonymous caller must only ever see anonymous (user=NULL) rows —
        # returning the queryset unfiltered here would leak every
        # authenticated user's data (quiz history, grades, saved sites, etc.)
        # to any unauthenticated request.
        return queryset.filter(user__isnull=True)
    return queryset.filter(user=user)


def _flashcard_record_to_dict(record) -> dict:
    data = {
        "term": record.term,
        "definition": record.definition,
        "starred": bool(record.starred),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    if record.status in {"mastered", "in_progress"}:
        data["status"] = record.status
    return data


def read_flashcard_progress(course_id: str, user=None) -> dict:
    """Returns saved flashcard progress from SQLite.

    Missing rows mean no saved progress yet, which is a normal state.
    """
    _validate_course_id(course_id)
    from agent.models import FlashcardProgress

    records = FlashcardProgress.objects.filter(course_id=course_id, **_flashcard_user_filter(user))
    return {
        "course_id": course_id,
        "cards": {record.card_key: _flashcard_record_to_dict(record) for record in records},
    }


def write_flashcard_progress(course_id: str, data: dict, user=None) -> None:
    """Replaces saved flashcard progress for a course/user.

    Kept for compatibility with tests and callers that need a bulk replace.
    """
    _validate_course_id(course_id)
    cards = data.get("cards", {})
    if not isinstance(cards, dict):
        raise FlashcardProgressStorageError("flashcard progress has invalid cards shape")

    from django.db import transaction
    from agent.models import FlashcardProgress

    user_value = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        FlashcardProgress.objects.filter(course_id=course_id, **_flashcard_user_filter(user)).delete()
        for key, record in cards.items():
            if not isinstance(record, dict):
                continue
            status = record.get("status")
            if status not in {"mastered", "in_progress"}:
                status = None
            starred = bool(record.get("starred", False))
            if status is None and not starred:
                continue
            FlashcardProgress.objects.create(
                course_id=course_id,
                user=user_value,
                card_key=str(key),
                term=record.get("term", ""),
                definition=record.get("definition", ""),
                status=status,
                starred=starred,
            )


def annotate_flashcards_with_progress(course_id: str, flashcards: list, user=None) -> list:
    progress = read_flashcard_progress(course_id, user=user)
    saved = progress.get("cards", {})
    annotated = []
    for card in flashcards:
        key = card.get("key") or flashcard_key(card.get("term", ""), card.get("definition", ""))
        record = saved.get(key) or {}
        annotated_card = dict(card)
        annotated_card["key"] = key
        annotated_card["status"] = record.get("status") if record.get("status") in {"mastered", "in_progress"} else "not_started"
        annotated_card["starred"] = bool(record.get("starred", False))
        annotated.append(annotated_card)
    return annotated


def read_saved_flashcards(course_id: str, user=None) -> list:
    """Returns previously generated flashcards for a course/user."""
    _validate_course_id(course_id)
    from agent.models import FlashcardProgress

    records = (
        FlashcardProgress.objects
        .filter(course_id=course_id, **_flashcard_user_filter(user))
        .exclude(term="")
        .exclude(definition="")
        .order_by("id")
    )
    flashcards = []
    for record in records:
        flashcards.append({
            "key": record.card_key,
            "term": record.term,
            "definition": record.definition,
            "source": "saved",
            "url": None,
            "status": record.status if record.status in {"mastered", "in_progress"} else "not_started",
            "starred": bool(record.starred),
        })
    return flashcards


FLASHCARD_CACHE_LIMIT = 200


def remember_generated_flashcards(course_id: str, flashcards: list, user=None, topic: str = None) -> None:
    """Stores generated card text so course Q&A can reference the full deck,
    even before the learner marks progress or stars cards.

    `topic` (the chunk topic every card in one generation batch shares) is
    recorded so mastery.py can fold flashcard ratings into that topic's
    score. Omitting it (e.g. a caller unrelated to generation) leaves an
    existing card's topic untouched rather than blanking it out."""
    _validate_course_id(course_id)
    from agent.models import FlashcardProgress

    user_value = user if getattr(user, "is_authenticated", False) else None
    for card in flashcards:
        if not isinstance(card, dict):
            continue
        term = card.get("term", "")
        definition = card.get("definition", "")
        key = card.get("key") or flashcard_key(term, definition)
        lookup = {"course_id": course_id, "card_key": key, **_flashcard_user_filter(user)}
        existing = FlashcardProgress.objects.filter(**lookup).first()
        if existing:
            existing.user = user_value
            existing.term = term
            existing.definition = definition
            update_fields = ["user", "term", "definition", "updated_at"]
            if topic is not None:
                existing.topic = topic
                update_fields.append("topic")
            existing.save(update_fields=update_fields)
        else:
            FlashcardProgress.objects.create(
                course_id=course_id,
                user=user_value,
                card_key=key,
                term=term,
                definition=definition,
                topic=topic or "",
                status=None,
                starred=False,
            )

    _trim_untouched_flashcard_cache(course_id, user)


def _trim_untouched_flashcard_cache(course_id: str, user=None) -> None:
    """Evicts the oldest never-studied, unstarred cached cards once a
    course/user's cache exceeds FLASHCARD_CACHE_LIMIT rows. Cards the learner
    has actually starred or made progress on are never evicted here."""
    from agent.models import FlashcardProgress

    lookup = {"course_id": course_id, "status__isnull": True, "starred": False, **_flashcard_user_filter(user)}
    stale_ids = list(
        FlashcardProgress.objects.filter(**lookup)
        .order_by("-updated_at")
        .values_list("id", flat=True)[FLASHCARD_CACHE_LIMIT:]
    )
    if stale_ids:
        FlashcardProgress.objects.filter(id__in=stale_ids).delete()


def update_flashcard_progress(course_id: str, card: dict, user=None) -> dict:
    """Updates one flashcard progress record.

    status=not_started clears progress but keeps card text cached so decks can
    be reloaded without another model call.
    """
    status = card.get("status")
    if status not in {"mastered", "in_progress", "not_started"}:
        raise ValueError("status must be mastered, in_progress, or not_started")
    _validate_course_id(course_id)
    key = card.get("key") or flashcard_key(card.get("term", ""), card.get("definition", ""))
    starred = bool(card.get("starred", False))

    from agent.models import FlashcardProgress

    lookup = {"course_id": course_id, "card_key": key, **_flashcard_user_filter(user)}
    user_value = user if getattr(user, "is_authenticated", False) else None
    existing = FlashcardProgress.objects.filter(**lookup).first()
    term = card.get("term") or (existing.term if existing else "")
    definition = card.get("definition") or (existing.definition if existing else "")

    if status == "not_started":
        FlashcardProgress.objects.update_or_create(
            **lookup,
            defaults={
                "user": user_value,
                "term": term,
                "definition": definition,
                "status": None,
                "starred": starred,
            },
        )
    else:
        FlashcardProgress.objects.update_or_create(
            **lookup,
            defaults={
                "user": user_value,
                "term": term,
                "definition": definition,
                "status": status,
                "starred": starred,
            },
        )

    record = FlashcardProgress.objects.filter(**lookup).first()
    return {
        "key": key,
        "status": record.status if record and record.status in {"mastered", "in_progress"} else "not_started",
        "starred": bool(record.starred) if record else False,
    }


def _flashcard_review_state(record) -> dict:
    return {
        "key": record.card_key,
        "term": record.term,
        "definition": record.definition,
        "topic": record.topic,
        "suspended": bool(record.suspended),
        "rating": record.rating,
        "interval_days": record.interval_days,
        "review_count": record.review_count,
        "last_reviewed": record.last_reviewed.isoformat() if record.last_reviewed else None,
        "next_review": record.next_review.isoformat() if record.next_review else None,
    }


class FlashcardSuspendedError(Exception):
    """Raised when reviewing a card the learner has suspended. Reviewing
    would silently reactivate it into the due queue, which the learner did
    not ask for — call unsuspend_flashcard first."""


def review_flashcard(course_id: str, key: str, rating: str, user=None, now=None) -> dict:
    """Records a spaced-repetition review for one flashcard and returns its
    updated scheduling state. Creating the row on first review (rather than
    requiring it pre-exist) is expected — every card is reviewable the first
    time it's shown, before any progress row exists for it."""
    from . import spaced_repetition
    from agent.models import FlashcardProgress

    if rating not in spaced_repetition.RATINGS:
        raise ValueError(f"rating must be one of {spaced_repetition.RATINGS}, got {rating!r}")
    _validate_course_id(course_id)

    lookup = {"course_id": course_id, "card_key": key, **_flashcard_user_filter(user)}
    user_value = user if getattr(user, "is_authenticated", False) else None
    existing = FlashcardProgress.objects.filter(**lookup).first()
    if existing and existing.suspended:
        raise FlashcardSuspendedError(f"card '{key}' is suspended; unsuspend it before reviewing")

    schedule = spaced_repetition.schedule_review(rating, existing.interval_days if existing else 0, now=now)
    record, _ = FlashcardProgress.objects.update_or_create(
        **lookup,
        defaults={
            "user": user_value,
            "term": existing.term if existing else "",
            "definition": existing.definition if existing else "",
            "status": existing.status if existing else None,
            "starred": existing.starred if existing else False,
            "rating": rating,
            "interval_days": schedule["interval_days"],
            "review_count": (existing.review_count if existing else 0) + 1,
            "last_reviewed": schedule["reviewed_at"],
            "next_review": schedule["next_review"],
        },
    )
    return _flashcard_review_state(record)


def suspend_flashcard(course_id: str, key: str, suspended: bool = True, user=None) -> dict:
    """Suspends (or unsuspends) a card so it stops (or resumes) appearing in
    the due queue. Never silently flips this — only an explicit call here
    changes it; regeneration and progress updates leave it untouched."""
    from agent.models import FlashcardProgress

    _validate_course_id(course_id)
    lookup = {"course_id": course_id, "card_key": key, **_flashcard_user_filter(user)}
    user_value = user if getattr(user, "is_authenticated", False) else None
    existing = FlashcardProgress.objects.filter(**lookup).first()
    record, _ = FlashcardProgress.objects.update_or_create(
        **lookup,
        defaults={
            "user": user_value,
            "term": existing.term if existing else "",
            "definition": existing.definition if existing else "",
            "suspended": bool(suspended),
        },
    )
    return _flashcard_review_state(record)


def due_flashcards(course_id: str, user=None, limit: int = None, now=None) -> list:
    """Cards due for review: never reviewed, or due at/before `now`. Excludes
    suspended cards and cache rows with no card text (nothing to show)."""
    from django.db.models import F, Q
    from agent.models import FlashcardProgress

    _validate_course_id(course_id)
    now = now or datetime.now(timezone.utc)
    records = (
        FlashcardProgress.objects
        .filter(course_id=course_id, suspended=False, **_flashcard_user_filter(user))
        .exclude(term="")
        .filter(Q(next_review__isnull=True) | Q(next_review__lte=now))
        .order_by(F("next_review").asc(nulls_first=True), "id")
    )
    if limit:
        records = records[:limit]
    return [_flashcard_review_state(record) for record in records]


FLASHCARD_RATING_VALUE = {"again": 0.0, "hard": 0.35, "good": 0.7, "easy": 1.0}


def flashcard_topic_stats(course_id: str, user=None) -> dict:
    """Per-topic flashcard-review signal for mastery.py: how many cards in
    that topic have been rated at least once, their average rating (mapped
    to 0..1 via FLASHCARD_RATING_VALUE), and the most recent review. Cards
    with no topic (generated before the topic field existed) or never
    reviewed (rating is null) are excluded — they carry no usable signal."""
    _validate_course_id(course_id)
    from agent.models import FlashcardProgress

    records = (
        FlashcardProgress.objects
        .filter(course_id=course_id, **_flashcard_user_filter(user))
        .exclude(topic="")
        .exclude(rating__isnull=True)
    )
    stats = {}
    for record in records:
        bucket = stats.setdefault(record.topic, {"ratings": [], "last_reviewed": None})
        bucket["ratings"].append(FLASHCARD_RATING_VALUE.get(record.rating, 0.5))
        if record.last_reviewed and (bucket["last_reviewed"] is None or record.last_reviewed > bucket["last_reviewed"]):
            bucket["last_reviewed"] = record.last_reviewed

    return {
        topic: {
            "count": len(bucket["ratings"]),
            "avg_rating": sum(bucket["ratings"]) / len(bucket["ratings"]),
            "last_reviewed": bucket["last_reviewed"].isoformat() if bucket["last_reviewed"] else None,
        }
        for topic, bucket in stats.items()
    }


def reset_flashcard_progress(course_id: str, keys: list, user=None) -> None:
    _validate_course_id(course_id)
    from agent.models import FlashcardProgress

    key_values = [str(key) for key in keys]
    records = FlashcardProgress.objects.filter(
        course_id=course_id,
        card_key__in=key_values,
        **_flashcard_user_filter(user),
    )
    records.update(status=None)


def read_calendar_sync(course_id: str, user=None) -> list:
    _validate_course_id(course_id)
    from agent.models import CalendarSyncRecord

    records = _scope_user_queryset(CalendarSyncRecord.objects.filter(course_id=course_id), user).order_by("id")
    return [
        {
            "date": r.date,
            "title": r.title,
            "type": r.type,
            "google_event_id": r.google_event_id,
            "synced_at": r.synced_at,
        }
        for r in records
    ]


def append_calendar_sync_record(course_id: str, record: dict, user=None) -> None:
    _validate_course_id(course_id)
    from agent.models import CalendarSyncRecord

    CalendarSyncRecord.objects.create(
        course_id=course_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        date=record.get("date", ""),
        title=record.get("title", ""),
        type=record.get("type", ""),
        google_event_id=record.get("google_event_id", ""),
        synced_at=record.get("synced_at", datetime.now(timezone.utc).isoformat()),
    )


def read_mastery_scores(course_id: str, user=None):
    _validate_course_id(course_id)
    from agent.models import MasteryScore

    records = list(_scope_user_queryset(MasteryScore.objects.filter(course_id=course_id), user).order_by("score", "topic"))
    if not records:
        return None
    rebuilt_at = records[0].rebuilt_at
    return {
        "course_id": course_id,
        "rebuilt_at": rebuilt_at,
        "scores": [
            {
                "topic": r.topic,
                "score": r.score,
                "attempts": r.attempts,
                "last_seen": r.last_seen,
                "status": r.status,
                "reason": r.reason,
            }
            for r in records
        ],
    }


def write_mastery_scores(course_id: str, data: dict, user=None) -> None:
    _validate_course_id(course_id)
    scores = data.get("scores", [])
    if not isinstance(scores, list):
        raise QuizStorageError("mastery scores has invalid scores shape")

    from django.db import transaction
    from agent.models import MasteryScore

    user_value = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        MasteryScore.objects.filter(course_id=course_id, **_flashcard_user_filter(user)).delete()
        for score in scores:
            MasteryScore.objects.create(
                course_id=course_id,
                user=user_value,
                topic=score.get("topic", ""),
                score=float(score.get("score", 0)),
                attempts=int(score.get("attempts", 0)),
                last_seen=score.get("last_seen"),
                status=score.get("status", ""),
                reason=score.get("reason", ""),
                rebuilt_at=data.get("rebuilt_at", datetime.now(timezone.utc).isoformat()),
            )


def dismiss_recommendation(course_id: str, topic: str, user=None, dismissed_until=None) -> None:
    """Hides one (course, topic) study recommendation. `dismissed_until=None`
    means "until explicitly cleared"; a datetime means "deferred until then".
    Never touches quiz/flashcard/deadline data — recommendations.py always
    recomputes those from scratch, so clearing this table can only ever
    bring a hidden recommendation back, never lose anything academic."""
    _validate_course_id(course_id)
    from agent.models import RecommendationDismissal

    user_value = user if getattr(user, "is_authenticated", False) else None
    RecommendationDismissal.objects.update_or_create(
        course_id=course_id, topic=topic, **_flashcard_user_filter(user),
        defaults={"user": user_value, "dismissed_until": dismissed_until},
    )


def read_recommendation_dismissals(course_id: str, user=None) -> dict:
    _validate_course_id(course_id)
    from agent.models import RecommendationDismissal

    records = RecommendationDismissal.objects.filter(course_id=course_id, **_flashcard_user_filter(user))
    return {r.topic: r.dismissed_until for r in records}


def read_grades(course_id: str, user=None) -> dict:
    _validate_course_id(course_id)
    from agent.models import GradeItem

    records = _scope_user_queryset(GradeItem.objects.filter(course_id=course_id), user).order_by("created_at", "id")
    return {
        "course_id": course_id,
        "items": [
            {
                "id": r.item_id,
                "component": r.component,
                "title": r.title,
                "score": r.score,
                "max_points": r.max_points,
                "date": r.date,
            }
            for r in records
        ],
    }


def write_grades(course_id: str, data: dict, user=None) -> None:
    _validate_course_id(course_id)
    items = data.get("items", [])
    if not isinstance(items, list):
        raise GradesStorageError("grades has invalid items shape")

    from django.db import transaction
    from agent.models import GradeItem

    user_value = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        GradeItem.objects.filter(course_id=course_id, **_flashcard_user_filter(user)).delete()
        for item in items:
            GradeItem.objects.create(
                course_id=course_id,
                user=user_value,
                item_id=item.get("id", ""),
                component=item.get("component", ""),
                title=item.get("title", ""),
                score=float(item.get("score", 0)),
                max_points=float(item.get("max_points", 0)),
                date=item.get("date"),
            )


def validate_saved_site_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        raise ValueError("url is required")
    if len(normalized) > 2048:
        raise ValueError("url is too long")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute http(s) URL")
    return normalized


def _saved_site_to_dict(site) -> dict:
    return {
        "id": site.id,
        "course_id": site.course_id,
        "title": site.title,
        "url": site.url,
        "created_at": site.created_at.isoformat() if site.created_at else None,
        "updated_at": site.updated_at.isoformat() if site.updated_at else None,
    }


def list_saved_sites(course_id: str, user=None) -> list:
    _validate_course_id(course_id)
    from agent.models import SavedSite

    records = _scope_user_queryset(SavedSite.objects.filter(course_id=course_id), user).order_by("title", "id")
    return [_saved_site_to_dict(site) for site in records]


def save_site(course_id: str, url: str, title: str = None, user=None) -> dict:
    _validate_course_id(course_id)
    normalized_url = validate_saved_site_url(url)
    title = str(title or "").strip()
    if not title:
        parsed = urlparse(normalized_url)
        title = parsed.netloc or normalized_url
    title = title[:255]

    from agent.models import SavedSite

    user_value = user if getattr(user, "is_authenticated", False) else None
    site, _created = SavedSite.objects.update_or_create(
        course_id=course_id,
        user=user_value,
        url=normalized_url,
        defaults={"title": title},
    )
    return _saved_site_to_dict(site)


def _custom_event_to_dict(event) -> dict:
    return {
        "id": event.event_id,
        "course_id": event.course_id,
        "date": event.date,
        "time": event.time,
        "end_time": event.end_time,
        "title": event.title,
        "type": normalize_date_type(event.type),
        "location": event.location,
        "notes": event.notes,
        "source": event.source,
        "estimated_effort_minutes": event.estimated_effort_minutes,
        "source_material_id": str(event.source_material_id) if event.source_material_id else None,
        "replaces_syllabus_key": event.replaces_syllabus_key,
        "completed": event.completed,
        "synced": event.synced,
        "google_event_id": event.google_event_id,
        "synced_at": event.synced_at,
        "created_at": event.created_at,
    }


def read_custom_events(user=None) -> list:
    from agent.models import CustomEvent

    events = _scope_user_queryset(CustomEvent.objects.all(), user).order_by("date", "time", "created_at", "id")
    return [_custom_event_to_dict(event) for event in events]


def write_custom_events(events: list, user=None) -> None:
    if not isinstance(events, list):
        raise CustomEventsStorageError("custom events has invalid events shape")

    from django.db import transaction
    from agent.models import CustomEvent

    user_value = user if getattr(user, "is_authenticated", False) else None
    with transaction.atomic():
        delete_queryset = CustomEvent.objects.all()
        if getattr(user, "is_authenticated", False):
            delete_queryset = _scope_user_queryset(delete_queryset, user, include_legacy=False)
        else:
            delete_queryset = delete_queryset.filter(user__isnull=True)
        delete_queryset.delete()
        for event in events:
            CustomEvent.objects.create(
                event_id=event.get("id", ""),
                user=user_value,
                course_id=event.get("course_id"),
                date=event.get("date", ""),
                time=event.get("time"),
                end_time=event.get("end_time"),
                title=event.get("title", ""),
                type=normalize_date_type(event.get("type", "")),
                location=event.get("location", ""),
                notes=event.get("notes", ""),
                source=event.get("source") or "manual",
                estimated_effort_minutes=event.get("estimated_effort_minutes"),
                source_material_id=event.get("source_material_id"),
                replaces_syllabus_key=event.get("replaces_syllabus_key") or None,
                completed=bool(event.get("completed", False)),
                synced=bool(event.get("synced", False)),
                google_event_id=event.get("google_event_id"),
                synced_at=event.get("synced_at"),
                created_at=event.get("created_at", datetime.now(timezone.utc).isoformat()),
            )


def claim_custom_event(event_id: str, user) -> None:
    """Legacy anonymous events are never claimable by an authenticated user."""
    return


def write_syllabus(course_id: str, data: dict, user, overwrite: bool = False) -> Path:
    """Writes syllabus.json. Raises FileExistsError if it already exists and
    overwrite=False — callers are responsible for the plan-then-pause
    confirmation step (interactive prompt for CLI, explicit flag for API)."""
    out_dir = _course_dir(course_id, user)
    out_path = out_dir / "syllabus.json"

    if out_path.exists() and not overwrite:
        raise FileExistsError(str(out_path))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def delete_syllabus_preserving_course(course_id: str, user) -> None:
    """Remove trusted syllabus content while retaining the user's course shell."""
    course_dir = _course_dir(course_id, user)
    syllabus_path = course_dir / "syllabus.json"
    syllabus = read_syllabus(course_id, user)
    if syllabus is None:
        return
    course_path = course_dir / "course.json"
    course_path.write_text(
        json.dumps(
            {
                "course_id": course_id,
                "course_name": syllabus.get("course_name") or course_id.upper(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    syllabus_path.unlink()


def write_grading_config(course_id: str, grading: list, user, grade_scale: dict = None) -> Path:
    """Merges 'grading' and (if provided) 'grade_scale' into the course's
    existing syllabus.json. Raises CourseNotFoundError if no syllabus exists
    yet — grading categories can only be edited on a real course, not a
    draft. grade_scale is left untouched when omitted from the call, so
    editing categories doesn't require re-specifying the scale every time."""
    syllabus = read_syllabus(course_id, user)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus found for '{course_id}'")
    syllabus["grading"] = grading
    if grade_scale is not None:
        syllabus["grade_scale"] = grade_scale
    return write_syllabus(course_id, syllabus, user, overwrite=True)


class CourseAlreadyExistsError(Exception):
    """Raised when a course_id already has either course.json or syllabus.json."""


def write_course_draft(course_id: str, course_name: str, user, **metadata) -> Path:
    """Writes course.json — a class that has a name but no syllabus yet.
    Raises InvalidCourseIdError (via _course_dir) for a bad slug, and
    CourseAlreadyExistsError if course_id already has course.json or
    syllabus.json for this user — a draft can't collide with itself or a
    real course belonging to the same user."""
    out_dir = _course_dir(course_id, user)
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
            **metadata,
        }, indent=2),
        encoding="utf-8",
    )
    return course_path


def read_course_metadata(course_id: str, user) -> dict | None:
    """Read optional user-managed metadata without treating it as syllabus content."""
    course_path = _course_dir(course_id, user) / "course.json"
    if not course_path.exists():
        return None
    try:
        data = json.loads(course_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise CourseMetadataStorageError(f"course metadata for '{course_id}' is corrupt") from exc
    if not isinstance(data, dict) or data.get("course_id") != course_id or not isinstance(data.get("course_name"), str):
        raise CourseMetadataStorageError(f"course metadata for '{course_id}' has an invalid shape")
    return data


def write_course_metadata(course_id: str, data: dict, user) -> Path:
    """Replace validated metadata for an existing owned course."""
    course_dir = _course_dir(course_id, user)
    if not (course_dir / "course.json").exists() and not (course_dir / "syllabus.json").exists():
        raise CourseNotFoundError(f"no course '{course_id}' found")
    if not isinstance(data, dict) or data.get("course_id") != course_id or not str(data.get("course_name") or "").strip():
        raise CourseMetadataStorageError("course metadata has an invalid shape")
    course_path = course_dir / "course.json"
    course_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return course_path


def course_is_archived(course_id: str, user) -> bool:
    try:
        metadata = read_course_metadata(course_id, user)
    except CourseMetadataStorageError:
        return False
    return bool(metadata and metadata.get("archived"))


def course_exists(course_id: str, user) -> bool:
    """True if course_id is a real (syllabus'd) course for this user — the
    same definition reminders.list_courses() uses, so this matches exactly
    what the UI already offers as a selectable course. False (never raises)
    for a draft-only course, a missing course, or an unsafe/invalid
    course_id — callers doing input validation want a plain reject, not an
    exception for the common case of a client-supplied string."""
    try:
        course_dir = _course_dir(course_id, user)
    except InvalidCourseIdError:
        return False
    return (course_dir / "syllabus.json").exists()


def course_or_draft_exists(course_id: str, user) -> bool:
    """True if course_id exists as either a real course or a draft class for
    this user."""
    try:
        course_dir = _course_dir(course_id, user)
    except InvalidCourseIdError:
        return False
    return (course_dir / "syllabus.json").exists() or (course_dir / "course.json").exists()


def delete_course(course_id: str, user) -> None:
    """Deletes courses/<user.pk>/<course_id>/ entirely — syllabus, notes,
    references, sessions, quiz history, mastery scores, grades, calendar
    sync records, flashcard progress, custom events, and notifications, all
    scoped to this user. Raises CourseNotFoundError if course_id exists as
    neither a draft nor a real course for this user. Irreversible; callers
    are responsible for confirming with the user before calling this
    (plan-then-pause per CLAUDE.md)."""
    course_dir = _course_dir(course_id, user)
    if not (course_dir / "course.json").exists() and not (course_dir / "syllabus.json").exists():
        raise CourseNotFoundError(f"no course '{course_id}' found")
    shutil.rmtree(course_dir)
    delete_course_state(course_id, user)


def delete_course_state(course_id: str, user) -> None:
    from django.db import transaction
    from agent.models import (
        CalendarSyncRecord,
        CourseSession,
        CustomEvent,
        FlashcardProgress,
        GradeItem,
        MasteryScore,
        Notification,
        QuizAttempt,
        SavedSite,
        CourseMaterial,
    )

    user_filter = _flashcard_user_filter(user)
    with transaction.atomic():
        FlashcardProgress.objects.filter(course_id=course_id, **user_filter).delete()
        GradeItem.objects.filter(course_id=course_id, **user_filter).delete()
        CalendarSyncRecord.objects.filter(course_id=course_id, **user_filter).delete()
        CustomEvent.objects.filter(course_id=course_id, **user_filter).delete()
        Notification.objects.filter(course_id=course_id, **user_filter).delete()
        QuizAttempt.objects.filter(course_id=course_id, **user_filter).delete()
        MasteryScore.objects.filter(course_id=course_id, **user_filter).delete()
        CourseSession.objects.filter(course_id=course_id, **user_filter).delete()
        SavedSite.objects.filter(course_id=course_id, **user_filter).delete()
        CourseMaterial.objects.filter(course_id=course_id, **user_filter).delete()


def rename_course(course_id: str, course_name: str, user) -> None:
    """Updates course_name in place — course.json for a draft, syllabus.json
    for a real course, whichever exists for this user. Raises
    CourseNotFoundError if neither exists."""
    course_dir = _course_dir(course_id, user)
    course_path = course_dir / "course.json"
    syllabus_path = course_dir / "syllabus.json"

    found = False
    if course_path.exists():
        data = json.loads(course_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        course_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        found = True

    if syllabus_path.exists():
        data = json.loads(syllabus_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        syllabus_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        found = True

    if not found:
        raise CourseNotFoundError(f"no course '{course_id}' found")
