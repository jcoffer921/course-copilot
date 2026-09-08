"""Integration tests for ask.py's intent-routing layer (Phase 2/5 of the
Cora capability refactor): the free deterministic regex checks still run
before intent_router is ever called, a classifier failure/course_qa result
falls through to the existing grounded pipeline completely unchanged, and
each new routed intent (general_assistant, study_planner, mastery_analyzer,
document_summary_quick, quiz_or_flashcards) dispatches to its capability and
comes back through the same {answer, grounded, sources} envelope the
frontend already expects.
"""

import json

import pytest
from asgiref.sync import sync_to_async

from agent.models import CourseMaterial
from agent.services import ask, document_summarizer, intent_router, mastery, mastery_analyzer, material_files, quiz, storage, study_planner

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, name, tool_input):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "end_turn"


def _text_response(text):
    return _FakeResponse([_FakeTextBlock(text)])


def _classify_response(intent):
    return _FakeResponse([_FakeToolUseBlock(
        "classify_intent", {"intent": intent, "requires_course_context": True},
    )])


class _SequencedMessages:
    """Returns each response in order, then repeats the last one — lets a
    single fake client stand in for both the intent_router classification
    call and whatever call(s) come after it in the same ask_async request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


class _SequencedClient:
    def __init__(self, responses):
        self.messages = _SequencedMessages(responses)


def _seed_course(course_id, user):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": [], "grading": [], "topics": ["Recursion"],
    }, user)


def _seed_notes(course_id, user, lecture_id="lecture-1"):
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "source": "notes", "topics": ["Recursion"],
        "chunks": [{"id": "chunk-1", "topic": "Recursion", "text": "Recursion breaks a problem into smaller versions of itself."}],
    }, user)


def _seed_grounded_course_for_recommendations(course_id, user, topics=("Recursion",)):
    # study_planner reads recommendations.rank_recommendations(), which only
    # surfaces a topic once it has a CourseMaterial-backed chunk — this is
    # the same fixture shape test_study_planner.py and test_recommendations.py use.
    syllabus = {"course_id": course_id, "course_name": course_id.upper(), "dates": [], "grading": [], "topics": list(topics)}
    storage.write_syllabus(course_id, syllabus, user)
    storage_key = material_files.object_storage.save(user, course_id, ".pdf", b"%PDF-test")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename=f"{course_id}-syllabus.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS, source_key="syllabus",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_CONFIRMED,
        storage_key=storage_key, size_bytes=9, content_type="application/pdf", extracted_data=syllabus,
    )
    lecture_id = f"{course_id}-content"
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "topics": list(topics),
        "chunks": [{"id": f"topic-{i}", "topic": t, "text": f"Processed content about {t}."} for i, t in enumerate(topics, start=1)],
    }, user)
    notes_key = material_files.object_storage.save(user, course_id, ".docx", b"course-content")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="content.docx",
        material_type=CourseMaterial.TYPE_NOTES, source_key=lecture_id,
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=notes_key, size_bytes=14,
    )


async def test_deadline_request_never_calls_intent_router(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="deadline-bypass-owner")
    await sync_to_async(_seed_course)("cs101", user)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("intent_router.classify should not be called for a deadline-shaped request")

    monkeypatch.setattr(intent_router, "classify", _fail_if_called)
    fake = _SequencedClient([_text_response(json.dumps({
        "is_deadline_request": True, "missing": [], "deadlines": [], "message": "ok",
    }))])
    monkeypatch.setattr(ask, "get_client", lambda: fake)

    result = await ask.ask_async("cs101", "add homework 4 due october 12, 2026 at 11:59pm", user=user)

    assert result["grounded"] is True


async def test_save_site_request_never_calls_intent_router(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="save-site-bypass-owner")
    await sync_to_async(_seed_course)("cs101", user)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("intent_router.classify should not be called for a save-site request")

    monkeypatch.setattr(intent_router, "classify", _fail_if_called)

    def _fail_get_client():
        raise AssertionError("saving a site address should not call the model")

    monkeypatch.setattr(ask, "get_client", _fail_get_client)

    result = await ask.ask_async("cs101", "save https://example.edu/book as course book", user=user)

    assert result["grounded"] is True


async def test_classifier_course_qa_fallback_falls_through_unchanged(monkeypatch, django_user_model, isolated_courses_dir):
    # intent_router.classify() itself already guarantees it never raises —
    # any internal failure resolves to {"intent": "course_qa", ...}
    # (test_intent_router.py covers that contract directly). This confirms
    # ask_async's OWN behavior when handed that safe fallback: fall through
    # to the existing grounded pipeline exactly as if intent_router didn't
    # exist, using only the one grounded-answer call (no dispatch branch).
    user = await sync_to_async(django_user_model.objects.create_user)(username="classifier-fallback-owner")
    await sync_to_async(_seed_course)("cs101", user)

    async def _fallback(*args, **kwargs):
        return {"intent": "course_qa", "requires_course_context": True}

    monkeypatch.setattr(intent_router, "classify", _fallback)
    canned = json.dumps({"answer": "Not covered.", "grounded": False, "sources": []})
    fake = _SequencedClient([_text_response(canned)])
    monkeypatch.setattr(ask, "get_client", lambda: fake)

    result = await ask.ask_async("cs101", "what is the capital of France?", user=user)

    assert result["answer"] == "Not covered."
    assert result["grounded"] is False
    assert len(fake.messages.calls) == 1
    assert result["grounded"] is False


async def test_general_assistant_intent_skips_full_context_and_replies_cheaply(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="small-talk-owner")
    await sync_to_async(_seed_course)("cs101", user)
    fake = _SequencedClient([
        _classify_response("general_assistant"),
        _text_response("You're welcome! Let me know if you need anything else."),
    ])
    monkeypatch.setattr(ask, "get_client", lambda: fake)

    result = await ask.ask_async("cs101", "thanks Cora!", user=user)

    assert result["grounded"] is False
    assert result["answer"] == "You're welcome! Let me know if you need anything else."
    # The small-talk reply call must not carry the full syllabus/notes context.
    second_call = fake.messages.calls[1]
    assert second_call["messages"] == [{"role": "user", "content": "thanks Cora!"}]


async def test_study_planner_intent_dispatches_and_grounds_sources(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="study-plan-owner")
    await sync_to_async(_seed_grounded_course_for_recommendations)("cs101", user)
    router_fake = _SequencedClient([_classify_response("study_planner")])
    monkeypatch.setattr(ask, "get_client", lambda: router_fake)
    planner_fake = _SequencedClient([_text_response(json.dumps({
        "plan": [{"course_id": "cs101", "topic": "Recursion", "activity": "Practice quiz", "minutes": 30, "reason": "Weakest topic.", "priority": 1}],
        "summary": "Focus on recursion tonight.",
    }))])
    monkeypatch.setattr(study_planner, "get_client", lambda: planner_fake)

    result = await ask.ask_async("cs101", "what should I study tonight?", user=user)

    assert result["grounded"] is True
    assert "Focus on recursion tonight." in result["answer"]
    assert "Recursion" in result["answer"]


async def test_mastery_analyzer_intent_dispatches(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="mastery-analyzer-dispatch-owner")
    await sync_to_async(_seed_course)("cs101", user)
    await sync_to_async(storage.append_quiz_attempt)("cs101", {
        "topic": "Recursion", "correct": False, "timestamp": "2026-01-01T00:00:00",
        "question": "base case?", "correct_answer": "1", "user_answer": "0",
    }, user=user)
    await sync_to_async(mastery.rebuild_scores)("cs101", user=user)
    router_fake = _SequencedClient([_classify_response("mastery_analyzer")])
    monkeypatch.setattr(ask, "get_client", lambda: router_fake)
    analyzer_fake = _SequencedClient([_text_response(json.dumps({
        "insight": "Misses base-case questions.", "recommended_action": "Review base cases.", "confidence": "medium",
    }))])
    monkeypatch.setattr(mastery_analyzer, "get_client", lambda: analyzer_fake)

    result = await ask.ask_async("cs101", "how am I doing with recursion?", user=user)

    assert result["grounded"] is True
    assert "base-case" in result["answer"]
    assert "Review base cases." in result["answer"]


async def test_document_summary_intent_dispatches(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="doc-summary-dispatch-owner")
    await sync_to_async(_seed_course)("cs101", user)
    await sync_to_async(_seed_notes)("cs101", user)
    router_fake = _SequencedClient([_classify_response("document_summary_quick")])
    monkeypatch.setattr(ask, "get_client", lambda: router_fake)
    summarizer_fake = _SequencedClient([_text_response(json.dumps({"summary": "- Recursion recap."}))])
    monkeypatch.setattr(document_summarizer, "get_client", lambda: summarizer_fake)

    result = await ask.ask_async("cs101", "give me a quick summary of today's lecture", user=user)

    assert result["grounded"] is True
    assert "Recursion recap." in result["answer"]
    assert result["sources"]


@pytest.mark.parametrize(("question", "expected_depth"), [
    ("what was todays lesosn about", "quick"),
    ("what was todayâ€™s lesson about", "quick"),
    ("let's review today's lesson", "deep"),
    ("what did we cover in class today?", "quick"),
])
async def test_today_lesson_phrasing_bypasses_classifier_and_uses_today_notes(
    monkeypatch, django_user_model, isolated_courses_dir, question, expected_depth,
):
    user = await sync_to_async(django_user_model.objects.create_user)(username=f"today-lesson-{abs(hash(question))}")
    await sync_to_async(_seed_course)("cs101", user)
    today = ask.date.today().isoformat()
    storage.write_notes("cs101", "today-lesson", {
        "lecture_id": "today-lesson", "source": "notes", "date": today, "topics": ["Recursion"],
        "chunks": [{"id": "today-1", "topic": "Recursion", "text": "Today's lesson covered recursive base cases."}],
    }, user)
    storage.write_notes("cs101", "z-older-lesson", {
        "lecture_id": "z-older-lesson", "source": "notes", "date": "2026-01-01", "topics": ["Loops"],
        "chunks": [{"id": "old-1", "topic": "Loops", "text": "An older lesson covered loops."}],
    }, user)

    async def fail_if_classified(*args, **kwargs):
        raise AssertionError("today-lesson requests should bypass probabilistic intent classification")

    summary_calls = []

    async def summarize_today(course_id, **kwargs):
        summary_calls.append((course_id, kwargs))
        if kwargs["depth"] == "deep":
            return {
                "source_id": "today-lesson", "title": "today-lesson", "depth": "deep",
                "key_concepts": ["Recursive base cases"], "definitions": [],
                "relationships": [], "likely_testable": [],
            }
        return {
            "source_id": "today-lesson", "title": "today-lesson", "depth": "quick",
            "summary": "- Recursive base cases.",
        }

    monkeypatch.setattr(intent_router, "classify", fail_if_classified)
    monkeypatch.setattr(ask, "get_client", lambda: _SequencedClient([_text_response("unused")]))
    monkeypatch.setattr(document_summarizer, "summarize", summarize_today)

    result = await ask.ask_async("cs101", question, user=user)

    assert result["grounded"] is True
    assert result["sources"][0]["lecture_id"] == "today-lesson"
    assert summary_calls == [("cs101", {"lecture_date": today, "depth": expected_depth, "user": user})]


async def test_quiz_or_flashcards_intent_dispatches_flashcards(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="flashcard-dispatch-owner")
    await sync_to_async(_seed_course)("cs101", user)
    await sync_to_async(_seed_notes)("cs101", user)
    router_fake = _SequencedClient([_classify_response("quiz_or_flashcards")])
    monkeypatch.setattr(ask, "get_client", lambda: router_fake)
    quiz_fake = _SequencedClient([_text_response(json.dumps({
        "flashcards": [{"term": "Base case", "definition": "The condition that stops recursion.", "source": "course", "url": None}],
    }))])
    monkeypatch.setattr(quiz, "get_client", lambda: quiz_fake)

    result = await ask.ask_async("cs101", "make me some flashcards on recursion", user=user)

    assert result["grounded"] is True
    assert "Base case" in result["answer"]
