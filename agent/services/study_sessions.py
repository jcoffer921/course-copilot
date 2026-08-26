"""Guided study session lifecycle: start, log activities, complete, and
review history. Session/activity ownership always flows through the
authenticated user — never a course_id alone."""

from datetime import datetime, timezone
from django.db import transaction

from . import storage
from .storage import _validate_course_id


class StudySessionNotFoundError(Exception):
    pass


class InvalidStudySessionStateError(Exception):
    """Raised for an operation that doesn't make sense given the session's
    current lifecycle state (e.g. completing an already-completed session)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_dict(session) -> dict:
    return {
        "session_id": str(session.session_id),
        "course_id": session.course_id,
        "topic": session.topic,
        "duration_minutes": session.duration_minutes,
        "mode": session.mode,
        "status": session.status,
        "started_at": session.started_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


def _activity_dict(activity) -> dict:
    return {
        "kind": activity.kind,
        "payload": activity.payload,
        "position": activity.position,
        "created_at": activity.created_at.isoformat(),
    }


def _next_activity_position(session) -> int:
    latest = session.activities.order_by("-position").values_list("position", flat=True).first()
    return 0 if latest is None else latest + 1


def _owned_session(user, session_id):
    from agent.models import StudySession

    if not getattr(user, "is_authenticated", False):
        raise StudySessionNotFoundError("no such study session")
    session = StudySession.objects.filter(user=user, session_id=session_id).first()
    if session is None:
        raise StudySessionNotFoundError(f"no study session '{session_id}' for this user")
    return session


def start_session(user, course_id: str, topic: str = "", duration_minutes: int = None, mode: str = "mixed") -> dict:
    from agent.models import StudyActivity, StudySession

    _validate_course_id(course_id)
    if not storage.course_or_draft_exists(course_id, user):
        raise storage.CourseNotFoundError(f"no course found for '{course_id}'")
    syllabus = storage.read_syllabus(course_id, user)
    confirmed_topics = syllabus.get("topics", []) if syllabus else []
    if topic and topic not in confirmed_topics:
        raise ValueError("topic must belong to the confirmed course syllabus")
    if mode not in {choice for choice, _ in StudySession.MODE_CHOICES}:
        raise ValueError(f"mode must be one of {[c for c, _ in StudySession.MODE_CHOICES]}, got {mode!r}")

    with transaction.atomic():
        # Serialize starts per owner so a rapid double-click cannot race the
        # matching-session lookup and create duplicate active sessions.
        user.__class__.objects.select_for_update().get(pk=user.pk)
        existing = StudySession.objects.filter(
            user=user, course_id=course_id, topic=topic or "", duration_minutes=duration_minutes,
            mode=mode, status=StudySession.STATUS_IN_PROGRESS, state={},
        ).order_by("-started_at").first()
        if existing:
            return _session_dict(existing)

        session = StudySession.objects.create(
            user=user,
            course_id=course_id,
            topic=topic or "",
            duration_minutes=duration_minutes,
            mode=mode,
        )
        StudyActivity.objects.create(
            session=session,
            kind=StudyActivity.KIND_SESSION_STARTED,
            payload={"course_id": course_id, "topic": topic or "", "mode": mode},
            position=0,
        )
    return _session_dict(session)


def record_activity(user, session_id, kind: str, payload: dict = None) -> dict:
    from agent.models import StudyActivity, StudySession

    session = _owned_session(user, session_id)
    if kind not in {choice for choice, _ in StudyActivity.KIND_CHOICES}:
        raise ValueError(f"kind must be one of {[c for c, _ in StudyActivity.KIND_CHOICES]}, got {kind!r}")
    if session.status != StudySession.STATUS_IN_PROGRESS:
        raise InvalidStudySessionStateError(f"session '{session_id}' is already {session.status}")

    next_position = _next_activity_position(session)
    activity = StudyActivity.objects.create(
        session=session,
        kind=kind,
        payload=payload or {},
        position=next_position,
    )
    return _activity_dict(activity)


def complete_session(user, session_id, now: datetime = None) -> dict:
    from agent.models import StudyActivity, StudySession

    session = _owned_session(user, session_id)
    if session.status != StudySession.STATUS_IN_PROGRESS:
        raise InvalidStudySessionStateError(f"session '{session_id}' is already {session.status}")

    activities = list(session.activities.all())
    summary = {
        "flashcards_reviewed": sum(1 for a in activities if a.kind == StudyActivity.KIND_FLASHCARD_REVIEWED),
        "questions_answered": sum(1 for a in activities if a.kind == StudyActivity.KIND_QUIZ_ANSWERED),
        "questions_correct": sum(
            1 for a in activities
            if a.kind == StudyActivity.KIND_QUIZ_ANSWERED and a.payload.get("correct")
        ),
    }

    session.status = StudySession.STATUS_COMPLETED
    session.completed_at = now or _now()
    session.save(update_fields=["status", "completed_at"])

    next_position = _next_activity_position(session)
    StudyActivity.objects.create(
        session=session,
        kind=StudyActivity.KIND_SESSION_COMPLETED,
        payload=summary,
        position=next_position,
    )

    result = _session_dict(session)
    result["summary"] = summary
    return result


def list_sessions(user, course_id: str = None, limit: int = 20) -> list:
    from agent.models import StudySession

    if not getattr(user, "is_authenticated", False):
        return []
    queryset = StudySession.objects.filter(user=user)
    if course_id:
        _validate_course_id(course_id)
        queryset = queryset.filter(course_id=course_id)
    sessions = queryset.order_by("-started_at")[:limit]
    return [_session_dict(session) for session in sessions]


def session_detail(user, session_id) -> dict:
    session = _owned_session(user, session_id)
    data = _session_dict(session)
    data["activities"] = [_activity_dict(activity) for activity in session.activities.all()]
    return data
