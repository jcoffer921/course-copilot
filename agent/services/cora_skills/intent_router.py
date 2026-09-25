"""Skill definition for Cora's own front-door classifier.

Implemented by agent/services/intent_router.py. This is the one capability
that never itself talks to the student — it only decides which other
capability does.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="intent_router",
    description=(
        "Classifies an already-chat-routed student message (one the free "
        "deterministic checks in ask.py didn't already resolve) into exactly "
        "one downstream capability."
    ),
    triggers=[],  # this skill classifies everything else; it has no triggers of its own
    trigger_notes=(
        "Not itself selected by anything — ask.py calls this directly, after its own "
        "free regex checks (deadline/save-site requests) have already failed to match. "
        "Every intent value this classifier can return must correspond to exactly one "
        "other entry in CAPABILITIES."
    ),
    default_model=CORA_MODELS["fast"],
    implemented_by="agent.services.intent_router.classify",
    required_context=[],
    output_schema={
        "intent": (
            "general_assistant|study_planner|mastery_analyzer|document_summary_quick|"
            "document_summary_deep|quiz_or_flashcards|course_qa|unknown"
        ),
        "requires_course_context": "bool",
    },
    validation_rules=[
        "Any exception, timeout, or value outside the enum above must be treated as "
        "intent='course_qa' — never let a classification failure block or surface to "
        "the student. course_qa is today's existing default grounded-answer pipeline, "
        "so a failed classification is a silent no-op, not a degraded experience.",
        "'unknown' routes to the same course_qa fallback as a classifier error — it "
        "exists as an explicit, honest value the model can return rather than forcing "
        "a guess among the specific capabilities.",
        "document_summary_quick/document_summary_deep both implement the "
        "document_summarizer capability at different depths; quiz_or_flashcards covers "
        "both the quiz_generator and flashcard_generator capabilities — the calling code "
        "(ask.py), not this classifier, decides between them from phrasing (\"flashcards\" "
        "vs \"quiz me\"/\"question\").",
    ],
)
