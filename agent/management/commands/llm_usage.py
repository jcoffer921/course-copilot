from django.core.management.base import BaseCommand
from django.utils import timezone

from agent.models import LlmUsage


class Command(BaseCommand):
    help = "Prints today's per-user Anthropic request usage — spend visibility without opening the admin."

    def handle(self, *args, **options):
        today = timezone.localdate()
        rows = LlmUsage.objects.filter(date=today).select_related("user").order_by("-count")

        if not rows:
            self.stdout.write(f"No LLM requests recorded for {today}.")
            return

        for row in rows:
            self.stdout.write(f"{row.user.email or row.user.username}: {row.count}")
