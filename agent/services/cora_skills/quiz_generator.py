"""Skill definition for assessment-grade quiz/practice questions.

Implemented by agent/services/quiz.py::generate_assessment_question_async
(pre-existing, Sonnet — internally chains one Haiku flashcard call for
vocabulary context).
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="quiz_generator",
    description=(
        "Writes one exam-style question (multiple_choice/true_false/open_ended) from a "
        "course chunk that requires understanding, discrimination, or application — not "
        "just matching a term to its definition."
    ),
    triggers=[
        "quiz me on binary search trees",
        "give me a practice question about today's lecture",
        "test me on chapters 4 and 5",
    ],
    trigger_notes=(
        "Reached from the Study/Quiz page directly, and from chat via intent_router's "
        "quiz_or_flashcards intent when the message says 'quiz'/'question'/'test me' rather "
        "than 'flashcard(s)'. Also the engine behind exam practice attempts "
        "(agent/services/exams.py deliberately reuses this rather than a competing "
        "question store)."
    ),
    default_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.quiz.generate_assessment_question_async",
    required_context=["course_chunk", "mastery_score_for_topic", "previous_questions"],
    output_schema={
        "lecture_id": "string",
        "chunk_id": "string",
        "topic": "string",
        "question_type": "multiple_choice|true_false|open_ended",
        "question": "string",
        "choices": "list[string]",
        "correct_answer": "string",
        "explanation": "string",
    },
    validation_rules=[
        "Every question traces to one specific chunk (or syllabus field) selected before "
        "the question is written, never after; difficulty is calibrated from the topic's "
        "current mastery score, not fixed (.claude/skills/quiz-generation).",
        "Never resurface a question already present in previous_questions.",
    ],
)
