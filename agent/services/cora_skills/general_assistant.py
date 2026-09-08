"""Skill definition for cheap small-talk/navigation replies.

Implemented directly inside agent/services/ask.py::ask_async as a short,
skip-the-full-context Haiku reply — deliberately not its own service module,
since the whole point is to avoid paying for context assembly on messages
like "thanks Cora".
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="general_assistant",
    description=(
        "Greetings, thanks, and basic 'who are you'/navigation questions that need a short, "
        "friendly reply and nothing else — no course material, no learning-tool data, no "
        "full grounded-answer pipeline."
    ),
    triggers=[
        "thanks cora", "thank you", "hey cora", "hi", "who are you", "what can you do",
    ],
    trigger_notes=(
        "Route here only when the message carries no actual academic question or request — "
        "if it mixes a thank-you with a real follow-up question, classify by the follow-up "
        "instead. This exists specifically so a message like 'thanks Cora' never triggers a "
        "full syllabus/notes/references context build or a Sonnet call (see .claude/skills' "
        "cost-consciousness guidance)."
    ),
    default_model=CORA_MODELS["fast"],
    implemented_by="agent.services.ask.ask_async (inline small_talk branch)",
    required_context=[],
    output_schema={
        "answer": "string",
        "grounded": "bool (always false — nothing is being grounded here)",
        "sources": "list[string] (always empty)",
    },
    validation_rules=[
        "Never answer an actual academic/course question from this branch — if the message "
        "contains one, intent_router should have classified it elsewhere; this branch's reply "
        "prompt is not given course context at all, so it structurally cannot answer one.",
    ],
)
