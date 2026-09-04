"""Skill definition for summarizing one lecture/reference document.

Implemented by agent/services/document_summarizer.py::summarize (new).
depth="quick" is Haiku; depth="deep" is Sonnet. Both read only the one
targeted document's text (via storage.read_notes/read_references) — no
retrieval system, matching the project's existing full-context-stuffing
decision documented in CLAUDE.md.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="document_summarizer",
    description=(
        "Summarizes one lecture's notes or one reference document, either as a quick bullet "
        "recap (Haiku) or a deep academic breakdown of key concepts, definitions, "
        "relationships, and likely-testable material (Sonnet)."
    ),
    triggers=[
        "give me a quick summary of this page",
        "summarize today's lecture",
        "teach me what this lecture means and what I need for the exam",
        "what should I understand before tomorrow's lecture",
    ],
    trigger_notes=(
        "'quick summary'/'tl;dr'/short recap phrasing routes to document_summary_quick "
        "(Haiku). Anything implying the student wants to actually learn/understand the "
        "material, prepare for an exam, or see how concepts relate routes to "
        "document_summary_deep (Sonnet) — when genuinely ambiguous, default to deep, since a "
        "student asking Cora (rather than just skimming the page themselves) usually wants "
        "more than a shorter copy of the text."
    ),
    default_model=CORA_MODELS["fast"],
    escalation_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.document_summarizer.summarize",
    required_context=["target_lecture_or_reference_text"],
    output_schema={
        "quick": {"source_id": "string", "title": "string", "summary": "string"},
        "deep": {
            "source_id": "string",
            "title": "string",
            "key_concepts": "list[string]",
            "definitions": "list[{term, definition}]",
            "relationships": "list[string]",
            "likely_testable": "list[string]",
        },
    },
    validation_rules=[
        "Every concept/definition/relationship must be traceable to the target document's "
        "own text — never introduce an outside fact or technique, same no-outside-knowledge "
        "boundary .claude/skills/grounded-answering enforces for chat.",
        "If no lecture_id/reference_id resolves to real content, say so rather than "
        "summarizing something else or fabricating content.",
    ],
)
