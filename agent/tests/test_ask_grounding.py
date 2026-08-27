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
from agent.services import ask, custom_events, sessions, storage


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


class _FakeToolUseBlock:
    def __init__(self, name, tool_input):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input


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


def _seed_course(course_id, user):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    }, user)


def _seed_lecture(course_id, user, lecture_id="ComputationTheory_Lecture01"):
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id,
        "source": "notes",
        "topics": ["A"],
        "chunks": [{
            "id": "sets-chunk",
            "topic": "A",
            "text": "A universal set contains the elements under discussion. DeMorgan's law explains complements of unions.",
        }],
    }, user)


def test_build_web_search_tool_requires_approved_domains():
    assert ask._build_web_search_tool([]) is None


def test_build_web_search_tool_scopes_to_approved_domains():
    assert ask._build_web_search_tool(["docs.python.org"]) == {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }


def test_calendar_write_tool_is_a_bounded_confirmation_proposal():
    tool = ask._build_calendar_write_tool()

    assert tool["name"] == "propose_calendar_changes"
    assert "writes nothing until" in tool["description"]
    assert tool["input_schema"]["properties"]["deadlines"]["maxItems"] == 150
    action = tool["input_schema"]["properties"]["deadlines"]["items"]
    assert action["properties"]["action"]["enum"] == ["create", "update", "delete"]


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


def test_deadline_intent_matches_across_multiple_lines():
    # Regression: the trigger verb/noun and the day-of-week keyword landing
    # on separate lines (a structured multi-field request, e.g. pasted
    # "Course: ... / Days: ... / Time: ...") must still match — "." doesn't
    # span newlines by default, so a plain ".*" here silently missed this
    # shape entirely and the request fell through to plain grounded Q&A,
    # where the model correctly (but unhelpfully) said it had no calendar
    # tool available, confirmed via manual repro in a live session.
    message = (
        "Course: CMPSC 457 — Computer Graphics Algorithms\n"
        "Days: Monday, Wednesday, Friday\n"
        "Time: 1:25 PM - 2:15 PM\n"
        "Start: August 24, 2026\n"
        "End: December 4, 2026"
    )
    assert ask._looks_like_deadline_request(message)


def test_deadline_intent_matches_generic_add_to_calendar_phrasing():
    assert ask._looks_like_deadline_request("Can you add this to my calendar?")
    assert ask._looks_like_deadline_request("please put this on my calendar")


@pytest.mark.django_db
async def test_class_schedule_request_can_return_multiple_pending_events(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="class-schedule-multiple-events")
    _seed_course("testcourse", user)
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

    result = await ask.ask_async("testcourse", "my class meets Monday and Wednesday at 10", user=user)

    assert result["pending_deadline"] is None
    assert [event["date"] for event in result["pending_deadlines"]] == ["2026-08-24", "2026-08-26"]
    assert {event["type"] for event in result["pending_deadlines"]} == {"class"}
    context = _content_text(fake_client.messages.calls[0]["messages"][0]["content"])
    assert '"schedule_weeks": 15' in context
    assert "schedule_start_date" in context
    assert "schedule_end_date" in context


@pytest.mark.django_db
async def test_calendar_tool_proposes_change_without_writing_it(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="calendar-tool-proposal")
    _seed_course("testcourse", user)
    tool_input = {
        "is_deadline_request": True,
        "missing": [],
        "deadlines": [{
            "action": "create",
            "event_id": None,
            "title": "Project 1",
            "course_id": "testcourse",
            "date": "2026-09-14",
            "time": "17:00",
            "end_time": None,
            "type": "project",
        }],
        "message": "Add Project 1 on Sep 14 at 5:00 PM?",
    }
    fake_client = _FakeClient(_FakeResponseWithContent([
        _FakeToolUseBlock(ask.CALENDAR_WRITE_TOOL_NAME, tool_input),
    ]))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async(
        "testcourse", "add Project 1 to my calendar on September 14 at 5", user=user,
    )

    assert result["pending_deadline"]["title"] == "Project 1"
    assert result["pending_deadline"]["action"] == "create"
    assert await sync_to_async(custom_events.list_events)(user=user) == []
    call = fake_client.messages.calls[0]
    assert call["tools"] == [ask._build_calendar_write_tool()]
    assert call["tool_choice"] == {"type": "tool", "name": ask.CALENDAR_WRITE_TOOL_NAME}


@pytest.mark.django_db
async def test_calendar_tool_rejects_malformed_action_input(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="calendar-tool-invalid")
    _seed_course("testcourse", user)
    fake_client = _FakeClient(_FakeResponseWithContent([
        _FakeToolUseBlock(ask.CALENDAR_WRITE_TOOL_NAME, {
            "is_deadline_request": True,
            "missing": [],
            "deadlines": ["not an action"],
            "message": "Confirm?",
        }),
    ]))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    with pytest.raises(ValueError, match="shape of calendar actions"):
        await ask.ask_async("testcourse", "add a project to my calendar tomorrow", user=user)

    assert await sync_to_async(custom_events.list_events)(user=user) == []


