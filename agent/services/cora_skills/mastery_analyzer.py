"""Skill definition for interpreting (not computing) mastery data.

Implemented by agent/services/mastery_analyzer.py::analyze (new). All scores
are computed deterministically by agent/services/mastery.py (EWMA, no LLM) —
this capability only interprets the pattern across recent quiz attempts that
those scores summarize.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="mastery_analyzer",
    description=(
        "Interprets a topic's mastery score and recent quiz-attempt history into a "
        "concrete, evidenced pattern (e.g. 'misses base-case recursion questions but does "
        "fine on tracing') and an actionable recommendation."
    ),
    triggers=[
        "how am I doing with binary trees",
        "why do I keep getting recursion questions wrong",
        "why has my performance been declining",
    ],
    trigger_notes=(
        "Route here when the student asks WHY their performance looks a certain way, or "
        "for an explanation of a pattern — not for the raw number itself (that's already "
        "in course_qa's LEARNING_TOOLS context, or the Mastery page directly). A request "
        "spanning multiple topics/courses with 'what should I do about it' belongs in "
        "study_planner instead."
    ),
    default_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.mastery_analyzer.analyze",
    required_context=["mastery_scores", "recent_quiz_attempts"],
    output_schema={
        "insight": "string",
        "recommended_action": "string",
        "confidence": "high|medium|low",
    },
    validation_rules=[
        "Never state a pattern the supplied attempt data doesn't actually support — this "
        "reuses the three-way miss classification from .claude/skills/wrong-answer-analysis "
        "(concept gap / carelessness / ambiguous question) as its vocabulary for describing "
        "what a wrong answer means, rather than defaulting every miss to 'doesn't understand "
        "the concept'.",
        "'confidence' must reflect how much attempt data actually exists — low with only "
        "one or two attempts, never inflated to sound more certain than the evidence.",
    ],
)
