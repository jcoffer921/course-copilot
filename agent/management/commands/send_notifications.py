from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from agent.services import notifications, operations


class Command(BaseCommand):
    help = "Generate today's OnTrack reminder and send at most one study email per enabled user."

    def handle(self, *args, **options):
        generated = sent = 0
        try:
            users = get_user_model().objects.filter(settings__notifications_enabled=True).iterator()
            for user in users:
                generated += notifications.refresh_notifications(user)
                sent += notifications.send_pending_notification_emails(user)
        except Exception as exc:
            operations.record_heartbeat("notification_delivery", status="error", detail=type(exc).__name__)
            raise
        operations.record_heartbeat("notification_delivery", detail=f"generated={generated}; emailed={sent}")
        self.stdout.write(self.style.SUCCESS(f"Generated {generated}; emailed {sent}."))
