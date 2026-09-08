"""Skill definition for chat-driven calendar create/update/delete proposals.

Implemented by agent/services/ask.py::_extract_deadline_request (pre-existing,
Haiku), with a one-shot escalation to Sonnet for contextually ambiguous dates
(see the "ambiguous_context" tool-schema field and the retry it triggers).
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="calendar_extractor",
    description=(
        "Turns a chat message describing a deadline/event change into a structured, "
        "side-effect-free create/update/delete proposal for the student to confirm."
    ),
    triggers=[
        "add homework 4 due october 12 at 11:59pm",
        "move my exam to friday",
        "delete the project deadline",
        "CMPSC 465 meets Monday Wednesday Friday 3:35-4:25pm",
    ],
    trigger_notes=(
        "Not reached through intent_router — ask.py's own deterministic regex "
        "(_looks_like_deadline_request) already classifies these messages for free, "
        "before intent_router ever runs, and dispatches straight here. A single "
        "recurring-schedule request with 2+ named weekdays plus a clock time is resolved "
        "with no model call at all (_recurring_schedule_proposal). Everything else starts "
        "on Haiku and escalates once to Sonnet only when the model itself reports "
        "ambiguous_context=true — i.e. the date depends on another date/event mentioned "
        "elsewhere rather than being stated directly."
    ),
    default_model=CORA_MODELS["fast"],
    escalation_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.ask._extract_deadline_request",
    required_context=["existing_deadlines", "today", "current_course"],
    output_schema={
        "is_deadline_request": "bool (const true)",
        "missing": "list[title|date|course_id|event_match]",
        "deadlines": "list[{action, event_id, title, course_id, date, time, end_time, type}]",
        "message": "string",
        "ambiguous_context": "bool (optional; triggers one Sonnet escalation retry)",
    },
    validation_rules=[
        "Never invent a date — if it's relative/ambiguous and can't be resolved from the "
        "supplied today/existing_deadlines context, put 'date' in missing and ask, rather "
        "than guessing (.claude/skills/calendar-write-confirmation).",
        "This capability only ever proposes; the confirmation endpoint "
        "(confirm_deadline_actions) is the sole path allowed to write to the calendar, and "
        "it re-resolves update/delete event_ids against the signed-in user's own events "
        "regardless of what this capability claimed.",
    ],
)
