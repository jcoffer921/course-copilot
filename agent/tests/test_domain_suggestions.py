"""
Live tests against the real Anthropic API for domain_suggestions.py.

Requires ANTHROPIC_API_KEY and courses/cs101 to already have syllabus.json —
skipped automatically if either precondition is missing.
"""

import os

import pytest

from agent.services import storage
from agent.services.domain_suggestions import suggest_domains

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires a live ANTHROPIC_API_KEY",
)

COURSE_ID = "cs101"


@pytest.fixture(autouse=True, scope="module")
def _require_fixture_data():
    if storage.read_syllabus(COURSE_ID) is None:
        pytest.skip(f"courses/{COURSE_ID}/syllabus.json not found — run extract_syllabus first")


async def test_suggest_domains_returns_plausible_real_domains():
    domains = await suggest_domains(COURSE_ID)

    assert domains
    assert all(isinstance(d, str) and d for d in domains)
    assert all("wikipedia.org" not in d for d in domains)


async def test_suggest_domains_never_writes_anything():
    before = storage.read_trusted_domains(COURSE_ID)

    await suggest_domains(COURSE_ID)

    after = storage.read_trusted_domains(COURSE_ID)
    assert before == after
