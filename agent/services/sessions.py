"""
Flat-file JSON storage for grounded Q&A conversation sessions. Same approach
as storage.py — sessions live under courses/<course_id>/sessions/<session_id>.json.
Plain sync I/O; wrap with sync_to_async at call sites (views.py), same pattern
as storage.py.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import storage

# session_id becomes a filename under courses/<course_id>/sessions/ — same
# defense as storage.COURSE_ID_RE, restricted to a safe charset.
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

VALID_ROLES = {"user", "assistant"}


class SessionStorageError(Exception):
    """Raised when an existing session file on disk is corrupt/unreadable."""


class SessionNotFoundError(Exception):
    """Raised when the requested session_id doesn't exist for that course."""


class InvalidSessionIdError(ValueError):
    """Raised when session_id isn't a safe filesystem path segment."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sessions_dir(course_id: str) -> Path:
    """Resolves courses/<course_id>/sessions/ (course_id validated by storage._course_dir)."""
    return storage._course_dir(course_id) / "sessions"


def _session_path(course_id: str, session_id: str) -> Path:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise InvalidSessionIdError(f"invalid session_id: {session_id!r}")
    sessions_dir = _sessions_dir(course_id)
    path = (sessions_dir / f"{session_id}.json").resolve()
    if path.parent != sessions_dir.resolve():
        raise InvalidSessionIdError(f"invalid session_id: {session_id!r}")
    return path


# --------------------------------------------------------------------------
# Validation — same pattern as validate_syllabus in storage.py
# --------------------------------------------------------------------------

def validate_session(data: dict) -> list:
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

    require("session_id", str)
    require("course_id", str)
    require("created_at", str)
    require("updated_at", str)
    require("messages", list)

    if errors:
        return errors  # top-level shape is broken, don't bother checking nested items

    for i, m in enumerate(data["messages"]):
        if not isinstance(m, dict):
            errors.append(f"messages[{i}] is not an object")
            continue
        if "role" not in m or "content" not in m or "timestamp" not in m:
            errors.append(f"messages[{i}] missing one of role/content/timestamp: {m}")
            continue
        if m["role"] not in VALID_ROLES:
            errors.append(f"messages[{i}].role invalid: {m['role']!r} (must be one of {VALID_ROLES})")
        if not isinstance(m["content"], str):
            errors.append(f"messages[{i}].content must be a string")
        if m["role"] == "user" and (m.get("sources") or m.get("grounded") is not None):
            errors.append(
                f"WARNING: messages[{i}] is a user message but has sources/grounded set "
                f"(those only apply to assistant messages, not blocking)"
            )

    return errors


# --------------------------------------------------------------------------
# Read / write — plain sync I/O, wrapped with sync_to_async at the call site
# --------------------------------------------------------------------------

def create_session(course_id: str) -> dict:
    """Creates a new empty session for course_id and writes it to disk.
    Raises storage.CourseNotFoundError if no syllabus.json exists yet — a
    session can't be grounded in a course that doesn't exist."""
    syllabus = storage.read_syllabus(course_id)
    if syllabus is None:
        raise storage.CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    session_id = uuid.uuid4().hex
    now = _now()
    data = {
        "session_id": session_id,
        "course_id": course_id,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }

    sessions_dir = _sessions_dir(course_id)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = _session_path(course_id, session_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def get_session(course_id: str, session_id: str):
    """Returns the parsed session dict, or None if it doesn't exist."""
    path = _session_path(course_id, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SessionStorageError(f"session '{session_id}' for '{course_id}' is corrupt: {e}")


def append_message(
    course_id: str, session_id: str, role: str, content: str,
    sources: list = None, grounded: bool = None,
) -> dict:
    """Appends a message to an existing session and writes it back. Raises
    SessionNotFoundError if the session doesn't exist — callers must create
    it first via create_session(), this never creates one implicitly."""
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r} (must be one of {VALID_ROLES})")

    data = get_session(course_id, session_id)
    if data is None:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")

    message = {"role": role, "content": content, "timestamp": _now()}
    if role == "assistant":
        message["sources"] = sources or []
        message["grounded"] = bool(grounded)

    data["messages"].append(message)
    data["updated_at"] = _now()

    path = _session_path(course_id, session_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def list_sessions(course_id: str) -> list:
    """Returns [{session_id, created_at, updated_at, message_count}, ...] for
    every session under courses/<course_id>/sessions/, sorted by filename.
    Does not include message bodies — use get_session() for that. Returns []
    if sessions/ doesn't exist yet."""
    sessions_dir = _sessions_dir(course_id)
    if not sessions_dir.exists():
        return []

    summaries = []
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SessionStorageError(f"session file '{path.name}' for '{course_id}' is corrupt: {e}")
        summaries.append({
            "session_id": data.get("session_id", path.stem),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "message_count": len(data.get("messages", [])),
        })
    return summaries
