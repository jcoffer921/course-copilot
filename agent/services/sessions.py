"""SQLite-backed storage for grounded Q&A conversation sessions."""

import re
import uuid
from datetime import datetime, timezone

from . import storage

# session_id is a URL/resource identifier. Keep the same defense-in-depth
# restriction used for path segments even though sessions now live in SQLite.
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

VALID_ROLES = {"user", "assistant"}
VALID_CITATION_TYPES = {"syllabus", "notes", "slides", "reference", "web"}
CITATION_FIELDS = {
    "material_id", "material_type", "title", "lecture_id", "chunk_id", "page", "url", "excerpt",
}
RESPONSE_METADATA_FIELDS = (
    "pending_deadline", "pending_deadlines", "deadline_missing", "saved_site",
    "grounding_mode",
)
MEMORY_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "from", "have", "into", "just", "like", "more", "need",
    "should", "that", "their", "there", "these", "they", "this", "through",
    "what", "when", "where", "which", "with", "would", "your",
}


class SessionStorageError(Exception):
    """Raised when an existing session record is corrupt or unreadable."""


class SessionNotFoundError(Exception):
    """Raised when the requested session_id doesn't exist for that course."""


class InvalidSessionIdError(ValueError):
    """Raised when session_id isn't a safe filesystem path segment."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_session_id(course_id: str, session_id: str, user=None) -> None:
    storage._validate_course_id(course_id)
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
            data.update({
                key: value
                for key, value in (message.response_metadata or {}).items()
                if key in RESPONSE_METADATA_FIELDS
            })
        messages.append(data)
    return {
        "session_id": session.session_id,
        "course_id": session.course_id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": messages,
    }


def _validate_stored_sources(sources) -> list:
    """Accept legacy labels and the complete v1 citation shape, but nothing else."""
    if not isinstance(sources, list) or len(sources) > 12:
        raise ValueError("assistant sources must be a list with at most 12 items")
    for index, source in enumerate(sources):
        if isinstance(source, str):
            if not source.strip():
                raise ValueError(f"assistant sources[{index}] must not be blank")
            continue
        if not isinstance(source, dict) or not CITATION_FIELDS.issubset(source):
            raise ValueError(f"assistant sources[{index}] is not a complete citation")
        if not isinstance(source["material_id"], str) or not source["material_id"]:
            raise ValueError(f"assistant sources[{index}].material_id is invalid")
        if source["material_type"] not in VALID_CITATION_TYPES:
            raise ValueError(f"assistant sources[{index}].material_type is invalid")
        if not isinstance(source["title"], str) or not source["title"]:
            raise ValueError(f"assistant sources[{index}].title is invalid")
        if not isinstance(source["excerpt"], str) or len(source["excerpt"]) > 360:
            raise ValueError(f"assistant sources[{index}].excerpt is invalid")
        for nullable_string in ("lecture_id", "chunk_id", "url"):
            if source[nullable_string] is not None and not isinstance(source[nullable_string], str):
                raise ValueError(f"assistant sources[{index}].{nullable_string} is invalid")
        if source["page"] is not None and (
            not isinstance(source["page"], int) or isinstance(source["page"], bool) or source["page"] < 1
        ):
            raise ValueError(f"assistant sources[{index}].page is invalid")
    return sources


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
        if m["role"] == "assistant":
            try:
                _validate_stored_sources(m.get("sources", []))
            except ValueError as exc:
                errors.append(f"messages[{i}].sources invalid: {exc}")
            if not isinstance(m.get("grounded"), bool):
                errors.append(f"messages[{i}].grounded must be a boolean")

    return errors


# --------------------------------------------------------------------------
# Read / write — plain sync I/O, wrapped with sync_to_async at the call site
# --------------------------------------------------------------------------

def create_session(course_id: str, user=None) -> dict:
    """Creates a new empty SQLite-backed session for course_id.
    Raises storage.CourseNotFoundError if no syllabus.json exists yet — a
    session can't be grounded in a course that doesn't exist."""
    syllabus = storage.read_syllabus(course_id, user)
    if syllabus is None:
        raise storage.CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    session_id = uuid.uuid4().hex
    now = _now()
    data = {
        "session_id": session_id,
        "course_id": course_id,
        "title": "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }

    from agent.models import CourseSession

    CourseSession.objects.create(
        session_id=session_id,
        course_id=course_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        title=data["title"],
        created_at=now,
        updated_at=now,
    )
    return data


def get_session(course_id: str, session_id: str, user=None):
    """Returns the parsed session dict, or None if it doesn't exist."""
    _validate_session_id(course_id, session_id, user)
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
    client_request_id: str = None, response_metadata: dict = None,
) -> dict:
    """Appends a message to an existing session. Raises
    SessionNotFoundError if the session doesn't exist — callers must create
    it first via create_session(), this never creates one implicitly."""
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r} (must be one of {VALID_ROLES})")

    _validate_session_id(course_id, session_id, user)
    from agent.models import CourseSession, SessionMessage

    session = CourseSession.objects.filter(course_id=course_id, session_id=session_id, **_user_filter(user)).first()
    if session is None:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")

    now = _now()
    position = session.messages.count()
    assistant_sources = _validate_stored_sources(sources or []) if role == "assistant" else []
    assistant_metadata = {
        key: value
        for key, value in (response_metadata or {}).items()
        if key in RESPONSE_METADATA_FIELDS
    } if role == "assistant" else {}
    SessionMessage.objects.create(
        session=session,
        role=role,
        content=content,
        timestamp=now,
        sources=assistant_sources,
        grounded=bool(grounded) if role == "assistant" else None,
        client_request_id=client_request_id if role == "user" else None,
        response_metadata=assistant_metadata,
        position=position,
    )
    session.updated_at = now
    session.save(update_fields=["updated_at"])
    return get_session(course_id, session_id, user=user)


