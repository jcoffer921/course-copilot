"""Cora's runtime capability registry.

This is NOT the repo's .claude/skills/ directory — that's dev-tooling
Claude Code follows while *building* this app. Everything in this package
ships inside the Django app itself and is read at runtime by
agent/services/intent_router.py to decide which capability should handle a
chat message, which model it should use, and what context it needs.

One module per capability, each exporting a single module-level `SKILL =
CoraSkill(...)`. This __init__ aggregates them into CAPABILITIES so there is
exactly one place — this package — that routing logic, the intent_router's
generated prompt, and this package's own tests all read from. Adding or
refining a capability's trigger criteria means editing its one file here;
nothing else needs to change for the router to pick it up.

Six of these capabilities are implemented by services that already existed
before this registry (syllabus_analyzer, calendar_extractor,
flashcard_generator, quiz_generator, course_qa, general_assistant) — they
still get a skill file so there's one authoritative place documenting their
trigger criteria and schema, even though `implemented_by` just points at
already-shipped functions.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CoraSkill:
    name: str
    description: str
    # Example user phrasings the intent_router's classification prompt is
    # literally rendered from — keep these realistic, not exhaustive.
    triggers: list[str]
    # Free-text routing guidance: when to pick this capability over a
    # neighboring one. This is the part that actually disambiguates.
    trigger_notes: str
    default_model: str
    # Dotted path to the function that implements this capability, for
    # documentation/introspection only — this registry never calls it.
    implemented_by: str
    required_context: list[str] = field(default_factory=list)
    escalation_model: str | None = None
    output_schema: dict | None = None
    validation_rules: list[str] = field(default_factory=list)


from . import (  # noqa: E402 (must follow CoraSkill's definition)
    calendar_extractor,
    course_qa,
    document_summarizer,
    flashcard_generator,
    general_assistant,
    intent_router,
    mastery_analyzer,
    quiz_generator,
    study_planner,
    syllabus_analyzer,
)

_MODULES = (
    intent_router,
    syllabus_analyzer,
    calendar_extractor,
    document_summarizer,
    flashcard_generator,
    quiz_generator,
    study_planner,
    mastery_analyzer,
    course_qa,
    general_assistant,
)

CAPABILITIES: dict[str, CoraSkill] = {module.SKILL.name: module.SKILL for module in _MODULES}

__all__ = ["CoraSkill", "CAPABILITIES"]
