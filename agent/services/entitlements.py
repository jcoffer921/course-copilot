"""Maps a UserSettings.tier to what that tier unlocks. The single place tier
gating lives — when pilot and full diverge, this is the only function that
changes; nothing else should inline a tier or access_status check."""

FEATURES = ("chat", "quiz", "flashcards", "grades", "deadlines", "calendar_sync", "critique")


def features_for_tier(tier: str) -> set:
    """Both tiers unlock everything today. Kept as a real per-tier mapping
    (not a shortcut constant) so a future split only touches this body."""
    return set(FEATURES)


DAILY_REQUEST_LIMIT = 100


def daily_request_limit(tier: str) -> int:
    """Requests-per-calendar-day cap on Anthropic-calling endpoints, by
    tier (see agent/services/llm_usage.py — the single place this is
    checked). Both tiers share the same cap today."""
    return DAILY_REQUEST_LIMIT
