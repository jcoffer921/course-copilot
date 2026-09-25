"""Skill definition for cross-course, prioritized study planning.

Implemented by agent/services/study_planner.py::generate_plan (new). Its
context (build_context) is pure Python, reusing calendar_events,
recommendations, mastery, streak, and study_sessions — this capability's job
is only to prioritize and explain, never to compute the underlying numbers.
"""

from ..client import CORA_MODELS
from . import CoraSkill

SKILL = CoraSkill(
    name="study_planner",
    description=(
        "Combines upcoming deadlines, exam proximity, mastery levels, recent quiz/"
        "flashcard performance, and study history into a prioritized, time-boxed study "
        "plan across the student's courses."
    ),
    triggers=[
        "what should I study tonight",
        "I have about two hours, what should I focus on",
        "help me plan my studying this week",
        "what should I focus on before my exam",
    ],
    trigger_notes=(
        "Route here whenever the student asks for prioritization across more than one "
        "topic or course, or names an amount of available time/asks 'what should I do'. "
        "A question about one specific named topic's status or due date belongs in "
        "course_qa or the deterministic calendar path instead — this capability is for "
        "deciding WHAT COMES FIRST, not for answering a single fact."
    ),
    default_model=CORA_MODELS["reasoning"],
    implemented_by="agent.services.study_planner.generate_plan",
    required_context=["calendar", "mastery", "recommendations", "recent_activity", "streak"],
    output_schema={
        "plan": "list[{course_id, course_name, topic, activity, minutes, reason, priority}]",
        "summary": "string",
    },
    validation_rules=[
        "Never include a course_id/topic/deadline that isn't present in the supplied "
        "deterministic context — build_context() computes every number this capability is "
        "allowed to reason over; nothing is invented on top of it.",
        "Every 'reason' must trace back to an actual figure from the context (a mastery "
        "score, a deadline date, a recent accuracy drop) — never a generic platitude.",
        "When calendar or mastery data for a course is thin/absent, say so plainly in that "
        "item's reason instead of padding the plan with unsupported confidence.",
    ],
)
