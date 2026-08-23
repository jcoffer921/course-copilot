from datetime import date

from django.db import IntegrityError

from . import custom_events, storage

OVERDUE_CATEGORIES = {"hw", "project", "test_quiz"}


def _notification_to_dict(notification) -> dict:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "course_id": notification.course_id,
        "deadline_id": notification.deadline_id,
        "due_date": notification.due_date,
        "category": notification.category,
        "read": notification.read,
        "created_at": notification.created_at.isoformat(),
    }


def generate_overdue_deadline_notifications(user=None) -> int:
    from agent.models import Notification

    today = date.today().isoformat()
    user_value = user if getattr(user, "is_authenticated", False) else None
    created_count = 0
    for event in custom_events.list_events(user=user):
        category = storage.normalize_date_type(event.get("type"))
        if category not in OVERDUE_CATEGORIES:
            continue
        if event.get("completed"):
            continue
        if not event.get("id") or not event.get("date") or event["date"] >= today:
            continue
        key = f"overdue_deadline:{event['id']}:{event['date']}"
        try:
            _, created = Notification.objects.get_or_create(
                user=user_value,
                notification_key=key,
                defaults={
                    "kind": Notification.KIND_OVERDUE_DEADLINE,
                    "title": f"Overdue: {event.get('title', 'Deadline')}",
                    "body": "This deadline has passed and is not marked complete.",
                    "course_id": event.get("course_id"),
                    "deadline_id": event.get("id"),
                    "due_date": event.get("date"),
                    "category": category,
                },
            )
            if created:
                created_count += 1
        except IntegrityError:
            continue
    return created_count


def list_notifications(user=None, limit: int = 20) -> dict:
    from agent.models import Notification

    generate_overdue_deadline_notifications(user=user)
    queryset = Notification.objects.all()
    if getattr(user, "is_authenticated", False):
        queryset = queryset.filter(user=user)
    else:
        queryset = queryset.filter(user__isnull=True)
    unread_count = queryset.filter(read=False).count()
    rows = queryset.order_by("-created_at", "-id")[:limit]
    return {"notifications": [_notification_to_dict(n) for n in rows], "unread_count": unread_count}


def mark_notifications_read(user=None, ids=None) -> dict:
    from agent.models import Notification

    queryset = Notification.objects.all()
    if getattr(user, "is_authenticated", False):
        queryset = queryset.filter(user=user)
    else:
        queryset = queryset.filter(user__isnull=True)
    if ids is not None:
        queryset = queryset.filter(id__in=ids)
    queryset.update(read=True)
    return list_notifications(user=user)
