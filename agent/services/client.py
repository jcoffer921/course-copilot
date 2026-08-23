"""
Shared Anthropic client init. Every service that calls the API imports from
here instead of instantiating AsyncAnthropic() itself, so the "missing API
key -> fail loudly with a clear message, not a raw SDK error" check and
per-task-type model selection live in exactly one place.
"""

import os

from anthropic import AsyncAnthropic

# Sonnet is the default for extraction, grounded Q&A, and assessment-grade quiz generation.
# Haiku is used for cheap data gathering and quick definition flashcards.
# Opus is reserved for rubric critique mode (not built yet) — that mode
# trades cost for reasoning quality, per CLAUDE.md's stack notes.
MODEL_DEFAULT = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5"
MODEL_RUBRIC_CRITIQUE = "claude-opus-4-6"


def get_client() -> AsyncAnthropic:
    """Returns a configured AsyncAnthropic client, or raises a clear
    ValueError (not a raw SDK connection error) if ANTHROPIC_API_KEY is unset."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    return AsyncAnthropic()
