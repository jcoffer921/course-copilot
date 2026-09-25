"""Authenticated student-profile composition.

Personal fields live on Django's User and its existing one-to-one
UserSettings row. Academic summaries reuse owned dashboard/study data; this
module introduces no competing activity or progress store.
"""

from django.db.models import Count, Sum

from agent.models import CourseMaterial, QuizAttempt, StudyActivity, UserSettings

from . import course_catalog, dashboard, entitlements, streak


def display_name_for(user) -> str:
    full_name = user.get_full_name().strip()
    if full_name:
        return full_name
    if user.first_name.strip():
        return user.first_name.strip()
    if user.email:
        return user.email.split("@", 1)[0]
    return user.username


def _recent_activity(user, course_names: dict[str, str]) -> list[dict]:
    rows = (
        StudyActivity.objects.filter(session__user=user)
        .select_related("session")
        .order_by("-created_at")[:20]
    )
    labels = {
        StudyActivity.KIND_SESSION_STARTED: "Started a study session",
        StudyActivity.KIND_FLASHCARD_REVIEWED: "Studied a flashcard",
        StudyActivity.KIND_QUIZ_ANSWERED: "Answered a quiz question",
        StudyActivity.KIND_SESSION_COMPLETED: "Completed a study session",
    }
    return [
        {
            "kind": row.kind,
            "title": labels.get(row.kind, "Studied in OnTrack"),
            "course_id": row.session.course_id,
            "course_name": course_names.get(row.session.course_id, row.session.course_id.upper()),
            "topic": row.session.topic,
            "occurred_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _calendar_connected(user) -> bool:
    return (
        hasattr(user, "google_calendar_connection")
        and bool(user.google_calendar_connection.refresh_token)
        and user.google_calendar_connection.grant_failed_at is None
    )


def build_profile(user) -> dict:
    settings_row, _ = UserSettings.objects.get_or_create(user=user)
    material_totals = CourseMaterial.objects.filter(user=user).aggregate(
        file_count=Count("pk"), storage_bytes=Sum("size_bytes"),
    )
    dashboard_data = dashboard.build_dashboard(user=user)
    courses = []
    for course_id, summary in dashboard_data["courses"].items():
        if summary.get("error"):
            continue
        courses.append({
            "id": course_id,
            "name": summary.get("course_name") or course_id.upper(),
            "mastery": summary.get("mastery_pct"),
            "topics_count": summary.get("topics_count", 0),
            "quizzes_completed": summary.get("quiz_attempts_count", 0),
        })
    courses.sort(key=lambda row: row["name"].casefold())
    measured_mastery = [row["mastery"] for row in courses if row["mastery"] is not None]
    course_names = {row["id"]: row["name"] for row in courses}

    return {
        "email": user.email,
        "username": user.username,
        "display_name": display_name_for(user),
        "bio": settings_row.bio,
        "university": settings_row.university,
        "major": settings_row.major,
        "graduation_year": settings_row.graduation_year,
        "access_status": settings_row.access_status,
        "tier": settings_row.tier,
        "features": sorted(entitlements.features_for_tier(settings_row.tier)),
        "notifications_enabled": settings_row.notifications_enabled,
        "email_notifications_enabled": settings_row.email_notifications_enabled,
        "google_identity_connected": hasattr(user, "google_account"),
        "calendar_connected": _calendar_connected(user),
        # True only when a connection was made before and has since stopped
        # working (grant revoked/expired) — distinct from never having
        # connected at all, so the UI can say "reconnect" instead of
        # "connect" and not read as OnTrack having silently lost data.
        "calendar_connection_lapsed": (
            hasattr(user, "google_calendar_connection") and not _calendar_connected(user)
        ),
        "timezone": settings_row.timezone,
        "preferred_session_minutes": settings_row.preferred_session_minutes,
        "available_study_days": settings_row.available_study_days,
        "reminder_lead_minutes": settings_row.reminder_lead_minutes,
        "study_reminder_time": settings_row.study_reminder_time.strftime("%H:%M"),
        "member_since": user.date_joined.date().isoformat(),
        "courses_enrolled": course_catalog.count_active_courses(user),
        "quizzes_completed": QuizAttempt.objects.filter(user=user).count(),
        "current_streak": streak.current_streak(user=user),
        "overall_progress": round(sum(measured_mastery) / len(measured_mastery)) if measured_mastery else None,
        "courses": courses,
        "recent_activity": _recent_activity(user, course_names),
        "material_file_count": material_totals["file_count"] or 0,
        "material_storage_bytes": material_totals["storage_bytes"] or 0,
    }
