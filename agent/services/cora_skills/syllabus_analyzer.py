"""Skill definition for syllabus -> syllabus.json extraction.

Implemented by agent/services/syllabus_extraction.py::extract_syllabus_async
(pre-existing). Triggered by a Materials-page upload, not by chat text — no
chat intent maps to this capability today.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="syllabus_analyzer",
    description=(
        "Interprets an uploaded syllabus into structured course data: course name, "
        "meeting patterns, dates, grading breakdown, and topics."
    ),
    triggers=[],  # upload-triggered, not chat-classified
    trigger_notes=(
        "Not reachable through intent_router — it runs when a syllabus file is uploaded "
        "on the Materials page (ExtractSyllabusView -> materials.stage_syllabus), always "
        "stopping at a needs_review candidate for the student to confirm before "
        "syllabus.json is replaced. See .claude/skills/syllabus-extraction for the "
        "non-negotiable 'confidence over completeness' rule this must follow."
    ),
    default_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.syllabus_extraction.extract_syllabus_async",
    required_context=["uploaded_document"],
    output_schema={
        "course_id": "string",
        "course_name": "string",
        "meeting_patterns": "list[object]",
        "dates": "list[{date, title, type}]",
        "grading": "list[{component, weight_pct, total_items, drop_lowest}]",
        "topics": "list[string]",
    },
    validation_rules=[
        "Never guess a missing year or invent a grading weight to force categories to sum "
        "to 100%; drop an incomplete date/grading entry rather than fabricate the missing "
        "field (.claude/skills/syllabus-extraction).",
    ],
)
