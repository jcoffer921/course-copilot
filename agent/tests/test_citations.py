import json
import uuid
from pathlib import Path

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from agent.models import CourseMaterial
from agent.services import ask, citations, sessions, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="citation-owner")


@pytest.fixture
def api_client(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    client.user = owner
    return client


def _seed_course(user, course_id="cs101", *, unsafe_excerpt=False):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": "Computer Science",
        "dates": [],
        "grading": [],
        "topics": ["Recursion"],
    }, user)
    text = (
        "<script>alert('course')</script> A base case stops recursive calls. "
        + ("x" * 500 if unsafe_excerpt else "A recursive step reduces the problem.")
    )
    storage.write_notes(course_id, "lecture-01", {
        "lecture_id": "lecture-01",
        "source": "notes",
        "date": "2026-08-25",
        "topics": ["Recursion"],
        "chunks": [{"id": "recursion-base", "topic": "Recursion", "text": text}],
    }, user)
    material = CourseMaterial.objects.create(
        user=user,
        course_id=course_id,
        original_filename="recursion-notes.txt",
        material_type=CourseMaterial.TYPE_NOTES,
        source_key="lecture-01",
        storage_key=f"{uuid.uuid4().hex}.txt",
        size_bytes=len(text),
        processing_status=CourseMaterial.STATUS_READY,
        review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
    )
    return material


@pytest.mark.django_db
def test_structured_citation_resolves_to_exact_owned_chunk_and_bounded_excerpt(
    isolated_courses_dir, owner,
):
    material = _seed_course(owner, unsafe_excerpt=True)

    source = citations.resolve_citations(
        owner, "cs101", ["lecture-01"], "What stops recursion?", "The base case.",
    )[0]

    assert source == citations.preview_source(owner, "cs101", source)
    assert source["material_id"] == str(material.material_id)
    assert source["material_type"] == "notes"
    assert source["lecture_id"] == "lecture-01"
    assert source["chunk_id"] == "recursion-base"
    assert source["title"] == "recursion-notes.txt"
    assert len(source["excerpt"]) <= citations.MAX_EXCERPT_CHARS
    assert source["excerpt"].endswith("…")
    assert "<script>" in source["excerpt"]  # Kept as text; the UI binding escapes it.


@pytest.mark.django_db
def test_source_preview_endpoint_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    _seed_course(api_client.user)
    source = citations.resolve_citations(
        api_client.user, "cs101", ["lecture-01"], "base case", "base case",
    )[0]
    session = sessions.create_session("cs101", user=api_client.user)
    sessions.append_message("cs101", session["session_id"], "user", "What is a base case?", user=api_client.user)
    sessions.append_message(
        "cs101", session["session_id"], "assistant", "It stops recursion.",
        sources=[source], grounded=True, user=api_client.user,
    )
    preview_request = {
        **source, "session_id": session["session_id"], "message_index": 1, "citation_index": 0,
    }

    response = api_client.post("/api/courses/cs101/sources/preview/", preview_request, format="json")

    assert response.status_code == 200
    assert response.data["source"]["chunk_id"] == "recursion-base"

    other = django_user_model.objects.create_user(username="citation-other")
    _seed_course(other)
    other_client = APIClient()
    other_client.force_authenticate(user=other)
    denied = other_client.post("/api/courses/cs101/sources/preview/", preview_request, format="json")
    assert denied.status_code == 404
    assert "recursion-notes.txt" not in str(denied.data)

    mixed = dict(preview_request, message_index=0)
    assert api_client.post("/api/courses/cs101/sources/preview/", mixed, format="json").status_code == 404


@pytest.mark.django_db
def test_source_preview_rejects_citation_from_another_saved_answer(isolated_courses_dir, api_client):
    _seed_course(api_client.user)
    source = citations.resolve_citations(api_client.user, "cs101", ["lecture-01"], "base case", "base case")[0]
    session = sessions.create_session("cs101", user=api_client.user)
    sessions.append_message("cs101", session["session_id"], "user", "Question", user=api_client.user)
    sessions.append_message("cs101", session["session_id"], "assistant", "Unsupported", sources=[], grounded=False, user=api_client.user)

    forged = {**source, "session_id": session["session_id"], "message_index": 1, "citation_index": 0}

    assert api_client.post("/api/courses/cs101/sources/preview/", forged, format="json").status_code == 404


@pytest.mark.django_db
def test_forged_chunk_and_unapproved_web_sources_never_resolve(isolated_courses_dir, owner):
    _seed_course(owner)
    source = citations.resolve_citations(
        owner, "cs101", ["lecture-01"], "base case", "base case",
    )[0]
    source["chunk_id"] = "not-an-owned-chunk"

    with pytest.raises(citations.CitationNotFoundError):
        citations.preview_source(owner, "cs101", source)
    source = citations.resolve_citations(
        owner, "cs101", ["lecture-01"], "base case", "base case",
    )[0]
    source["material_type"] = "slides"
    with pytest.raises(citations.CitationNotFoundError):
        citations.preview_source(owner, "cs101", source)
    with pytest.raises(ValueError, match="unavailable or unapproved"):
        citations.resolve_citations(
            owner, "cs101", ["https://attacker.example/private"], "question", "answer",
        )


@pytest.mark.django_db
def test_approved_web_source_is_labeled_and_never_claims_to_be_uploaded(isolated_courses_dir, owner):
    _seed_course(owner)
    storage.write_trusted_domains("cs101", ["docs.python.org"], owner)

    source = citations.resolve_citations(
        owner, "cs101", ["https://docs.python.org/3/"], "Python docs", "Python docs",
    )[0]

    assert source["material_type"] == "web"
    assert source["material_id"].startswith("web-")
    assert source["lecture_id"] is None
    assert source["chunk_id"] is None
    assert source["url"] == "https://docs.python.org/3/"
    assert "uploaded" not in source["excerpt"].lower()