@pytest.mark.django_db
async def test_no_web_search_tool_when_no_domains_approved(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="no-web-search-tool")
    _seed_course("testcourse", user)
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question", user=user)

    assert result["grounded"] is False
    assert "tools" not in fake_client.messages.calls[0]


@pytest.mark.django_db
async def test_save_site_request_stores_url_without_model_call(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-stores-url")
    _seed_course("testcourse", user)

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
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-reach-context")
    _seed_course("testcourse", user)
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
    user = await sync_to_async(django_user_model.objects.create_user)(username="site-user-domain")
    _seed_course("testcourse", user)
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

    await ask.ask_async("testcourse", "look up the next WebGL detail from the book", user=user, allow_web=True)

    assert fake_client.messages.calls[0]["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["sites.google.com"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }]


@pytest.mark.django_db
async def test_relevant_prior_sessions_reach_ask_context(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="memory-user-reach-context")
    _seed_course("testcourse", user)
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

    assert result["sources"][0]["material_id"].startswith("ontrack-conversation-")
    context_message = _content_text(fake_client.messages.calls[0]["messages"][0]["content"])
    assert "RECALLED_CONVERSATIONS" in context_message
    assert "plain language" in context_message
    assert "final project dates" not in context_message


@pytest.mark.django_db
async def test_relevant_memory_excludes_active_session(isolated_courses_dir, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="memory-user-excludes-active")
    _seed_course("testcourse", user)
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
async def test_web_search_tool_added_with_approved_domains(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="web-search-tool-added")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
    canned = json.dumps({
        "answer": "from the web", "grounded": True, "sources": ["https://docs.python.org/3/"],
    })
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question", user=user, allow_web=True)

    assert result["grounded"] is True
    call = fake_client.messages.calls[0]
    assert call["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["docs.python.org"],
        "max_uses": ask.WEB_SEARCH_MAX_USES,
    }]


@pytest.mark.django_db
async def test_course_material_mode_never_offers_web_even_when_domains_are_approved(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="course-only-web-disabled")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
    fake_client = _FakeClient(_FakeResponse(json.dumps({"answer": "Not covered.", "grounded": False, "sources": []})))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question", user=user)

    assert result["grounding_mode"] == "course_materials"
    assert fake_client.messages.calls[0].get("tools", []) == []


@pytest.mark.django_db
async def test_pause_turn_resubmits_conversation_up_to_limit(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="pause-turn-resubmits")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
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

    result = await ask.ask_async("testcourse", "some question", user=user)

    assert result["answer"] == "done"
    assert call_count == 2

    # The resubmission must replay the paused assistant's actual content
    # (the API auto-detects the trailing server-tool state itself), not a
    # synthetic "Continue" user message.
    second_call_messages = fake_client.messages.calls[1]["messages"]
    assert second_call_messages[-1] == {"role": "assistant", "content": paused_response.content}


@pytest.mark.django_db
async def test_pause_turn_stops_after_max_continuations(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="pause-turn-stops")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
    # Always pauses — never resolves to end_turn — to prove the loop is
    # actually capped rather than unbounded (an unbounded `while` would also
    # pass the test above, since its second response is end_turn).
    fake_client = _FakeClient(_FakeResponse("mid-search", stop_reason="pause_turn"))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    with pytest.raises(ValueError):
        await ask.ask_async("testcourse", "some question", user=user)

    # First call plus the capped number of continuations.
    assert len(fake_client.messages.calls) == ask.MAX_PAUSE_TURN_CONTINUATIONS + 1


@pytest.mark.django_db
async def test_citation_split_text_blocks_after_tool_use_are_reassembled(
    isolated_courses_dir, monkeypatch, django_user_model,
):
    # Simulates a post-search response where the API attaches citations to a
    # span of the answer, splitting the final JSON text across multiple
    # trailing `text` blocks (each carrying its own citations array in
    # reality, though the fake doesn't need to model that field). Only the
    # last text block used to be read, which truncated the JSON.
    user = await sync_to_async(django_user_model.objects.create_user)(username="citation-split-blocks")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
    content = [
        _FakeNonTextBlock("server_tool_use"),
        _FakeNonTextBlock("web_search_tool_result"),
        _FakeTextBlock('{"answer": "Per the docs, '),
        _FakeTextBlock('the walrus operator assigns inline'),
        _FakeTextBlock('", "grounded": true, "sources": ["https://docs.python.org/3/"]}'),
    ]
    fake_client = _FakeClient(_FakeResponseWithContent(content))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what does := do?", user=user)

    assert result["answer"] == "Per the docs, the walrus operator assigns inline"
    assert result["grounded"] is True
    assert result["sources"][0]["material_type"] == "web"
    assert result["sources"][0]["url"] == "https://docs.python.org/3/"


@pytest.mark.django_db
async def test_reference_text_reaches_prompt(isolated_courses_dir, monkeypatch, django_user_model):
    # Structural check that reference content actually gets stuffed into the
    # prompt sent to the API — closes the gap where deleting the
    # reference-context wiring from ask_async would leave the whole
    # non-live suite green.
    user = await sync_to_async(django_user_model.objects.create_user)(username="reference-text-reaches-prompt")
    _seed_course("testcourse", user)
    storage.write_reference("testcourse", "ref1", {
        "reference_id": "ref1",
        "title": "Some Reference",
        "source_filename": "ref1.txt",
        "text": "UNIQUE_MARKER_TEXT_12345",
    }, user)
    canned = json.dumps({"answer": "not covered", "grounded": False, "sources": []})
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    await ask.ask_async("testcourse", "some question", user=user)

    call = fake_client.messages.calls[0]
    assert "UNIQUE_MARKER_TEXT_12345" in _content_text(call["messages"][0]["content"])


@pytest.mark.django_db
async def test_preamble_text_block_before_tool_use_is_dropped(isolated_courses_dir, monkeypatch, django_user_model):
    # A text block emitted before tool use (e.g. the model narrating what
    # it's about to do) must not be concatenated into the final JSON.
    user = await sync_to_async(django_user_model.objects.create_user)(username="preamble-before-tool-use")
    _seed_course("testcourse", user)
    storage.write_trusted_domains("testcourse", ["docs.python.org"], user)
    content = [
        _FakeTextBlock("I'll check the docs."),
        _FakeNonTextBlock("server_tool_use"),
        _FakeTextBlock('{"answer": "ok", "grounded": true, "sources": []}'),
    ]
    fake_client = _FakeClient(_FakeResponseWithContent(content))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "some question", user=user)

    assert result["answer"] == "ok"
    assert result["grounded"] is True
    assert result["sources"] == []


