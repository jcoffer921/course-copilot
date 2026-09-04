"""Cora's chat front door: classifies a message into one downstream
capability using a single small, tool-forced Haiku call.

Called from agent/services/ask.py::ask_async only AFTER its own free
deterministic regex checks (_looks_like_deadline_request,
_looks_like_save_site_request) have already failed to match — those stay
first since they're free and already correct. See
agent/services/cora_skills/intent_router.py for the full routing contract
(trigger criteria per capability, validation rules) this module implements;
the classification prompt below is generated from that same registry so the
two can't drift apart.
"""

import logging

from .client import CORA_MODELS
from .cora_skills import CAPABILITIES

logger = logging.getLogger(__name__)

_TOOL_NAME = "classify_intent"

# Order matters only for prompt readability. document_summary_quick/deep both
# implement the document_summarizer capability at different depths;
# quiz_or_flashcards covers both quiz_generator and flashcard_generator —
# ask.py decides between those two from phrasing, not this classifier.
_INTENT_TO_SKILL = {
    "general_assistant": "general_assistant",
    "study_planner": "study_planner",
    "mastery_analyzer": "mastery_analyzer",
    "document_summary_quick": "document_summarizer",
    "document_summary_deep": "document_summarizer",
    "quiz_or_flashcards": "quiz_generator",
    "course_qa": "course_qa",
}
_VALID_INTENTS = [*_INTENT_TO_SKILL.keys(), "unknown"]
_FALLBACK_INTENT = "course_qa"


def _build_system_prompt() -> str:
    lines = [
        "You classify a student's message to Cora, an OnTrack academic assistant, into "
        "exactly one capability using the classify_intent tool.",
        "'course_qa' is the safe default whenever nothing else clearly fits — pick it "
        "freely, it is not a last resort to avoid.",
        "",
        "Capabilities:",
    ]
    seen_skills = {}
    for intent, skill_name in _INTENT_TO_SKILL.items():
        skill = CAPABILITIES[skill_name]
        if skill_name in seen_skills:
            # document_summary_quick/deep share one skill (document_summarizer) whose
            # trigger_notes already explains the quick-vs-deep split — printing that
            # whole paragraph twice would just waste tokens on every classification call.
            lines.append(f"- {intent}: see {seen_skills[skill_name]} above for the quick-vs-deep split.")
            continue
        examples = "; ".join(f'"{t}"' for t in skill.triggers[:3])
        suffix = f" Examples: {examples}." if examples else ""
        seen_skills[skill_name] = intent
        lines.append(f"- {intent}: {skill.trigger_notes}{suffix}")
    lines.append(
        "- unknown: the message genuinely doesn't fit any capability above and isn't a "
        "course question either — use sparingly, this still falls back to course_qa."
    )
    return "\n".join(lines)


_SYSTEM_PROMPT = _build_system_prompt()


def _build_tool() -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Classify the student's message into one Cora capability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": _VALID_INTENTS},
                "requires_course_context": {"type": "boolean"},
            },
            "required": ["intent", "requires_course_context"],
            "additionalProperties": False,
        },
    }


def _fallback() -> dict:
    return {"intent": _FALLBACK_INTENT, "requires_course_context": True}


async def classify(client, question: str, has_current_course: bool) -> dict:
    """Never raises. Any failure — network error, malformed or out-of-enum
    tool output — returns the safe course_qa fallback, since a
    classification error must never block a chat message or surface to the
    student (agent/services/cora_skills/intent_router.py's validation
    rules).

    Takes an already-resolved client (from ask.py's own get_client() call)
    rather than resolving one itself, matching ask.py's existing
    _extract_deadline_request(client, ...) convention — this is what keeps
    ask.py's tests, which monkeypatch ask.get_client, able to fully control
    every model call this makes instead of hitting the real API."""
    try:
        response = await client.messages.create(
            model=CORA_MODELS["fast"],
            max_tokens=200,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"has_current_course: {has_current_course}\nMessage: {question}",
            }],
            tools=[_build_tool()],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )
    except Exception:
        logger.warning("intent_router.classify: API call failed, falling back to course_qa", exc_info=True)
        return _fallback()

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
    if not tool_blocks:
        return _fallback()

    data = tool_blocks[0].input
    if not isinstance(data, dict) or data.get("intent") not in _VALID_INTENTS:
        return _fallback()

    intent = "course_qa" if data["intent"] == "unknown" else data["intent"]
    return {
        "intent": intent,
        "requires_course_context": bool(data.get("requires_course_context", True)),
    }