@pytest.mark.django_db
def test_legacy_string_sources_remain_readable(isolated_courses_dir, api_client):
    _seed_course(api_client.user)
    session = sessions.create_session("cs101", user=api_client.user)
    sessions.append_message("cs101", session["session_id"], "user", "What is recursion?", user=api_client.user)
    sessions.append_message(
        "cs101", session["session_id"], "assistant", "A recursive definition refers to itself.",
        sources=["lecture-01"], grounded=True, user=api_client.user,
    )

    response = api_client.get(f"/api/courses/cs101/sessions/{session['session_id']}/")

    assert response.status_code == 200
    assert response.data["messages"][1]["sources"] == ["lecture-01"]


@pytest.mark.django_db
def test_recalled_conversation_citation_opens_the_exact_owned_message(isolated_courses_dir, owner):
    _seed_course(owner)
    prior = sessions.create_session("cs101", user=owner)
    sessions.append_message(
        "cs101", prior["session_id"], "user",
        "Explain recursion with a staircase example.", user=owner,
    )

    source = citations.resolve_citations(
        owner, "cs101", ["recalled_conversations"],
        "Remember my recursion example?", "You preferred a staircase example.",
    )[0]
    preview = citations.preview_source(owner, "cs101", source)

    assert source["material_id"].startswith("ontrack-conversation-")
    assert preview["excerpt"] == "Explain recursion with a staircase example."


class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_TextBlock(text)]


class _Messages:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class _Client:
    def __init__(self, result):
        self.messages = _Messages(result)


@pytest.mark.django_db(transaction=True)
async def test_retry_request_id_returns_same_exchange_without_duplicate_user_message(
    isolated_courses_dir, owner, monkeypatch,
):
    await sync_to_async(_seed_course)(owner)
    session = await sync_to_async(sessions.create_session)("cs101", user=owner)
    fake = _Client(_Response(json.dumps({"answer": "Not in the notes.", "grounded": False, "sources": []})))
    monkeypatch.setattr(ask, "get_client", lambda: fake)
    request_id = str(uuid.uuid4())

    first = await ask.ask_async(
        "cs101", "What is quantum gravity?", session_id=session["session_id"],
        client_request_id=request_id, user=owner,
    )
    second = await ask.ask_async(
        "cs101", "What is quantum gravity?", session_id=session["session_id"],
        client_request_id=request_id, user=owner,
    )
    saved = await sync_to_async(sessions.get_session)("cs101", session["session_id"], user=owner)

    assert second == first
    assert len(fake.messages.calls) == 1
    assert [message["role"] for message in saved["messages"]] == ["user", "assistant"]
    assert saved["title"] == "What is quantum gravity?"


@pytest.mark.django_db
def test_conversations_can_be_renamed_and_explicitly_deleted(isolated_courses_dir, api_client):
    _seed_course(api_client.user)
    created = api_client.post("/api/courses/cs101/sessions/")
    session_id = created.data["session_id"]

    renamed = api_client.patch(
        f"/api/courses/cs101/sessions/{session_id}/", {"title": "Exam review"}, format="json",
    )
    refused = api_client.delete(
        f"/api/courses/cs101/sessions/{session_id}/", {"confirmation": "no"}, format="json",
    )
    deleted = api_client.delete(
        f"/api/courses/cs101/sessions/{session_id}/", {"confirmation": "DELETE"}, format="json",
    )

    assert renamed.status_code == 200
    assert renamed.data["title"] == "Exam review"
    assert refused.status_code == 400
    assert deleted.status_code == 204
    assert api_client.get(f"/api/courses/cs101/sessions/{session_id}/").status_code == 404


@pytest.mark.django_db
def test_citation_for_chunk_resolves_exact_chunk_for_quiz_review(isolated_courses_dir, owner):
    material = _seed_course(owner)

    citation = citations.citation_for_chunk(owner, "cs101", "lecture-01", "recursion-base")

    assert citation["material_id"] == str(material.material_id)
    assert citation["chunk_id"] == "recursion-base"
    assert citation["lecture_id"] == "lecture-01"


@pytest.mark.django_db
def test_citation_for_chunk_returns_none_for_unowned_or_missing_chunk(isolated_courses_dir, owner, django_user_model):
    _seed_course(owner)

    assert citations.citation_for_chunk(owner, "cs101", "lecture-01", "not-a-real-chunk") is None
    assert citations.citation_for_chunk(owner, "cs101", "", "") is None

    other = django_user_model.objects.create_user(username="citation-chunk-other")
    assert citations.citation_for_chunk(other, "cs101", "lecture-01", "recursion-base") is None


def test_source_excerpt_is_rendered_through_escaped_template_binding():
    root = Path(__file__).resolve().parents[2]
    template = (root / "agent/templates/agent/cora.html").read_text(encoding="utf-8")
    controller = (root / "agent/static/agent/js/cora.js").read_text(encoding="utf-8")

    assert 'id="cora-source-excerpt"' in template
    assert "sourceExcerpt.textContent = source.excerpt" in controller
    assert "sourceExcerpt.innerHTML" not in controller


def test_model_source_labels_are_strictly_bounded():
    with pytest.raises(ValueError, match="at most|more than"):
        citations.validate_source_labels(["syllabus"] * (citations.MAX_CITATIONS + 1))
    with pytest.raises(ValueError, match="invalid source label"):
        citations.validate_source_labels([{"material_id": "forged"}])
