"""In-app notifications and idempotent email delivery."""

from datetime import date, datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings as django_settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone as django_timezone

from . import custom_events, recommendations, storage

OVERDUE_CATEGORIES = {"hw", "project", "test_quiz"}
EMAIL_PRESENTATION = {
    "study_reminder": {
        "eyebrow": "YOUR STUDY PLAN",
        "button_label": "Start guided study",
        "accent": "#52774b",
        "accent_soft": "#edf3e9",
    },
    "overdue_deadline": {
        "eyebrow": "DEADLINE UPDATE",
        "button_label": "Open calendar",
        "accent": "#c6652f",
        "accent_soft": "#fff0e6",
    },
}


def _owned_queryset(user):
    from agent.models import Notification
    return Notification.objects.filter(user=user) if getattr(user, "is_authenticated", False) else Notification.objects.none()


def _notification_to_dict(notification) -> dict:
    return {
        "id": notification.id, "kind": notification.kind, "title": notification.title,
        "body": notification.body, "course_id": notification.course_id,
        "deadline_id": notification.deadline_id, "due_date": notification.due_date,
        "category": notification.category, "action_url": notification.action_url,
        "read": notification.read, "emailed": notification.emailed_at is not None,
        "created_at": notification.created_at.isoformat(),
    }


def _create(user, key, **defaults):
    from agent.models import Notification
    if not getattr(user, "is_authenticated", False):
        return None, False
    try:
        return Notification.objects.get_or_create(user=user, notification_key=key, defaults=defaults)
    except IntegrityError:
        return Notification.objects.filter(user=user, notification_key=key).first(), False


def generate_overdue_deadline_notifications(user=None, today=None) -> int:
    from agent.models import Notification
    today = (today or date.today()).isoformat()
    created_count = 0
    for event in custom_events.list_events(user=user):
        category = storage.normalize_date_type(event.get("type"))
        if category not in OVERDUE_CATEGORIES or event.get("completed"):
            continue
        if not event.get("id") or not event.get("date") or event["date"] >= today:
            continue
        _, created = _create(
            user, f"overdue_deadline:{event['id']}:{event['date']}",
            kind=Notification.KIND_OVERDUE_DEADLINE,
            title=f"Overdue: {event.get('title', 'Deadline')}",
            body="This deadline has passed and is not marked complete.",
            course_id=event.get("course_id"), deadline_id=event.get("id"),
            due_date=event.get("date"), category=category, action_url="/calendar/",
        )
        created_count += int(created)
    return created_count


def _user_settings(user):
    from agent.models import UserSettings
    settings_row, _ = UserSettings.objects.get_or_create(user=user)
    return settings_row


def generate_study_reminder_notification(user, now=None) -> int:
    """Create one grounded study reminder on each enabled study day."""
    if not getattr(user, "is_authenticated", False):
        return 0
    preferences = _user_settings(user)
    if not preferences.notifications_enabled:
        return 0
    now = now or datetime.now(timezone.utc)
    try:
        local_now = now.astimezone(ZoneInfo(preferences.timezone))
    except ZoneInfoNotFoundError:
        local_now = now.astimezone(ZoneInfo(django_settings.TIME_ZONE))
    if local_now.time().replace(tzinfo=None) < preferences.study_reminder_time:
        return 0
    ranked = recommendations.rank_recommendations(
        user, session_minutes=preferences.preferred_session_minutes, limit=1, now=now,
    )
    if not ranked:
        return 0
    item = ranked[0]
    course_id, topic = item["course_id"], item["topic"]
    _, created = _create(
        user, f"study_reminder:{local_now.date().isoformat()}", kind="study_reminder",
        title=f"Ready for a {preferences.preferred_session_minutes}-minute study session?",
        body=f"Focus on {topic}. {item.get('reason', '')}".strip(),
        course_id=course_id, category="study",
        action_url=f"/study/?view=session&course={quote(course_id)}&topic={quote(topic)}",
    )
    return int(created)


