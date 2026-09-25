"""Skill definition for lightweight recall flashcards.

Implemented by agent/services/quiz.py::generate_flashcards_async
(pre-existing, Haiku).
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="flashcard_generator",
    description=(
        "Generates quick, definition-focused recall flashcards (term + definition) from "
        "one course chunk, optionally supplemented by scoped web search."
    ),
    triggers=[
        "make me some flashcards for recursion",
        "flashcard the vocab from today's lecture",
    ],
    trigger_notes=(
        "Reached from the Study/Flashcards page directly (no chat routing needed there), "
        "and from chat via intent_router's quiz_or_flashcards intent when the message says "
        "'flashcard(s)' rather than 'quiz'/'question'. These are lightweight recall cards, "
        "not exam-style questions — route a request for something that tests understanding "
        "or application to quiz_generator instead."
    ),
    default_model=CORA_MODELS["fast"],
    implemented_by="agent.services.quiz.generate_flashcards_async",
    required_context=["course_chunk"],
    output_schema={
        "lecture_id": "string",
        "chunk_id": "string",
        "topic": "string",
        "flashcards": "list[{term, definition, source, url}]",
    },
    validation_rules=[
        "Definitions come from the provided chunk first; web search (when available) only "
        "fills in compact definitions matching the chunk's own topic — never introduces an "
        "unrelated fact (.claude/skills/quiz-generation).",
    ],
)
