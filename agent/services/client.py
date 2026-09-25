"""
Shared Anthropic client init. Every service that calls the API imports from
here instead of instantiating AsyncAnthropic() itself, so the "missing API
key -> fail loudly with a clear message, not a raw SDK error" check and
per-task-type model selection live in exactly one place.
"""

import logging
import os

from anthropic import AsyncAnthropic
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

# Sonnet is the default for extraction, grounded Q&A, and assessment-grade quiz generation.
# Haiku is used for cheap data gathering and quick definition flashcards.
# Opus is reserved for rubric critique mode (not built yet) — that mode
# trades cost for reasoning quality, per CLAUDE.md's stack notes.
MODEL_DEFAULT = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"
MODEL_RUBRIC_CRITIQUE = "claude-opus-4-6"

# Named aliases for Cora's capability routing (agent/services/cora_skills/) —
# new capabilities reference CORA_MODELS["fast"/"reasoning"/"critique"]
# instead of importing the raw constants above, so a future model swap is a
# one-line change here rather than a hunt across every capability file.
CORA_MODELS = {
    "fast": MODEL_HAIKU,
    "reasoning": MODEL_DEFAULT,
    "critique": MODEL_RUBRIC_CRITIQUE,
}


def get_client() -> AsyncAnthropic:
    """Returns a configured AsyncAnthropic client, or raises a clear
    ValueError (not a raw SDK connection error) if ANTHROPIC_API_KEY is unset."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    return AsyncAnthropic()


async def create_message(client: AsyncAnthropic, user, **kwargs):
    """Every service call site should call this instead of
    `client.messages.create(**kwargs)` directly, so per-model token/cost
    accounting (agent/services/llm_usage.py) lives in exactly one place —
    the same rationale this module's docstring gives for get_client() itself.

    Takes an already-resolved `client` rather than resolving one itself:
    every existing test fakes a model call via
    `monkeypatch.setattr(<module>, "get_client", lambda: fake_client)` (see
    agent/services/intent_router.py::classify's docstring for the
    established precedent) — resolving our own client here would bypass
    that fake entirely and start hitting the real API in tests.

    Token counts only exist once the response comes back, so this can't be
    the same pre-request choke point AIAPIView.initial() uses for the daily
    request cap (see llm_usage.check_and_increment). Recording usage here is
    purely observational: a failure must never break a request that already
    succeeded, so it's logged and swallowed, never raised to the caller."""
    response = await client.messages.create(**kwargs)
    try:
        from . import llm_usage

        await sync_to_async(llm_usage.record_usage)(
            user, kwargs.get("model"), response.usage.input_tokens, response.usage.output_tokens,
        )
    except Exception:
        logger.exception("llm_usage.record_usage failed", extra={"user_id": getattr(user, "pk", None)})
    return response
