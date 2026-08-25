"""SQLite-backed storage for grounded Q&A conversation sessions."""

import re
import uuid
from datetime import datetime, timezone

from . import storage

# session_id becomes a filename under courses/<course_id>/sessions/ — same
# defense as storage.COURSE_ID_RE, restricted to a safe charset.
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

VALID_ROLES = {"user", "assistant"}
MEMORY_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "from", "have", "into", "just", "like", "more", "need",
    "should", "that", "their", "there", "these", "they", "this", "through",
    "what", "when", "where", "which", "with", "would", "your",
}


class SessionStorageError(Exception):
    """Raised when an existing session file on disk is corrupt/unreadable."""


class SessionNotFoundError(Exception):
    """Raised when the requested session_id doesn't exist for that course."""


class InvalidSessionIdError(ValueError):
    """Raised when session_id isn't a safe filesystem path segment."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_session_id(course_id: str, session_id: str) -> None:
    storage._course_dir(course_id)
    if not SESSION_ID_RE.fullmatch(session_id):
        raise InvalidSessionIdError(f"invalid session_id: {session_id!r}")


def _user_filter(user=None) -> dict:
    if getattr(user, "is_authenticated", False):
        return {"user": user}
    return {"user__isnull": True}


def _memory_terms(text: str) -> set:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", text or "")
    return {word.lower() for word in words if word.lower() not in MEMORY_STOPWORDS}


def _session_to_dict(session) -> dict:
    messages = []
    for message in session.messages.all():
        data = {
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp,
        }
        if message.role == "assistant":
            data["sources"] = message.sources or []
            data["grounded"] = bool(message.grounded)
        messages.append(data)
    return {
        "session_id": session.session_id,
        "course_id": session.course_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": messages,
    }


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

def create_session(course_id: str, user=None) -> dict:
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

    from agent.models import CourseSession

    CourseSession.objects.create(
        session_id=session_id,
        course_id=course_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        created_at=now,
        updated_at=now,
    )
    return data


def get_session(course_id: str, session_id: str, user=None):
    """Returns the parsed session dict, or None if it doesn't exist."""
    _validate_session_id(course_id, session_id)
    from agent.models import CourseSession

    session = CourseSession.objects.prefetch_related("messages").filter(
        course_id=course_id,
        session_id=session_id,
        **_user_filter(user),
    ).first()
    if session is None:
        return None
    return _session_to_dict(session)


def append_message(
    course_id: str, session_id: str, role: str, content: str,
    sources: list = None, grounded: bool = None, user=None,
) -> dict:
    """Appends a message to an existing session and writes it back. Raises
    SessionNotFoundError if the session doesn't exist — callers must create
    it first via create_session(), this never creates one implicitly."""
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r} (must be one of {VALID_ROLES})")

    _validate_session_id(course_id, session_id)
    from agent.models import CourseSession, SessionMessage

    session = CourseSession.objects.filter(course_id=course_id, session_id=session_id, **_user_filter(user)).first()
    if session is None:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")

    now = _now()
    position = session.messages.count()
    SessionMessage.objects.create(
        session=session,
        role=role,
        content=content,
        timestamp=now,
        sources=sources or [],
        grounded=bool(grounded) if role == "assistant" else None,
        position=position,
    )
    session.updated_at = now
    session.save(update_fields=["updated_at"])
    return get_session(course_id, session_id, user=user)


def list_sessions(course_id: str, user=None) -> list:
    """Returns [{session_id, created_at, updated_at, message_count}, ...] for
    every session under courses/<course_id>/sessions/, sorted by filename.
    Does not include message bodies — use get_session() for that. Returns []
    if sessions/ doesn't exist yet."""
    storage._course_dir(course_id)
    from django.db.models import Count
    from agent.models import CourseSession

    return [
        {
            "session_id": session.session_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "message_count": session.message_count,
        }
        for session in CourseSession.objects.filter(course_id=course_id, **_user_filter(user))
        .annotate(message_count=Count("messages"))
        .order_by("session_id")
    ]


def relevant_messages(
    course_id: str, query: str, session_id: str = None, user=None, limit: int = 8,
) -> list:
    """Returns small excerpts from prior saved sessions that overlap query.

    This is deliberately lexical and bounded. It gives Cora useful continuity
    without stuffing every previous conversation into every prompt.
    """
    storage._course_dir(course_id)
    terms = _memory_terms(query)
    if not terms:
        return []

    from django.db.models import Q
    from agent.models import CourseSession, SessionMessage

    sessions_qs = CourseSession.objects.filter(course_id=course_id, **_user_filter(user))
    if session_id:
        sessions_qs = sessions_qs.exclude(session_id=session_id)

    # Coarse DB-side substring pre-filter on the extracted terms, so a course
    # with a lot of session history doesn't pull and score every message on
    # every question — only rows that could plausibly overlap are fetched.
    # The exact word-boundary scoring below still runs on this smaller set.
    term_filter = Q()
    for term in terms:
        term_filter |= Q(content__icontains=term)

    messages = (
        SessionMessage.objects
        .filter(session__in=sessions_qs)
        .filter(term_filter)
        .select_related("session")
        .order_by("-session__updated_at", "position")[:200]
    )

    scored = []
    for message in messages:
        content = message.content or ""
        message_terms = _memory_terms(content)
        overlap = terms & message_terms
        if not overlap:
            continue
        scored.append((
            len(overlap),
            message.session.updated_at or "",
            {
                "session_id": message.session.session_id,
                "role": message.role,
                "content": content[:800],
                "timestamp": message.timestamp,
                "sources": message.sources or [],
                "grounded": bool(message.grounded) if message.role == "assistant" else None,
                "matched_terms": sorted(overlap),
            },
        ))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:limit]]
