import json

import pytest
from asgiref.sync import sync_to_async

from agent.services import mastery, mastery_analyzer, storage

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


def _seed_attempts(course_id, user, attempts):
    for a in attempts:
        storage.append_quiz_attempt(course_id, a, user=user)
    mastery.rebuild_scores(course_id, user=user)


async def test_analyze_returns_insight_and_normalizes_confidence(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="mastery-analyzer-owner")
    await sync_to_async(_seed_attempts)("cs101", user, [
        {
            "topic": "Recursion", "correct": False, "timestamp": "2026-01-01T00:00:00",
            "question": "What is the base case of factorial(0)?", "correct_answer": "1", "user_answer": "0",
        },
        {
            "topic": "Recursion", "correct": True, "timestamp": "2026-01-02T00:00:00",
            "question": "Trace factorial(3).", "correct_answer": "6", "user_answer": "6",
        },
    ])
    payload = json.dumps({
        "insight": "Misses base-case questions but traces recursive calls correctly.",
        "recommended_action": "Review base-case definitions before more tracing practice.",
        "confidence": "medium",
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(mastery_analyzer, "get_client", lambda: fake)

    result = await mastery_analyzer.analyze(user, "cs101", topic="Recursion")

    assert result["confidence"] == "medium"
    assert "base-case" in result["insight"]
    assert "base-case" in result["recommended_action"]
    sent_context = json.loads(fake.messages.calls[0]["messages"][0]["content"])
    assert len(sent_context["recent_attempts"]) == 2
    assert sent_context["mastery_scores"][0]["topic"] == "Recursion"


async def test_analyze_defaults_invalid_confidence_to_low(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="bad-confidence-owner")
    await sync_to_async(_seed_attempts)("cs101", user, [
        {"topic": "Recursion", "correct": False, "timestamp": "2026-01-01T00:00:00"},
    ])
    payload = json.dumps({"insight": "x", "recommended_action": "y", "confidence": "extremely sure"})
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(mastery_analyzer, "get_client", lambda: fake)

    result = await mastery_analyzer.analyze(user, "cs101", topic="Recursion")

    assert result["confidence"] == "low"


async def test_raises_when_no_mastery_or_attempt_data_exists(django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="no-data-owner")

    with pytest.raises(mastery_analyzer.NoMasteryDataError):
        await mastery_analyzer.analyze(user, "cs101")


async def test_topic_filter_excludes_other_topics_attempts(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="topic-filter-owner")
    await sync_to_async(_seed_attempts)("cs101", user, [
        {"topic": "Recursion", "correct": True, "timestamp": "2026-01-01T00:00:00"},
        {"topic": "Sorting", "correct": False, "timestamp": "2026-01-02T00:00:00"},
    ])
    fake = _FakeClient(_FakeResponse(json.dumps({"insight": "x", "recommended_action": "y", "confidence": "low"})))
    monkeypatch.setattr(mastery_analyzer, "get_client", lambda: fake)

    await mastery_analyzer.analyze(user, "cs101", topic="Recursion")

    sent_context = json.loads(fake.messages.calls[0]["messages"][0]["content"])
    assert all(a["topic"] == "Recursion" for a in sent_context["recent_attempts"])
