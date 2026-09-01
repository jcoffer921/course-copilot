from datetime import datetime, timezone

import pytest
from django.core import mail
from django.test import override_settings

from agent.models import Notification, UserSettings
from agent.services import notifications


pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="reminder-user", email="student@example.com",
    )


def test_study_reminder_is_personalized_and_created_once_per_day(user, monkeypatch):
    preferences = UserSettings.objects.create(
        user=user, notifications_enabled=True, timezone="America/New_York",
        preferred_session_minutes=45, available_study_days=[0],
    )
    monkeypatch.setattr(notifications.recommendations, "rank_recommendations", lambda *args, **kwargs: [{
        "course_id": "cs101", "topic": "Recursion",
        "reason": "Recursion needs another review.",
    }])
    monday = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)

    assert notifications.generate_study_reminder_notification(user, now=monday) == 1
    assert notifications.generate_study_reminder_notification(user, now=monday) == 0

    row = Notification.objects.get(user=user, kind=Notification.KIND_STUDY_REMINDER)
    assert "45-minute" in row.title
    assert "Recursion" in row.body
    assert row.action_url == "/study/?view=session&course=cs101&topic=Recursion"
    preferences.available_study_days = [1]
    preferences.save()
    assert notifications.generate_study_reminder_notification(
        user, now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    ) == 1


def test_study_reminder_waits_for_users_local_time(user, monkeypatch):
    UserSettings.objects.create(
        user=user, notifications_enabled=True, timezone="America/New_York",
        study_reminder_time=notifications.datetime.strptime("18:30", "%H:%M").time(),
    )
    monkeypatch.setattr(notifications.recommendations, "rank_recommendations", lambda *args, **kwargs: [{
        "course_id": "cs101", "topic": "Recursion", "reason": "Review it.",
    }])

    assert notifications.generate_study_reminder_notification(
        user, now=datetime(2026, 8, 31, 22, 29, tzinfo=timezone.utc),
    ) == 0
    assert notifications.generate_study_reminder_notification(
        user, now=datetime(2026, 8, 31, 22, 30, tzinfo=timezone.utc),
    ) == 1


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ONTRACK_BASE_URL="https://ontrack.example",
)
def test_study_email_is_sent_once_and_contains_action_link(user):
    UserSettings.objects.create(
        user=user, notifications_enabled=True, timezone="America/New_York",
    )
    now = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    today = now.astimezone(notifications.ZoneInfo("America/New_York")).date().isoformat()
    row = Notification.objects.create(
        user=user, notification_key=f"study_reminder:{today}", kind=Notification.KIND_STUDY_REMINDER,
        title="Time to study", body="Review recursion.", action_url="/study/?course=cs101",
    )

    assert notifications.send_pending_notification_emails(user, now=now) == 1
    assert notifications.send_pending_notification_emails(user, now=now) == 0
    row.refresh_from_db()
    assert row.emailed_at is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["student@example.com"]
    assert "https://ontrack.example/study/?course=cs101" in mail.outbox[0].body
    assert mail.outbox[0].subject == "OnTrack | Time to study"
    assert len(mail.outbox[0].alternatives) == 1
    html, mime_type = mail.outbox[0].alternatives[0]
    assert mime_type == "text/html"
    assert "OnTrack" in html
    assert "Start guided study" in html
    assert 'href="https://ontrack.example/study/?course=cs101"' in html


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_daily_email_does_not_send_missed_days_in_a_burst(user):
    UserSettings.objects.create(
        user=user, notifications_enabled=True, timezone="America/New_York",
    )
    Notification.objects.create(
        user=user, notification_key="study_reminder:2026-08-30",
        kind=Notification.KIND_STUDY_REMINDER, title="Old reminder",
    )
    Notification.objects.create(
        user=user, notification_key="study_reminder:2026-08-31",
        kind=Notification.KIND_STUDY_REMINDER, title="Today's reminder",
    )
    now = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)

    assert notifications.send_pending_notification_emails(user, now=now) == 1
    assert notifications.send_pending_notification_emails(user, now=now) == 0
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "OnTrack | Today's reminder"


def test_cora_notification_links_to_saved_conversation_and_deduplicates(user):
    first = notifications.create_cora_message_notification(
        user, "cs101", "session-42", "Here is your grounded answer.", request_id="request-7",
    )
    second = notifications.create_cora_message_notification(
        user, "cs101", "session-42", "Here is your grounded answer.", request_id="request-7",
    )

    assert first.pk == second.pk
    assert first.kind == Notification.KIND_CORA_MESSAGE
    assert first.action_url == "/cora/?course=cs101&session=session-42"
    assert Notification.objects.filter(user=user).count() == 1


def test_email_preference_disables_delivery(user):
    UserSettings.objects.create(user=user, notifications_enabled=False)
    Notification.objects.create(
        user=user, notification_key="study:disabled", kind=Notification.KIND_STUDY_REMINDER,
        title="Time to study", action_url="/study/",
    )
    assert notifications.send_pending_notification_emails(user) == 0


def test_read_notifications_disappear_but_are_retained(user):
    UserSettings.objects.create(user=user, notifications_enabled=False)
    row = Notification.objects.create(
        user=user, notification_key="read:test", kind=Notification.KIND_CORA_MESSAGE,
        title="Cora replied", action_url="/cora/",
    )

    result = notifications.mark_notifications_read(user, ids=[row.pk])

    assert result == {"notifications": [], "unread_count": 0}
    row.refresh_from_db()
    assert row.read is True
