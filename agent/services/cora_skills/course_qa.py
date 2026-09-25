"""Skill definition for grounded, course-scoped Q&A.

Implemented by agent/services/ask.py::ask_async (the pre-existing default
path). This is intent_router's fallback/default — it's what already runs
today for every chat message that isn't a deadline/save-site request, a
small_talk greeting, or one of the newer specialized intents.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="course_qa",
    description=(
        "Answers a question about ONE course using only that course's syllabus, notes, "
        "references, saved sites, recalled conversation, and learning-tool data "
        "(quiz/flashcard/mastery/grades) — never outside knowledge."
    ),
    triggers=[
        "explain recursion using my professor's notes",
        "what did professor smith say about the final project",
        "how are chapters 4 and 5 connected",
        "compare the two algorithms from this week's notes",
        "what's my grade breakdown",
        "when's the project due",  # only when NOT caught by the deterministic deadline regex first
    ],
    trigger_notes=(
        "This is the default/fallback intent — route here whenever no other capability's "
        "trigger_notes clearly fit. A single, specific, single-course question about "
        "material, grades, or a specific fact stays here even if it references mastery "
        "or quiz history, since ASK_SYSTEM_PROMPT's LEARNING_TOOLS context already covers "
        "that. Only escalate to study_planner when the student is asking for cross-topic or "
        "cross-course PRIORITIZATION, and to mastery_analyzer when they're asking WHY their "
        "performance looks a certain way (a pattern across attempts), not just what it is."
    ),
    default_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.ask.ask_async",
    required_context=["course_materials", "learning_tools", "recalled_conversations"],
    output_schema={
        "answer": "string",
        "grounded": "bool",
        "sources": "list[string]",
    },
    validation_rules=[
        "Never answer from general/training knowledge as if it were this course's material "
        "(see .claude/skills/grounded-answering and grounding-check for the full, "
        "non-negotiable rule this capability must follow).",
    ],
)