def list_sessions(course_id: str, user=None) -> list:
    """Return newest-first summaries without message bodies for one owned course."""
    storage._validate_course_id(course_id)
    from django.db.models import Count
    from agent.models import CourseSession

    return [
        {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "message_count": session.message_count,
        }
        for session in CourseSession.objects.filter(course_id=course_id, **_user_filter(user))
        .annotate(message_count=Count("messages"))
        .order_by("-updated_at", "session_id")
    ]


def _default_title(question: str) -> str:
    title = " ".join(str(question or "").split()).strip()
    if len(title) > 80:
        title = title[:79].rstrip() + "…"
    return title or "New chat"


def exchange_for_request(course_id: str, session_id: str, client_request_id: str, user=None):
    """Return a completed assistant response for an idempotent client request."""
    if not client_request_id:
        return None
    _validate_session_id(course_id, session_id, user)
    from agent.models import CourseSession, SessionMessage

    session = CourseSession.objects.filter(
        course_id=course_id, session_id=session_id, **_user_filter(user)
    ).first()
    if session is None:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")
    user_message = SessionMessage.objects.filter(
        session=session, role="user", client_request_id=client_request_id
    ).first()
    if user_message is None:
        return None
    assistant = SessionMessage.objects.filter(
        session=session, role="assistant", position=user_message.position + 1
    ).first()
    if assistant is None:
        return None
    return {
        "answer": assistant.content,
        "grounded": bool(assistant.grounded),
        "sources": assistant.sources or [],
        **(assistant.response_metadata or {}),
    }


def append_exchange(
    course_id: str,
    session_id: str,
    question: str,
    result: dict,
    *,
    client_request_id: str = None,
    user=None,
) -> dict:
    """Atomically append one user/assistant pair, idempotently when keyed."""
    _validate_session_id(course_id, session_id, user)
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
        raise ValueError("assistant answer must be a string")
    if not isinstance(result.get("grounded"), bool):
        raise ValueError("assistant grounded must be a boolean")
    from django.db import transaction
    from agent.models import CourseSession, SessionMessage

    with transaction.atomic():
        session = CourseSession.objects.select_for_update().filter(
            course_id=course_id, session_id=session_id, **_user_filter(user)
        ).first()
        if session is None:
            raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")
        if client_request_id:
            existing = exchange_for_request(course_id, session_id, client_request_id, user=user)
            if existing is not None:
                return existing

        position = session.messages.count()
        now = _now()
        SessionMessage.objects.create(
            session=session,
            role="user",
            content=question,
            timestamp=now,
            client_request_id=client_request_id,
            position=position,
        )
        metadata = {
            key: result[key]
            for key in RESPONSE_METADATA_FIELDS
            if key in result
        }
        assistant_sources = _validate_stored_sources(result.get("sources", []))
        SessionMessage.objects.create(
            session=session,
            role="assistant",
            content=result.get("answer", ""),
            timestamp=now,
            sources=assistant_sources,
            grounded=result["grounded"],
            response_metadata=metadata,
            position=position + 1,
        )
        if session.title == "New chat":
            session.title = _default_title(question)
        session.updated_at = now
        session.save(update_fields=["title", "updated_at"])
    return result


def rename_session(course_id: str, session_id: str, title: str, user=None) -> dict:
    _validate_session_id(course_id, session_id, user)
    normalized = " ".join(str(title or "").split()).strip()
    if not normalized:
        raise ValueError("Conversation title is required.")
    from agent.models import CourseSession

    session = CourseSession.objects.filter(
        course_id=course_id, session_id=session_id, **_user_filter(user)
    ).first()
    if session is None:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")
    session.title = normalized[:255]
    session.updated_at = _now()
    session.save(update_fields=["title", "updated_at"])
    return _session_to_dict(session)


def delete_session(course_id: str, session_id: str, confirmation: str, user=None) -> None:
    if confirmation != "DELETE":
        raise ValueError('Type "DELETE" to confirm conversation deletion.')
    _validate_session_id(course_id, session_id, user)
    from agent.models import CourseSession

    deleted, _ = CourseSession.objects.filter(
        course_id=course_id, session_id=session_id, **_user_filter(user)
    ).delete()
    if not deleted:
        raise SessionNotFoundError(f"no session '{session_id}' found for course '{course_id}'")


def relevant_messages(
    course_id: str, query: str, session_id: str = None, user=None, limit: int = 8,
) -> list:
    """Returns small excerpts from prior saved sessions that overlap query.

    This is deliberately lexical and bounded. It gives Cora useful continuity
    without stuffing every previous conversation into every prompt.
    """
    storage._validate_course_id(course_id)
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
