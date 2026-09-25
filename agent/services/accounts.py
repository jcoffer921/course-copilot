"""Owned account export and destructive operations with explicit confirmation."""

import json
import shutil
from datetime import datetime, timezone

from . import storage


ACCOUNT_DELETE_CONFIRMATION = "DELETE MY ACCOUNT"


def _course_ids(user):
    root = storage.COURSES_DIR / str(user.pk)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and storage.COURSE_ID_RE.fullmatch(path.name))


def export_account_data(user) -> dict:
    """Build a portable export without credentials, storage keys, or security metadata."""
    from agent.models import CourseMaterial, CustomEvent, ExamPlan, QuizAttempt, StudySession, UserSettings

    preferences, _ = UserSettings.objects.get_or_create(user=user)
    courses = []
    for course_id in _course_ids(user):
        courses.append({
            "course_id": course_id,
            "metadata": storage.read_course_metadata(course_id, user),
            "syllabus": storage.read_syllabus(course_id, user),
            "notes": storage.read_notes(course_id, user),
            "references": storage.read_references(course_id, user),
            "quiz_history": storage.read_quiz_history(course_id, user),
            "mastery": storage.read_mastery_scores(course_id, user),
            "grades": storage.read_grades(course_id, user),
        })
    materials = CourseMaterial.objects.filter(user=user).values(
        "material_id", "course_id", "original_filename", "material_type", "size_bytes",
        "content_type", "processing_status", "review_status", "uploaded_at", "updated_at",
    )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "display_name": user.get_full_name(), "username": user.username, "email": user.email,
            "bio": preferences.bio, "university": preferences.university,
            "major": preferences.major, "graduation_year": preferences.graduation_year,
        },
        "preferences": {
            "notifications_enabled": preferences.notifications_enabled,
            "email_notifications_enabled": preferences.email_notifications_enabled,
            "timezone": preferences.timezone,
            "preferred_session_minutes": preferences.preferred_session_minutes,
            "available_study_days": preferences.available_study_days,
            "reminder_lead_minutes": preferences.reminder_lead_minutes,
            "study_reminder_time": preferences.study_reminder_time.strftime("%H:%M"),
        },
        "connections": {
            "google_identity_connected": hasattr(user, "google_account"),
            "google_calendar_connected": hasattr(user, "google_calendar_connection"),
        },
        "courses": courses,
        "materials": list(materials),
        "exam_plans": list(ExamPlan.objects.filter(user=user).values(
            "course_id", "event_id", "included_topics", "included_material_ids", "study_guide", "created_at", "updated_at"
        )),
        "study_sessions": list(StudySession.objects.filter(user=user).values(
            "session_id", "course_id", "topic", "duration_minutes", "mode", "status", "started_at", "completed_at"
        )),
        "quiz_attempts": list(QuizAttempt.objects.filter(user=user).values(
            "course_id", "lecture_id", "chunk_id", "topic", "question", "correct_answer",
            "user_answer", "correct", "timestamp",
        )),
        "calendar_events": list(CustomEvent.objects.filter(user=user).values(
            "id", "course_id", "date", "time", "end_time", "title", "type", "location", "notes", "source", "completed", "created_at"
        )),
    }


def serialize_export(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def delete_account(user, confirmation: str) -> None:
    """Delete only the authenticated user's DB row and course directory."""
    if confirmation != ACCOUNT_DELETE_CONFIRMATION:
        raise ValueError(f'Type "{ACCOUNT_DELETE_CONFIRMATION}" to confirm account deletion.')
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Authentication is required.")

    courses_root = storage.COURSES_DIR.resolve()
    user_dir = (courses_root / str(user.pk)).resolve()
    if not user_dir.is_relative_to(courses_root) or user_dir.parent != courses_root:
        raise ValueError("Unsafe account storage path.")

    if user_dir.exists():
        shutil.rmtree(user_dir)
    user.delete()
