"""Owner-only pilot analytics composed from existing, student-scoped data."""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from agent.models import (
    GoogleCalendarConnection,
    LlmUsage,
    ProductMetric,
    QuizAttempt,
    SessionMessage,
    StudyActivity,
    StudySession,
    UserSettings,
)

from . import course_catalog, storage

VALID_RANGES = {"7d", "30d", "all"}
QUALIFYING_PRODUCT_EVENTS = {
    "cora_answered",
    "study_completed",
    "study_started",
}


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def range_start(range_key: str, *, now=None):
    if range_key not in VALID_RANGES:
        raise ValueError("range must be one of: 7d, 30d, all")
    if range_key == "all":
        return None
    now = now or timezone.now()
    days = 7 if range_key == "7d" else 30
    local_day = timezone.localdate(now) - timedelta(days=days - 1)
    return timezone.make_aware(datetime.combine(local_day, time.min), timezone.get_current_timezone())


def pilot_students(owner):
    return get_user_model().objects.filter(
        settings__tier=UserSettings.TIER_PILOT,
        is_active=True,
    ).exclude(pk=owner.pk).order_by("pk")


def _quiz_rows(student_ids, start):
    rows = QuizAttempt.objects.filter(user_id__in=student_ids)
    parsed = []
    for row in rows.iterator():
        timestamp = _parse_timestamp(row.timestamp)
        if timestamp and (start is None or timestamp >= start):
            parsed.append((row, timestamp))
    return parsed


def _message_rows(student_ids, start):
    rows = SessionMessage.objects.filter(session__user_id__in=student_ids, role="user")
    parsed = []
    for row in rows.iterator():
        timestamp = _parse_timestamp(row.timestamp)
        if timestamp and (start is None or timestamp >= start):
            parsed.append((row, timestamp))
    return parsed


def _course_name(user, course_id):
    try:
        record = course_catalog._base_record(course_id, user)
    except (storage.CourseNotFoundError, storage.CourseMetadataStorageError, storage.SyllabusStorageError, OSError, ValueError):
        return course_id.upper()
    return record["name"]


def build_summary(owner, range_key: str, *, now=None):
    now = now or timezone.now()
    start = range_start(range_key, now=now)
    students = list(pilot_students(owner).select_related("settings"))
    student_ids = [student.pk for student in students]

    sessions = StudySession.objects.filter(user_id__in=student_ids)
    activities = StudyActivity.objects.filter(session__user_id__in=student_ids)
    metrics = ProductMetric.objects.filter(user_id__in=student_ids)
    usage = LlmUsage.objects.filter(user_id__in=student_ids)
    if start is not None:
        sessions = sessions.filter(started_at__gte=start)
        activities = activities.filter(created_at__gte=start)
        metrics = metrics.filter(created_at__gte=start)
        usage = usage.filter(date__gte=timezone.localdate(start))

    session_rows = list(sessions.select_related("user"))
    quiz_rows = _quiz_rows(student_ids, start)
    message_rows = _message_rows(student_ids, start)
    flashcard_rows = list(activities.filter(kind=StudyActivity.KIND_FLASHCARD_REVIEWED).select_related("session"))
    product_rows = list(metrics.filter(event__in=QUALIFYING_PRODUCT_EVENTS))

    active_ids = {row.user_id for row in session_rows}
    active_ids.update(row.user_id for row, _ in quiz_rows)
    active_ids.update(row.session.user_id for row in flashcard_rows)
    active_ids.update(row.user_id for row in product_rows)
    active_ids.update(row.session.user_id for row, _ in message_rows)

    status_counts = Counter(student.settings.access_status for student in students)
    total = len(students)
    valid_connections = GoogleCalendarConnection.objects.filter(
        user_id__in=student_ids,
        grant_failed_at__isnull=True,
        token_expiry__gt=now,
    )

    course_stats = defaultdict(lambda: {
        "student_ids": set(), "study_sessions": 0, "questions_answered": 0,
        "first_correct": 0, "first_total": 0, "calendar_student_ids": set(), "name": "",
    })
    for row in session_rows:
        stats = course_stats[row.course_id]
        stats["student_ids"].add(row.user_id)
        stats["study_sessions"] += 1
        stats["name"] = stats["name"] or _course_name(row.user, row.course_id)
    first_attempts = {}
    for row, timestamp in sorted(quiz_rows, key=lambda item: item[1]):
        stats = course_stats[row.course_id]
        stats["student_ids"].add(row.user_id)
        stats["questions_answered"] += 1
        stats["name"] = stats["name"] or _course_name(row.user, row.course_id)
        first_attempts.setdefault((row.user_id, row.course_id, row.topic), row)
    for row in first_attempts.values():
        stats = course_stats[row.course_id]
        stats["first_total"] += 1
        stats["first_correct"] += int(row.correct)

    connection_ids = set(valid_connections.values_list("user_id", flat=True))
    for course_id, stats in course_stats.items():
        stats["calendar_student_ids"] = stats["student_ids"] & connection_ids

    courses = []
    for course_id, stats in course_stats.items():
        accuracy = round(stats["first_correct"] / stats["first_total"] * 100) if stats["first_total"] else None
        courses.append({
            "course_id": course_id,
            "name": stats["name"] or course_id.upper(),
            "students_active": len(stats["student_ids"]),
            "study_sessions": stats["study_sessions"],
            "questions_answered": stats["questions_answered"],
            "first_attempt_accuracy": accuracy,
            "calendar_connected": len(stats["calendar_student_ids"]),
        })
    courses.sort(key=lambda row: (row["study_sessions"] + row["questions_answered"], row["course_id"]), reverse=True)

    dates = []
    active_by_day = defaultdict(set)
    for row in session_rows:
        active_by_day[timezone.localdate(row.started_at)].add(row.user_id)
    for row, timestamp in quiz_rows:
        active_by_day[timezone.localdate(timestamp)].add(row.user_id)
    for row in flashcard_rows:
        active_by_day[timezone.localdate(row.created_at)].add(row.session.user_id)
    for row in product_rows:
        active_by_day[timezone.localdate(row.created_at)].add(row.user_id)
    for row, timestamp in message_rows:
        active_by_day[timezone.localdate(timestamp)].add(row.session.user_id)
    if start is not None:
        cursor = timezone.localdate(start)
        while cursor <= timezone.localdate(now):
            dates.append(cursor)
            cursor += timedelta(days=1)
    else:
        dates = sorted(active_by_day)

    engagement = {
        "study_sessions": len(session_rows),
        "quizzes": len(quiz_rows),
        "flashcards": len(flashcard_rows),
        "cora": len(message_rows),
        "calendar": 0,
    }
    return {
        "pilot": {"name": "Student Pilot 2026", "students": total},
        "range": range_key,
        "access_status": {
            "pending": status_counts[UserSettings.ACCESS_PENDING],
            "active": status_counts[UserSettings.ACCESS_ACTIVE],
            "suspended": status_counts[UserSettings.ACCESS_SUSPENDED],
            "total": total,
        },
        "metrics": {
            "active_students": len(active_ids),
            "study_sessions": len(session_rows),
            "questions_answered": len(quiz_rows),
            "calendar_connected": valid_connections.count(),
            "llm_requests": sum(usage.values_list("count", flat=True)),
        },
        "timeline": [{"date": day.isoformat(), "count": len(active_by_day[day])} for day in dates],
        "engagement": engagement,
        "courses": courses,
        "impact": {
            "resurfacing": {"available": False, "reason": "OnTrack does not yet record a resurfacing event linked to a later attempt."},
            "calendar_retention": {"available": False, "reason": "Disconnected calendar grants are not retained as historical eligibility records."},
            "syllabus_corrections": {"available": False, "reason": "Confirmed syllabus edits are not yet stored as a deduplicated correction audit."},
        },
        "definitions": {
            "active_students": "Students with a study session, submitted quiz answer, flashcard review, Cora message, or qualifying product event in the selected period.",
            "llm_usage": "Student pilot AI requests only. OnTrack does not currently record tokens or provider cost.",
        },
    }


