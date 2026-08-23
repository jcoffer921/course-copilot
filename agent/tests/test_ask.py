"""
Live tests against the real Anthropic API for ask.py's grounding behavior —
the most safety-critical script in the project (CLAUDE.md's first
non-negotiable: never fabricate course content).

Requires ANTHROPIC_API_KEY and courses/cs101 to already have syllabus.json
and the lecture05 (recursion) notes chunked — skipped automatically if
either precondition is missing.
"""

import os

import pytest

from agent.services import storage
from agent.services.ask import ask_async

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires a live ANTHROPIC_API_KEY",
)

COURSE_ID = "cs101"


@pytest.fixture(autouse=True, scope="module")
def _require_fixture_data():
    if storage.read_syllabus(COURSE_ID) is None:
        pytest.skip(f"courses/{COURSE_ID}/syllabus.json not found — run extract_syllabus first")
    if not storage.read_notes(COURSE_ID):
        pytest.skip(f"courses/{COURSE_ID}/notes/ is empty — run chunk_notes first")


async def test_answerable_question_is_grounded():
    """A question directly answerable from the chunked lecture notes should
    get a correct, grounded answer citing the lecture as its source."""
    result = await ask_async(COURSE_ID, "What are the two required parts of a recursive function?")

    assert result["grounded"] is True
    assert "lecture05" in result["sources"]
    answer_lower = result["answer"].lower()
    assert "base case" in answer_lower
    assert "recursive case" in answer_lower


async def test_uncovered_question_is_not_fabricated():
    """A question about something this course never covers at all (this is
    an intro Python course; C/pointers never comes up anywhere) must be
    flagged as not grounded, not answered from general knowledge."""
    result = await ask_async(
        COURSE_ID,
        "What textbook chapter covers pointers and manual memory management in C?",
    )

    assert result["grounded"] is False
    assert result["sources"] == []


async def test_adjacent_topic_is_not_blurred_with_covered_topic():
    """The lecture 5 notes mention memoization BY NAME, but explicitly as
    something NOT covered in this course, while discussing recursion and
    Fibonacci. A model that blurs "the notes mention this word" with "the
    notes teach this concept" would incorrectly explain memoization as if
    it were this course's material — exactly the failure mode this test
    exists to catch."""
    result = await ask_async(
        COURSE_ID,
        "Explain how memoization works and show me how to add it to the "
        "fibonacci function from lecture 5.",
    )

    assert result["grounded"] is False


async def test_reference_grounds_when_syllabus_and_notes_dont_cover_it():
    """A question only a course's uploaded reference doc answers (not
    covered by syllabus/notes) should come back grounded, citing the
    reference_id — not 'syllabus' or a lecture_id."""
    references = storage.read_references(COURSE_ID)
    if not references:
        pytest.skip(f"courses/{COURSE_ID}/references/ is empty — upload a reference doc first")

    result = await ask_async(COURSE_ID, "What does the uploaded reference document cover?")

    assert result["grounded"] is True
    assert any(r["reference_id"] in result["sources"] for r in references)


async def test_web_search_grounds_when_domain_approved_and_course_material_silent():
    """A question genuinely outside cs101's notes/syllabus, but inside an
    approved domain's real coverage, should come back grounded with a real
    cited URL from the approved list."""
    approved = storage.read_trusted_domains(COURSE_ID)
    if not approved:
        pytest.skip(
            f"no trusted_domains.json approved for {COURSE_ID} — run "
            f"`manage.py domains {COURSE_ID} --approve ...` first"
        )

    result = await ask_async(
        COURSE_ID,
        "According to the official Python documentation, what does the walrus operator (:=) do?",
    )

    assert result["grounded"] is True
    web_sources = [s for s in result["sources"] if s.startswith("http")]
    assert web_sources
    assert any(domain in src for domain in approved for src in web_sources)


async def test_identity_question_answers_as_cora():
    """Asking who the assistant is should be answered in character as Cora,
    still inside the required JSON envelope — proving the identity clause
    doesn't leak outside the JSON contract or corrupt grounded/sources
    semantics for a question that isn't about course material."""
    result = await ask_async(COURSE_ID, "Who are you and what do you do?")

    assert "cora" in result["answer"].lower()
    assert result["grounded"] is False
    assert result["sources"] == []
