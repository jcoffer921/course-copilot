"""Per-user daily cap on Anthropic-calling endpoints, resolved from tier via
entitlements.daily_request_limit(). Counts requests, not tokens — token
accounting isn't worth building for a one-semester pilot. AIAPIView.initial()
in views.py is the single call site every Anthropic-calling view goes
through; nothing else should inline this check."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled

from .entitlements import daily_request_limit


def check_and_increment(user) -> None:
    """Raises rest_framework.exceptions.Throttled (-> HTTP 429) if the
    user has already hit their tier's cap for today; otherwise records
    this request and returns. Deliberately does not catch database errors
    — an unreachable usage table must fail loudly, not silently let
    requests through uncounted."""
    from agent.models import LlmUsage, UserSettings

    today = timezone.localdate()
    tier = UserSettings.objects.get_or_create(user=user)[0].tier
    limit = daily_request_limit(tier)

    with transaction.atomic():
        row, _ = LlmUsage.objects.select_for_update().get_or_create(user=user, date=today, defaults={"count": 0})
        if row.count >= limit:
            raise Throttled(detail=f"Daily AI request limit ({limit}) reached. Resets at midnight.")
        row.count += 1
        row.save(update_fields=["count"])
