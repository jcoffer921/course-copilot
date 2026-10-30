"""Short-lived server-side state for the faculty planning chat.

A student's details, the conversation, and the draft plan are kept in the cache under one key per
faculty member, with a sliding idle expiry, and never in the database (not an application table, not
`django_session`). The default cache is per process; running more than one worker needs a shared
cache backend in `CACHES`, otherwise a request on another worker simply sees no state.
"""

from django.conf import settings
from django.core.cache import cache

DEFAULT_TTL_SECONDS = 30 * 60


def ttl_seconds() -> int:
    return int(getattr(settings, "FACULTY_PLAN_STATE_TTL_SECONDS", DEFAULT_TTL_SECONDS))


def _key(user) -> str:
    return f"faculty-plan-state:{user.pk}"


def read(user) -> dict | None:
    return cache.get(_key(user))


def write(user, state: dict) -> None:
    """Store `state` and restart the idle window."""
    cache.set(_key(user), state, ttl_seconds())


def clear(user) -> None:
    cache.delete(_key(user))
