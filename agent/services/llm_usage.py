"""Per-user daily cap and per-model token/cost accounting for Anthropic-calling
endpoints. The cap is resolved from tier via entitlements.daily_request_limit()
and checked once, pre-request, at AIAPIView.initial() in views.py — the single
call site every Anthropic-calling view goes through; nothing else should
inline that check. Token/cost accounting is recorded post-request instead
(token counts only exist once a response comes back — see client.create_message,
the single call site every Anthropic-calling service goes through for that),
so it shares the same LlmUsage row but not the same choke point. Reversed
from this module's earlier "not worth building for a one-semester pilot"
stance: cost-per-student-month decides whether OnTrack can run as a business,
and it can't be reconstructed after the fact once the pilot has started."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled

from .entitlements import daily_request_limit

# USD per 1M tokens. Filled in at pilot launch from published Anthropic
# pricing for the model IDs in client.py's MODEL_DEFAULT/MODEL_HAIKU/
# MODEL_RUBRIC_CRITIQUE — these are NOT auto-updated when those model IDs
# change or when Anthropic revises pricing. Review manually before trusting
# a cost figure derived from this table for a real financial decision.
PRICE_PER_MILLION_TOKENS = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Returns None (never 0) for a model missing from PRICE_PER_MILLION_TOKENS
    — an unpriced model's cost is unknown, not free, and this table isn't kept
    in sync automatically when client.py's model constants change."""
    price = PRICE_PER_MILLION_TOKENS.get(model)
    if price is None:
        return None
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


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


def record_usage(user, model: str, input_tokens: int, output_tokens: int) -> None:
    """Adds one response's input/output token counts, under `model`, to
    today's LlmUsage row for `user` — the same row check_and_increment's
    request `count` lives on, extended with a `tokens` JSON map keyed by
    model name. Called from client.create_message() after every Anthropic
    response; unlike check_and_increment, callers are expected to catch and
    log any exception here rather than let it interrupt an already-completed
    request (see that module's docstring) — this function itself still
    raises on failure so that contract is enforced at the call site, not
    silently satisfied here."""
    from agent.models import LlmUsage

    today = timezone.localdate()
    with transaction.atomic():
        row, _ = LlmUsage.objects.select_for_update().get_or_create(
            user=user, date=today, defaults={"count": 0, "tokens": {}},
        )
        totals = dict(row.tokens.get(model, {"input": 0, "output": 0}))
        totals["input"] = totals.get("input", 0) + int(input_tokens)
        totals["output"] = totals.get("output", 0) + int(output_tokens)
        row.tokens = {**row.tokens, model: totals}
        row.save(update_fields=["tokens"])