def create_cora_message_notification(user, course_id, session_id, answer, request_id=None):
    """Connect a saved Cora assistant turn to the notification center."""
    from agent.models import CourseSession, Notification
    if not getattr(user, "is_authenticated", False) or not session_id:
        return None
    if request_id:
        message_key = str(request_id)
    else:
        session = CourseSession.objects.filter(user=user, course_id=course_id, session_id=session_id).first()
        latest = session.messages.filter(role="assistant").order_by("-position").first() if session else None
        message_key = str(latest.pk) if latest else str(session_id)
    compact = " ".join(str(answer or "").split())
    notification, _ = _create(
        user, f"cora_message:{session_id}:{message_key}",
        kind=Notification.KIND_CORA_MESSAGE, title="Cora replied",
        body=(compact[:157] + "…") if len(compact) > 160 else compact,
        course_id=course_id, category="cora",
        action_url=f"/cora/?course={quote(course_id)}&session={quote(session_id)}",
    )
    return notification


def refresh_notifications(user, now=None) -> int:
    today = now.astimezone(timezone.utc).date() if now else None
    return generate_overdue_deadline_notifications(user=user, today=today) + generate_study_reminder_notification(user, now=now)


def list_notifications(user=None, limit: int = 20) -> dict:
    refresh_notifications(user=user)
    queryset = _owned_queryset(user)
    unread = queryset.filter(read=False)
    rows = unread.order_by("-created_at", "-id")[:limit]
    return {
        "notifications": [_notification_to_dict(n) for n in rows],
        "unread_count": unread.count(),
    }


def mark_notifications_read(user=None, ids=None) -> dict:
    queryset = _owned_queryset(user)
    if ids is not None:
        queryset = queryset.filter(id__in=ids)
    queryset.update(read=True)
    return list_notifications(user=user)


def send_pending_notification_emails(user, now=None) -> int:
    """Send at most one study email for the user's current local calendar day."""
    if not getattr(user, "is_authenticated", False) or not user.email:
        return 0
    preferences = _user_settings(user)
    if not preferences.notifications_enabled:
        return 0
    now = now or datetime.now(timezone.utc)
    try:
        local_date = now.astimezone(ZoneInfo(preferences.timezone)).date()
    except ZoneInfoNotFoundError:
        local_date = now.astimezone(ZoneInfo(django_settings.TIME_ZONE)).date()
        local_now = now.astimezone(ZoneInfo(django_settings.TIME_ZONE))
    else:
        local_now = now.astimezone(ZoneInfo(preferences.timezone))
    if local_now.time().replace(tzinfo=None) < preferences.study_reminder_time:
        return 0
    notification = _owned_queryset(user).filter(
        notification_key=f"study_reminder:{local_date.isoformat()}",
        kind="study_reminder",
        emailed_at__isnull=True,
    ).first()
    if notification is None:
        return 0

    action_url = f"{django_settings.ONTRACK_BASE_URL}{notification.action_url or '/'}"
    presentation = EMAIL_PRESENTATION["study_reminder"]
    first_name = (user.first_name or user.username or "there").strip()
    body = (
        f"Hi {first_name},\n\n{notification.title}\n\n{notification.body}"
        f"\n\n{presentation['button_label']}: {action_url}"
        "\n\nYou can change reminder email preferences in OnTrack Settings."
    )
    html = render_to_string("agent/emails/notification.html", {
        "first_name": first_name,
        "notification": notification,
        "action_url": action_url,
        "settings_url": f"{django_settings.ONTRACK_BASE_URL}/settings/",
        **presentation,
    })
    message = EmailMultiAlternatives(
        subject=f"OnTrack | {notification.title}",
        body=body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html, "text/html")
    delivered = message.send(fail_silently=False)
    if delivered:
        notification.emailed_at = django_timezone.now()
        notification.save(update_fields=["emailed_at"])
        return 1
    return 0
