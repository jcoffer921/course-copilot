"""
Structural (non-live) tests for ask.py's new grounding-source wiring: that
the web_search tool is added only when a course has approved domains, and
that it's built with the right allowed_domains. These don't call the real
API — a fake client records what ask_async would have sent it.
"""

import json

import pytest
from asgiref.sync import sync_to_async

from agent.models import SavedSite
from agent.services import ask, sessions, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _content_text(content):
    """ask_async's context message is now a list of text blocks (cache_control
    breakpoint on the context block) rather than a single string — flatten it
    back to text so these prompt-content assertions still work regardless of
    which shape a given message uses."""
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content)


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


def test_build_web_search_tool_requires_approved_domains():
    assert ask._build_web_search_tool([]) is None


def test_build_web_search_tool_scopes_to_approved_domains():
    assert ask._build_web_search_tool(["docs.python.org"]) == {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }


def test_domains_from_saved_sites_extracts_http_hosts():
    assert ask._domains_from_saved_sites([
        {"url": "https://sites.google.com/site/webglbook/home/chapter-2"},
        {"url": "ftp://example.com/book"},
        {"url": ""},
    ]) == ["sites.google.com"]


def test_deadline_intent_accepts_natural_event_requests():
    assert ask._looks_like_deadline_request("remind me about the project due Friday")
    assert ask._looks_like_deadline_request("I have an exam on 2026-09-12")
    assert ask._looks_like_deadline_request("put my lab meeting on the calendar tomorrow at 3")
    assert ask._looks_like_deadline_request("my class meets Mondays and Wednesdays at 10")
    assert ask._looks_like_deadline_request("CS101 schedule is MWF 10-10:50")


def test_deadline_intent_does_not_catch_plain_course_questions():
    assert not ask._looks_like_deadline_request("what does the project cover?")
    assert not ask._looks_like_deadline_request("explain exam study strategies")


