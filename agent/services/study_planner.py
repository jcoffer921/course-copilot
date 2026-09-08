"""Cross-course, prioritized study planning. build_context() is pure Python,
composing already-existing deterministic services (recommendations.py's
weighted ranking, calendar_events.py's canonical deadlines, streak.py,
study_sessions.py) — generate_plan() only prioritizes and explains what
that context already computed; it never derives a score itself.

See agent/services/cora_skills/study_planner.py for the full routing
contract and validation rules this implements.
"""

import json

from asgiref.sync import sync_to_async

from . import calendar_events, recommendations, reminders, storage, streak, study_sessions
from .client import CORA_MODELS, get_client
from .cora_json import parse_model_json

DEADLINE_WINDOW_DAYS = 21

SYSTEM_PROMPT = """You are Cora's study-planning tool for OnTrack. You are given deterministically \
computed context for one student — ranked topic recommendations (already scored by mastery gap, \
deadline urgency, grading importance, and recency), upcoming deadlines, recent study session activity, \
and their current study streak. Turn this into a short, prioritized, time-boxed study plan.

Rules:
- Never include a course_id that isn't in the supplied "courses" list, or a topic that isn't one of \
the supplied "recommendations" for that course_id. If a plan item is about an upcoming deadline rather \
than a specific weak topic, still only cite a course_id from "courses" and leave the item's specific \
recommendation-backed topic out rather than inventing one.
- Every "reason" must cite an actual figure or fact from the supplied context (a mastery score, a \
deadline date, a recent accuracy note, a rank_score/gap) — never a generic platitude like "this is \
important to review".
- If "available_minutes" is given, the sum of each item's "minutes" should not meaningfully exceed it. \
If it isn't given, default to reasonable session lengths (20-45 minutes per item) and let the total run \
a bit longer.
- Prioritize items with the highest rank_score, but let real urgency (a deadline in the next day or \
two) move something up even with a lower rank_score — explain that trade-off in "reason" when you make it.
- If the supplied context is thin (few or no recommendations/deadlines) for a course, say so plainly in \
that item's reason or in "summary" rather than padding the plan with unsupported confidence.
- "summary" is 1-3 short sentences a student would actually read, not a restatement of the plan list.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "plan": [
    {"course_id": "string", "course_name": "string", "topic": "string|null", "activity": "string", \
"minutes": 0, "reason": "string", "priority": 1}
  ],
  "summary": "string"
}
"""


class NoStudyContextError(Exception):
    """Raised when there's no course, deadline, or recommendation data yet to plan from."""


def build_context(user, available_minutes: int = None, course_ids: list[str] = None) -> dict:
    """Pure Python, no LLM. Every number here comes from an existing
    deterministic service — this function only assembles them."""
    scope_ids = course_ids or reminders.list_courses(user)

    courses = []
    for course_id in scope_ids:
        syllabus = storage.read_syllabus(course_id, user)
        courses.append({"course_id": course_id, "course_name": (syllabus or {}).get("course_name") or course_id})

    ranked = recommendations.rank_recommendations(
        user, session_minutes=available_minutes, limit=15, course_ids=scope_ids,
    )
    deadlines = calendar_events.upcoming_events(user, within_days=DEADLINE_WINDOW_DAYS, course_ids=scope_ids)
    sessions = [
        s for s in study_sessions.list_sessions(user, limit=15)
        if not course_ids or s.get("course_id") in scope_ids
    ]

    return {
        "available_minutes": available_minutes,
        "courses": courses,
        "recommendations": ranked,
        "upcoming_deadlines": [
            {"course_id": e.get("course_id"), "title": e["title"], "date": e["date"], "type": e["type"]}
            for e in deadlines
        ],
        "recent_study_activity": [
            {
                "course_id": s.get("course_id"), "topic": s.get("topic"), "mode": s.get("mode"),
                "status": s.get("status"), "started_at": s.get("started_at"),
            }
            for s in sessions
        ],
        "current_streak_days": streak.current_streak(user),
    }


def _valid_topics_by_course(context: dict) -> dict[str, set[str]]:
    by_course: dict[str, set[str]] = {}
    for item in context["recommendations"]:
        by_course.setdefault(item["course_id"], set()).add(item["topic"])
    return by_course


async def generate_plan(user, available_minutes: int = None, course_ids: list[str] = None) -> dict:
    context = await sync_to_async(build_context)(user, available_minutes, course_ids)
    if not context["courses"]:
        raise NoStudyContextError("no courses available yet to build a study plan from")

    client = get_client()
    response = await client.messages.create(
        model=CORA_MODELS["reasoning"],
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context, default=str)}],
    )
    raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    data = parse_model_json(raw, required_keys={"plan", "summary"})

    valid_course_ids = {c["course_id"] for c in context["courses"]}
    valid_topics = _valid_topics_by_course(context)
    course_names = {c["course_id"]: c["course_name"] for c in context["courses"]}

    plan = []
    for item in data.get("plan") or []:
        if not isinstance(item, dict):
            continue
        course_id = item.get("course_id")
        if course_id not in valid_course_ids:
            continue
        topic = item.get("topic") or None
        if topic and topic not in valid_topics.get(course_id, set()):
            continue
        plan.append({
            "course_id": course_id,
            "course_name": course_names.get(course_id, course_id),
            "topic": topic,
            "activity": str(item.get("activity", "")).strip(),
            "minutes": item.get("minutes") if isinstance(item.get("minutes"), (int, float)) else None,
            "reason": str(item.get("reason", "")).strip(),
            "priority": item.get("priority") if isinstance(item.get("priority"), int) else None,
        })

    return {"plan": plan, "summary": str(data.get("summary", "")).strip()}
