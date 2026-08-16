"""
Structural (non-live) tests for ask.py's new grounding-source wiring: that
the web_search tool is added only when a course has approved domains, and
that it's built with the right allowed_domains. These don't call the real
API — a fake client records what ask_async would have sent it.
"""

import json

import pytest

from agent.services import ask, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason


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


def _seed_course(course_id):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    })


async def test_no_web_search_tool_when_no_domains_approved(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["grounded"] is False
    assert "tools" not in fake_client.messages.calls[0]


async def test_web_search_tool_added_with_approved_domains(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    canned = json.dumps({
        "answer": "from the web", "grounded": True, "sources": ["https://docs.python.org/3/"],
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["grounded"] is True
    call = fake_client.messages.calls[0]
    assert call["tools"] == [{
        "type": "web_search_20250305", "name": "web_search", "allowed_domains": ["docs.python.org"],
    }]


async def test_pause_turn_resubmits_conversation_up_to_limit(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    final = json.dumps({"answer": "done", "grounded": True, "sources": ["https://docs.python.org/3/"]})
    fake_client = _FakeClient(_FakeResponse("mid-search", stop_reason="pause_turn"))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    # First call pauses; make the second call (the resubmission) return the final answer.
    original_create = fake_client.messages.create

    call_count = 0

    async def create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await original_create(**kwargs)
        return _FakeResponse(final)

    fake_client.messages.create = create

    result = await ask.ask_async("testcourse", "some question")

    assert result["answer"] == "done"
    assert call_count == 2