@pytest.mark.django_db
async def test_preamble_text_without_tool_use_is_still_parsed(isolated_courses_dir, monkeypatch, django_user_model):
    # No tool use happens here, so the last-non-text-block trim in ask_async
    # never kicks in — reproduces a live failure where the model ignored the
    # "no preamble" instruction and prefixed the JSON with prose explaining
    # a limitation. _parse_json_response must still find and parse the JSON.
    user = await sync_to_async(django_user_model.objects.create_user)(username="preamble-without-tool-use")
    _seed_course("testcourse", user)
    canned = (
        "I can't actually read the contents of your saved sites — only the URL "
        "and title are stored.\n\n"
        '{"answer": "I can\'t read saved site contents.", "grounded": false, "sources": []}'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what does chapter 2 say?", user=user)

    assert result["answer"] == "I can't read saved site contents."
    assert result["grounded"] is False
    assert result["sources"] == []


@pytest.mark.django_db
async def test_preamble_with_set_braces_before_json_is_still_parsed(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="preamble-set-braces")
    _seed_course("testcourse", user)
    _seed_lecture("testcourse", user)
    canned = (
        "The notes define a universal set with an example: "
        "`A = {1, 2, 3}`, `B = {1, a, b, c}`.\n\n"
        '{"answer": "Universal set example parsed.", "grounded": true, '
        '"sources": ["ComputationTheory\\_Lecture01"]}'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "what is a universal set?", user=user)

    assert result["answer"] == "Universal set example parsed."
    assert result["grounded"] is True
    assert result["sources"][0]["lecture_id"] == "ComputationTheory_Lecture01"


@pytest.mark.django_db
async def test_answer_with_unescaped_inner_quotes_is_still_parsed(isolated_courses_dir, monkeypatch, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(username="unescaped-inner-quotes")
    _seed_course("testcourse", user)
    _seed_lecture("testcourse", user)
    prior = await sync_to_async(sessions.create_session)("testcourse", user=user)
    await sync_to_async(sessions.append_message)(
        "testcourse", prior["session_id"], "user", "Morgan's law uses complements of unions.", user=user,
    )
    canned = (
        '{ "answer": "DeMorgan intuition: "Not (A or B)" means outside both.\\n\\n'
        '```venn\\noperation: union\\na: A\\nb: B\\nuniverse: U\\ncaption: A union B\\n```", '
        '"grounded": true, "sources": ["ComputationTheory\\_Lecture01", "recalled\\_conversations"] }'
    )
    fake_client = _FakeClient(_FakeResponse(canned))
    monkeypatch.setattr(ask, "get_client", lambda: fake_client)

    result = await ask.ask_async("testcourse", "talk about morgan's law", user=user)

    assert '"Not (A or B)"' in result["answer"]
    assert "```venn\noperation: union" in result["answer"]
    assert result["grounded"] is True
    assert result["sources"][0]["material_id"] == "legacy-notes-ComputationTheory_Lecture01"
    assert result["sources"][1]["material_id"].startswith("ontrack-conversation-")
