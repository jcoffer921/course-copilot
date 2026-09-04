import json

import pytest
from asgiref.sync import sync_to_async

from agent.services import document_summarizer, storage

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _seed_lecture(course_id, user, lecture_id="lecture-1", text="Recursion breaks a problem into smaller versions of itself."):
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "source": "notes", "topics": ["Recursion"],
        "chunks": [{"id": "chunk-1", "topic": "Recursion", "text": text}],
    }, user)


def _seed_reference(course_id, user, reference_id="ref-1", title="Textbook Ch. 4", text="Reference content about loops."):
    storage.write_reference(course_id, reference_id, {
        "reference_id": reference_id, "title": title, "source_filename": "ch4.pdf", "text": text,
    }, user)


async def test_quick_summary_uses_the_fast_model(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="quick-summary-owner")
    _seed_lecture("cs101", user)
    fake = _FakeClient(_FakeResponse(json.dumps({"summary": "- Recursion breaks problems down."})))
    monkeypatch.setattr(document_summarizer, "get_client", lambda: fake)

    result = await document_summarizer.summarize("cs101", lecture_id="lecture-1", depth="quick", user=user)

    assert result["depth"] == "quick"
    assert result["source_id"] == "lecture-1"
    assert "Recursion" in result["summary"]
    assert fake.messages.calls[0]["model"] == document_summarizer.CORA_MODELS["fast"]


async def test_deep_summary_uses_the_reasoning_model(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="deep-summary-owner")
    _seed_lecture("cs101", user)
    payload = json.dumps({
        "key_concepts": ["Recursion"],
        "definitions": [{"term": "Base case", "definition": "The condition that stops recursion."}],
        "relationships": ["Recursive calls depend on reaching a base case."],
        "likely_testable": ["Writing a base case for a recursive function."],
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(document_summarizer, "get_client", lambda: fake)

    result = await document_summarizer.summarize("cs101", lecture_id="lecture-1", depth="deep", user=user)

    assert result["depth"] == "deep"
    assert result["key_concepts"] == ["Recursion"]
    assert result["definitions"] == [{"term": "Base case", "definition": "The condition that stops recursion."}]
    assert result["relationships"]
    assert result["likely_testable"]


async def test_explicit_reference_id_resolves_its_own_title_and_text(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="reference-summary-owner")
    _seed_reference("cs101", user)
    fake = _FakeClient(_FakeResponse(json.dumps({"summary": "- Covers loop constructs."})))
    monkeypatch.setattr(document_summarizer, "get_client", lambda: fake)

    result = await document_summarizer.summarize("cs101", reference_id="ref-1", depth="quick", user=user)

    assert result["source_id"] == "ref-1"
    assert result["title"] == "Textbook Ch. 4"
    sent_prompt = fake.messages.calls[0]["messages"][0]["content"]
    assert "Reference content about loops." in sent_prompt


async def test_no_target_given_falls_back_to_most_recent_lecture(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="latest-lecture-owner")
    _seed_lecture("cs101", user, lecture_id="lecture-1", text="Early lecture content.")
    _seed_lecture("cs101", user, lecture_id="lecture-2", text="Most recent lecture content.")
    fake = _FakeClient(_FakeResponse(json.dumps({"summary": "- Recap."})))
    monkeypatch.setattr(document_summarizer, "get_client", lambda: fake)

    result = await document_summarizer.summarize("cs101", depth="quick", user=user)

    assert result["source_id"] == "lecture-2"


async def test_raises_when_course_has_no_notes_or_references(django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="no-material-for-summary-owner")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    }, user)

    with pytest.raises(document_summarizer.NoTargetDocumentError):
        await document_summarizer.summarize("cs101", depth="quick", user=user)


async def test_unknown_lecture_id_raises_even_when_other_notes_exist(django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="unknown-lecture-owner")
    _seed_lecture("cs101", user, lecture_id="lecture-1")

    with pytest.raises(document_summarizer.NoTargetDocumentError):
        await document_summarizer.summarize("cs101", lecture_id="does-not-exist", depth="quick", user=user)
