from agent.services import intent_router


class _FakeToolUseBlock:
    def __init__(self, name, tool_input):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = _FakeMessages(response, error)


def _tool_response(intent, requires_course_context=True):
    return _FakeResponse([_FakeToolUseBlock(
        "classify_intent", {"intent": intent, "requires_course_context": requires_course_context},
    )])


async def test_classify_returns_the_models_chosen_intent():
    client = _FakeClient(_tool_response("study_planner"))

    result = await intent_router.classify(client, "what should I study tonight", has_current_course=True)

    assert result == {"intent": "study_planner", "requires_course_context": True}


async def test_classify_falls_back_to_course_qa_when_no_tool_use_block_present():
    client = _FakeClient(_FakeResponse([_FakeTextBlock("I'm not going to use the tool.")]))

    result = await intent_router.classify(client, "some question", has_current_course=True)

    assert result["intent"] == "course_qa"


async def test_classify_falls_back_to_course_qa_on_api_error():
    client = _FakeClient(error=RuntimeError("network exploded"))

    result = await intent_router.classify(client, "some question", has_current_course=True)

    assert result["intent"] == "course_qa"


async def test_classify_normalizes_unknown_to_course_qa():
    client = _FakeClient(_tool_response("unknown"))

    result = await intent_router.classify(client, "??? gibberish ???", has_current_course=True)

    assert result["intent"] == "course_qa"


async def test_classify_falls_back_to_course_qa_on_out_of_enum_intent():
    client = _FakeClient(_tool_response("delete_everything"))

    result = await intent_router.classify(client, "some question", has_current_course=True)

    assert result["intent"] == "course_qa"


async def test_generated_system_prompt_lists_every_intent_with_real_guidance():
    # The prompt is generated from cora_skills, not hand-written — this
    # catches a future intent added to _INTENT_TO_SKILL without a
    # corresponding, non-empty trigger_notes bullet ever reaching the model.
    prompt = intent_router._SYSTEM_PROMPT
    for intent in intent_router._INTENT_TO_SKILL:
        assert f"- {intent}:" in prompt
