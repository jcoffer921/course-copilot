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


class _FakeNonTextBlock:
    def __init__(self, block_type="server_tool_use"):
        self.type = block_type


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason


class _FakeResponseWithContent:
    """Like _FakeResponse, but takes a pre-built content list directly so
    tests can mix text and non-text blocks (e.g. simulating a preamble or
    citation-split final answer)."""

    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
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
        "type": "web_search_20260209",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": 5,
    }]


async def test_pause_turn_resubmits_conversation_up_to_limit(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    final = json.dumps({"answer": "done", "grounded": True, "sources": ["https://docs.python.org/3/"]})
    paused_response = _FakeResponse("mid-search", stop_reason="pause_turn")
    fake_client = _FakeClient(paused_response)
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    # First call pauses; make the second call (the resubmission) return the final answer.
    call_count = 0

    async def create(**kwargs):
        nonlocal call_count
        call_count += 1
        fake_client.messages.calls.append(kwargs)
        if call_count == 1:
            return paused_response
        return _FakeResponse(final)

    fake_client.messages.create = create

    result = await ask.ask_async("testcourse", "some question")

    assert result["answer"] == "done"
    assert call_count == 2

    # The resubmission must replay the paused assistant's actual content
    # (the API auto-detects the trailing server-tool state itself), not a
    # synthetic "Continue" user message.
    second_call_messages = fake_client.messages.calls[1]["messages"]
    assert second_call_messages[-1] == {"role": "assistant", "content": paused_response.content}


async def test_pause_turn_stops_after_max_continuations(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    # Always pauses — never resolves to end_turn — to prove the loop is
    # actually capped rather than unbounded (an unbounded `while` would also
    # pass the test above, since its second response is end_turn).
    fake_client = _FakeClient(_FakeResponse("mid-search", stop_reason="pause_turn"))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    with pytest.raises(ValueError):
        await ask.ask_async("testcourse", "some question")

    # First call plus the capped number of continuations.
    assert len(fake_client.messages.calls) == ask.MAX_PAUSE_TURN_CONTINUATIONS + 1


async def test_citation_split_text_blocks_after_tool_use_are_reassembled(
    isolated_courses_dir, monkeypatch,
):
    # Simulates a post-search response where the API attaches citations to a
    # span of the answer, splitting the final JSON text across multiple
    # trailing `text` blocks (each carrying its own citations array in
    # reality, though the fake doesn't need to model that field). Only the
    # last text block used to be read, which truncated the JSON.
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    content = [
        _FakeNonTextBlock("server_tool_use"),
        _FakeNonTextBlock("web_search_tool_result"),
        _FakeTextBlock('{"answer": "Per the docs, '),
        _FakeTextBlock('the walrus operator assigns inline'),
        _FakeTextBlock('", "grounded": true, "sources": ["https://docs.python.org/3/"]}'),
    ]
    fake_client = _FakeClient(_FakeResponseWithContent(content))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what does := do?")

    assert result["answer"] == "Per the docs, the walrus operator assigns inline"
    assert result["grounded"] is True
    assert result["sources"] == ["https://docs.python.org/3/"]


async def test_reference_text_reaches_prompt(isolated_courses_dir, monkeypatch):
    # Structural check that reference content actually gets stuffed into the
    # prompt sent to the API — closes the gap where deleting the
    # reference-context wiring from ask_async would leave the whole
    # non-live suite green.
    _seed_course("testcourse")
    storage.write_reference("testcourse", "ref1", {
        "reference_id": "ref1",
        "title": "Some Reference",
        "source_filename": "ref1.txt",
        "text": "UNIQUE_MARKER_TEXT_12345",
    })
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    await ask.ask_async("testcourse", "some question")

    call = fake_client.messages.calls[0]
    assert "UNIQUE_MARKER_TEXT_12345" in call["messages"][0]["content"]


async def test_preamble_text_block_before_tool_use_is_dropped(isolated_courses_dir, monkeypatch):
    # A text block emitted before tool use (e.g. the model narrating what
    # it's about to do) must not be concatenated into the final JSON.
    _seed_course("testcourse")
    storage.write_trusted_domains("testcourse", ["docs.python.org"])
    content = [
        _FakeTextBlock("I'll check the docs."),
        _FakeNonTextBlock("server_tool_use"),
        _FakeTextBlock('{"answer": "ok", "grounded": true, "sources": []}'),
    ]
    fake_client = _FakeClient(_FakeResponseWithContent(content))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["answer"] == "ok"
    assert result["grounded"] is True
    assert result["sources"] == []