@pytest.mark.django_db
async def test_class_schedule_request_can_return_multiple_pending_events(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = json.dumps({
        "is_deadline_request": True,
        "missing": [],
        "deadlines": [
            {
                "title": "Test class",
                "course_id": "testcourse",
                "date": "2026-08-24",
                "time": "10:00",
                "end_time": "10:50",
                "type": "class",
            },
            {
                "title": "Test class",
                "course_id": "testcourse",
                "date": "2026-08-26",
                "time": "10:00",
                "end_time": "10:50",
                "type": "class",
            },
        ],
        "message": "I found two class meetings for this week. Confirm to add them.",
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "my class meets Monday and Wednesday at 10")

    assert result["pending_deadline"] is None
    assert [event["date"] for event in result["pending_deadlines"]] == ["2026-08-24", "2026-08-26"]
    assert {event["type"] for event in result["pending_deadlines"]} == {"class"}
    context = _content_text(fake_client.messages.calls[0]["messages"][0]["content"])
    assert '"schedule_weeks": 15' in context
    assert "schedule_start_date" in context
    assert "schedule_end_date" in context


@pytest.mark.django_db
async def test_no_web_search_tool_when_no_domains_approved(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question")

    assert result["grounded"] is False
    assert "tools" not in fake_client.messages.calls[0]


@pytest.mark.django_db
async def test_save_site_request_stores_url_without_model_call(isolated_courses_dir, monkeypatch, django_user_model):
    _seed_course("testcourse")
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-stores-url")

    def fail_get_client():
        raise AssertionError("saving a site address should not call the model")

    monkeypatch.setattr(ask, "get_client", fail_get_client)

    result = await ask.ask_async(
        "testcourse",
        "save https://example.edu/large-course-book as course book",
        user=user,
    )

    assert result["grounded"] is True
    assert result["saved_site"]["title"] == "course book"
    assert result["saved_site"]["url"] == "https://example.edu/large-course-book"
    saved = await sync_to_async(SavedSite.objects.get)(course_id="testcourse", user=user)
    assert saved.url == "https://example.edu/large-course-book"


@pytest.mark.django_db
async def test_saved_sites_reach_ask_context(isolated_courses_dir, monkeypatch, django_user_model):
    _seed_course("testcourse")
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-reach-context")
    await sync_to_async(storage.save_site)(
        "testcourse", "https://example.edu/large-course-book", title="Course Book", user=user,
    )
    canned = json.dumps({
        "answer": "The course book is https://example.edu/large-course-book",
        "grounded": True,
        "sources": ["https://example.edu/large-course-book"],
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what is my course book link?", user=user)

    assert result["grounded"] is True
    context_message = _content_text(fake_client.messages.calls[0]["messages"][0]["content"])
    assert "SAVED_SITES" in context_message
    assert "https://example.edu/large-course-book" in context_message


@pytest.mark.django_db
async def test_saved_site_domain_is_available_to_web_search(isolated_courses_dir, monkeypatch, django_user_model):
    _seed_course("testcourse")
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-domain")
    await sync_to_async(storage.save_site)(
        "testcourse", "https://sites.google.com/site/webglbook/home/chapter-2", title="WebGL Book", user=user,
    )
    canned = json.dumps({
        "answer": "from saved site search",
        "grounded": True,
        "sources": ["https://sites.google.com/site/webglbook/home/chapter-2"],
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    await ask.ask_async("testcourse", "look up the next WebGL detail from the book", user=user)

    assert fake_client.messages.calls[0]["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["sites.google.com"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }]


@pytest.mark.django_db
async def test_relevant_prior_sessions_reach_ask_context(isolated_courses_dir, monkeypatch, django_user_model):
    _seed_course("testcourse")
    user = await sync_to_async(django_user_model.objects.create_user)(username="memory-user-reach-context")
    relevant = await sync_to_async(sessions.create_session)("testcourse", user=user)
    await sync_to_async(sessions.append_message)(
        "testcourse", relevant["session_id"], "user", "I want shader examples in plain language.", user=user,
    )
    await sync_to_async(sessions.append_message)(
        "testcourse", relevant["session_id"], "assistant", "I'll keep shader examples plain.",
        sources=["recalled_conversations"], grounded=True, user=user,
    )
    unrelated = await sync_to_async(sessions.create_session)("testcourse", user=user)
    await sync_to_async(sessions.append_message)(
        "testcourse", unrelated["session_id"], "user", "Let's talk about final project dates.", user=user,
    )
    canned = json.dumps({"answer": "remembered", "grounded": True, "sources": ["recalled_conversations"]})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "remember how I want shader examples explained?", user=user)

    assert result["sources"] == ["recalled_conversations"]
    context_message = _content_text(fake_client.messages.calls[0]["messages"][0]["content"])
    assert "RECALLED_CONVERSATIONS" in context_message
    assert "plain language" in context_message
    assert "final project dates" not in context_message


@pytest.mark.django_db
async def test_relevant_memory_excludes_active_session(isolated_courses_dir, django_user_model):
    _seed_course("testcourse")
    user = await sync_to_async(django_user_model.objects.create_user)(username="memory-user-excludes-active")
    active = await sync_to_async(sessions.create_session)("testcourse", user=user)
    await sync_to_async(sessions.append_message)(
        "testcourse", active["session_id"], "user", "shader notes in active chat", user=user,
    )
    previous = await sync_to_async(sessions.create_session)("testcourse", user=user)
    await sync_to_async(sessions.append_message)(
        "testcourse", previous["session_id"], "user", "shader notes from older chat", user=user,
    )

    recalled = await sync_to_async(sessions.relevant_messages)(
        "testcourse", "shader notes", session_id=active["session_id"], user=user,
    )

    assert recalled
    assert all(item["session_id"] != active["session_id"] for item in recalled)
    assert any("older chat" in item["content"] for item in recalled)


@pytest.mark.django_db
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
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }]


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
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
    assert "UNIQUE_MARKER_TEXT_12345" in _content_text(call["messages"][0]["content"])


@pytest.mark.django_db
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


@pytest.mark.django_db
async def test_preamble_text_without_tool_use_is_still_parsed(isolated_courses_dir, monkeypatch):
    # No tool use happens here, so the last-non-text-block trim in ask_async
    # never kicks in — reproduces a live failure where the model ignored the
    # "no preamble" instruction and prefixed the JSON with prose explaining
    # a limitation. _parse_json_response must still find and parse the JSON.
    _seed_course("testcourse")
    canned = (
        "I can't actually read the contents of your saved sites — only the URL "
        "and title are stored.\n\n"
        '{"answer": "I can\'t read saved site contents.", "grounded": false, "sources": []}'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what does chapter 2 say?")

    assert result["answer"] == "I can't read saved site contents."
    assert result["grounded"] is False
    assert result["sources"] == []


@pytest.mark.django_db
async def test_preamble_with_set_braces_before_json_is_still_parsed(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = (
        "The notes define a universal set with an example: "
        "`A = {1, 2, 3}`, `B = {1, a, b, c}`.\n\n"
        '{"answer": "Universal set example parsed.", "grounded": true, '
        '"sources": ["ComputationTheory\\_Lecture01"]}'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what is a universal set?")

    assert result["answer"] == "Universal set example parsed."
    assert result["grounded"] is True
    assert result["sources"] == ["ComputationTheory_Lecture01"]


@pytest.mark.django_db
async def test_answer_with_unescaped_inner_quotes_is_still_parsed(isolated_courses_dir, monkeypatch):
    _seed_course("testcourse")
    canned = (
        '{ "answer": "DeMorgan intuition: "Not (A or B)" means outside both.\\n\\n'
        '```venn\\noperation: union\\na: A\\nb: B\\nuniverse: U\\ncaption: A union B\\n```", '
        '"grounded": true, "sources": ["ComputationTheory\\_Lecture01", "recalled\\_conversations"] }'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "talk about morgan's law")

    assert '"Not (A or B)"' in result["answer"]
    assert "```venn\noperation: union" in result["answer"]
    assert result["grounded"] is True
    assert result["sources"] == ["ComputationTheory_Lecture01", "recalled_conversations"]