def build_student_export(owner, range_key: str, *, now=None):
    now = now or timezone.now()
    start = range_start(range_key, now=now)
    students = list(pilot_students(owner).select_related("settings"))
    rows = []
    for student in students:
        sessions = StudySession.objects.filter(user=student)
        activities = StudyActivity.objects.filter(session__user=student)
        usage = LlmUsage.objects.filter(user=student)
        if start is not None:
            sessions = sessions.filter(started_at__gte=start)
            activities = activities.filter(created_at__gte=start)
            usage = usage.filter(date__gte=timezone.localdate(start))
        quiz_rows = _quiz_rows([student.pk], start)
        first = {}
        for attempt, timestamp in sorted(quiz_rows, key=lambda item: item[1]):
            first.setdefault((attempt.course_id, attempt.topic), attempt)
        first_values = list(first.values())
        accuracy = round(sum(int(row.correct) for row in first_values) / len(first_values) * 100, 1) if first_values else ""
        valid_connection = GoogleCalendarConnection.objects.filter(
            user=student, grant_failed_at__isnull=True, token_expiry__gt=now,
        ).first()
        course_ids = {row.course_id for row in sessions}
        course_ids.update(row.course_id for row, _ in quiz_rows)
        activity_times = [row.started_at for row in sessions]
        activity_times.extend(timestamp for _, timestamp in quiz_rows)
        rows.append({
            "student_id": student.pk,
            "account_status": student.settings.access_status,
            "created_at": student.date_joined.isoformat(),
            "first_active_at": min(activity_times).isoformat() if activity_times else "",
            "last_active_at": max(activity_times).isoformat() if activity_times else "",
            "courses_count": len(course_ids),
            "study_sessions": sessions.count(),
            "questions_answered": len(quiz_rows),
            "first_attempt_accuracy": accuracy,
            "post_resurfacing_accuracy": "",
            "calendar_connected": bool(valid_connection),
            "calendar_connected_at": valid_connection.connected_at.isoformat() if valid_connection else "",
            "calendar_retained_7d": "",
            "syllabus_dates_extracted": "",
            "syllabus_date_corrections": "",
            "flashcards_studied": activities.filter(kind=StudyActivity.KIND_FLASHCARD_REVIEWED).count(),
            "cora_messages": len(_message_rows([student.pk], start)),
            "llm_requests": sum(usage.values_list("count", flat=True)),
        })
    return rows


def render_student_csv(rows):
    fieldnames = [
        "student_id", "account_status", "created_at", "first_active_at", "last_active_at",
        "courses_count", "study_sessions", "questions_answered", "first_attempt_accuracy",
        "post_resurfacing_accuracy", "calendar_connected", "calendar_connected_at",
        "calendar_retained_7d", "syllabus_dates_extracted", "syllabus_date_corrections",
        "flashcards_studied", "cora_messages", "llm_requests",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
