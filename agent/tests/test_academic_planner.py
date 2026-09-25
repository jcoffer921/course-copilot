import json

import pytest

from agent.services import academic_planner
from agent.services.academic_planner import _enforce_grounding, plan_chat_async


def _program_requirement():
    return {
        "program_name": "B.S. Computer Science",
        "catalog_year": "2026-2027",
        "total_credits_required": 120,
        "categories": [
            {"name": "Core", "credits_required": 6, "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3, "prerequisites": [], "notes": ""},
                {"code": "CS 201", "title": "Data Structures", "credits": 3, "prerequisites": ["CS 101"], "notes": ""},
            ]},
        ],
    }


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


# --------------------------------------------------------------------------
# Grounding check
# --------------------------------------------------------------------------

def test_enforce_grounding_drops_course_not_in_program_requirement():
    draft = {
        "student_major": "Computer Science",
        "semesters": [{
            "label": "Fall 2026",
            "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3},
                {"code": "CS 999", "title": "Fabricated Course", "credits": 3},
            ],
        }],
        "total_credits": 6,
        "notes": "",
    }

    result = _enforce_grounding(draft, _program_requirement())

    codes = [c["code"] for c in result["semesters"][0]["courses"]]
    assert codes == ["CS 101"]
    assert result["total_credits"] == 3


def test_enforce_grounding_returns_none_for_non_dict_input():
    assert _enforce_grounding(None, _program_requirement()) is None
    assert _enforce_grounding("not a dict", _program_requirement()) is None


# --------------------------------------------------------------------------
# plan_chat_async — mocked model call
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_session_produces_clarifying_question_not_premature_plan(monkeypatch):
    payload = json.dumps({
        "reply": "What's this student's intended major, and have they completed any coursework yet?",
        "student_details": {},
        "draft_plan": None,
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(academic_planner, "get_client", lambda: fake)

    result = await plan_chat_async(_program_requirement(), {}, [], "Help me plan for a new student.")

    assert result["draft_plan"] is None
    assert "major" in result["reply"].lower()


@pytest.mark.asyncio
async def test_completed_conversation_produces_draft_plan_grounded_in_source(monkeypatch):
    payload = json.dumps({
        "reply": "Here's a draft plan.",
        "student_details": {"major": "Computer Science", "completed": []},
        "draft_plan": {
            "student_major": "Computer Science",
            "semesters": [{"label": "Fall 2026", "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3},
            ]}],
            "total_credits": 3,
            "notes": "",
        },
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(academic_planner, "get_client", lambda: fake)

    result = await plan_chat_async(
        _program_requirement(),
        {"major": "Computer Science", "completed": []},
        [{"role": "user", "content": "The student is a CS major, no prior coursework."}],
        "Draft a plan.",
    )

    assert result["draft_plan"] is not None
    all_codes = {c["code"] for s in result["draft_plan"]["semesters"] for c in s["courses"]}
    valid_codes = {c["code"] for cat in _program_requirement()["categories"] for c in cat["courses"]}
    assert all_codes.issubset(valid_codes)


@pytest.mark.asyncio
async def test_fabricated_course_in_model_response_is_dropped_not_surfaced(monkeypatch):
    payload = json.dumps({
        "reply": "Here's a draft plan.",
        "student_details": {},
        "draft_plan": {
            "student_major": "Computer Science",
            "semesters": [{"label": "Fall 2026", "courses": [
                {"code": "CS 101", "title": "Intro to Programming", "credits": 3},
                {"code": "PHIL 999", "title": "Made-up Philosophy Course", "credits": 3},
            ]}],
            "total_credits": 6,
            "notes": "",
        },
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(academic_planner, "get_client", lambda: fake)

    result = await plan_chat_async(_program_requirement(), {}, [], "Draft a plan.")

    codes = [c["code"] for c in result["draft_plan"]["semesters"][0]["courses"]]
    assert codes == ["CS 101"]
