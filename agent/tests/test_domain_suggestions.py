"""
Live tests against the real Anthropic API for domain_suggestions.py.

Requires ANTHROPIC_API_KEY and courses/cs101 to already have syllabus.json —
skipped automatically if either precondition is missing.
"""

import os

import pytest

from agent.services import storage
from agent.services.domain_suggestions import suggest_domains

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="requires a live ANTHROPIC_API_KEY",
    ),
    pytest.mark.django_db,
]

COURSE_ID = "cs101"


@pytest.fixture
def _course_user(django_user_model):
    user = django_user_model.objects.create_user(username="domain-suggestions-user", email="domain-suggestions-user@example.com")
    if storage.read_syllabus(COURSE_ID, user) is None:
        pytest.skip(f"courses/{COURSE_ID}/syllabus.json not found — run extract_syllabus first")
    return user


async def test_suggest_domains_returns_plausible_real_domains(_course_user):
    domains = await suggest_domains(COURSE_ID, _course_user)

    assert domains
    assert all(isinstance(d, str) and d for d in domains)
    assert all("wikipedia.org" not in d for d in domains)


async def test_suggest_domains_never_writes_anything(_course_user):
    before = storage.read_trusted_domains(COURSE_ID, _course_user)

    await suggest_domains(COURSE_ID, _course_user)

    after = storage.read_trusted_domains(COURSE_ID, _course_user)
    assert before == after
