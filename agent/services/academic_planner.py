"""
Academic planner chat — faculty hold a conversation with Cora to draft a
student's semester-by-semester plan for a confirmed program. Same async/
JSON-envelope shape as ask_async in ask.py, but scoped to a single
ProgramRequirement as its only source of truth (no syllabus/notes/web
grounding — that's ask.py's job for a student's own course questions).

Nothing here writes to disk or the database. All state (student details,
conversation history, draft plan) lives in the caller's session only — see
agent/views.py's FacultyPlanChatView/FacultyPlanResetView, which read and
write request.session["faculty_plan_session"].
"""

import json
import logging
import re

from .client import MODEL_DEFAULT as MODEL, create_message, get_client

logger = logging.getLogger(__name__)

ACADEMIC_PLANNER_SYSTEM_PROMPT = """You are Cora, helping a faculty member draft a semester-by-semester \
academic plan for a student in their program.

You will be given:
1. PROGRAM_REQUIREMENTS: the complete, confirmed requirements structure for this program — \
categories, courses, credits, and prerequisites. This is your ONLY source of courses and credit \
counts. Never propose a course, prerequisite, or credit count that isn't present in it.
2. STUDENT_DETAILS: facts the faculty member has supplied so far about this specific student \
(intended major/concentration, completed coursework, transfer credit, target graduation term, etc.). \
This starts empty.
3. The conversation so far.

Rules:
- Before drafting any plan, make sure you know the student's intended major/concentration and what \
coursework (if any) they've already completed. If STUDENT_DETAILS is missing either of these, ask a \
clarifying question instead of drafting — do not guess or draft a premature plan.
- Every course in a drafted plan must appear in PROGRAM_REQUIREMENTS' categories[].courses[], with the \
exact code and credits given there. Respect stated prerequisites when sequencing courses across \
semesters — a course cannot appear before its prerequisite's semester.
- Do not repeat a course the student has already completed (per STUDENT_DETAILS) in the drafted plan.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "reply": "string — your conversational response to the faculty member",
  "student_details": {"...": "..."},
  "draft_plan": null OR {
    "student_major": "string",
    "semesters": [{"label": "string", "courses": [{"code": "string", "title": "string", "credits": 0}]}],
    "total_credits": 0,
    "notes": "string"
  }
}

Notes on fields:
- "reply" is always present — your conversational message, e.g. a clarifying question or a summary of \
the plan you just drafted.
- "student_details" is STUDENT_DETAILS carried forward, merged with anything new you learned this \
turn. Never drop a fact that was already there.
- "draft_plan" is null until you have enough information to draft (or redraft) a plan; once you draft \
one, keep including your best current draft_plan on every later turn (updated as new facts come in), \
not null again, unless the faculty member asks you to discard it.
"""


def _parse_model_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        decoder = json.JSONDecoder()
        candidates = []
        for match in re.finditer(r"{", raw):
            try:
                obj, _ = decoder.raw_decode(raw[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "reply" in obj:
                candidates.append(obj)
        if candidates:
            return candidates[-1]
        raise ValueError(f"model did not return valid JSON: {e}\n\nRaw output:\n{raw}")


def _valid_course_codes(program_requirement: dict) -> set:
    codes = set()
    for category in program_requirement.get("categories") or []:
        for course in category.get("courses") or []:
            code = course.get("code")
            if code:
                codes.add(code)
    return codes


def _enforce_grounding(draft_plan: dict | None, program_requirement: dict) -> dict | None:
    """Drops any course the model proposed that isn't actually in the
    ProgramRequirement, rather than surfacing a fabricated course to the
    faculty member. Logs when this happens so we can see how often it does."""
    if not isinstance(draft_plan, dict):
        return None

    valid_codes = _valid_course_codes(program_requirement)
    semesters = []
    for semester in draft_plan.get("semesters") or []:
        if not isinstance(semester, dict):
            continue
        kept_courses = []
        for course in semester.get("courses") or []:
            if not isinstance(course, dict):
                continue
            code = course.get("code")
            if code in valid_codes:
                kept_courses.append(course)
            else:
                logger.warning(
                    "academic_planner: dropped ungrounded course %r not present in program_requirement",
                    code,
                )
        semesters.append({
            "label": str(semester.get("label") or ""),
            "courses": kept_courses,
        })

    return {
        "student_major": str(draft_plan.get("student_major") or ""),
        "semesters": semesters,
        "total_credits": sum(
            course.get("credits") or 0 for semester in semesters for course in semester["courses"]
        ),
        "notes": str(draft_plan.get("notes") or ""),
    }


async def plan_chat_async(
    program_requirement: dict, student_details: dict, conversation: list, message: str, user=None,
) -> dict:
    client = get_client()

    # student_details is resent as part of the system prompt on every call —
    # same rationale as ask.py's context block: it's the latest merged state,
    # not a point-in-time snapshot, so it belongs beside PROGRAM_REQUIREMENTS
    # rather than embedded in one specific turn of the replayed conversation.
    system = (
        ACADEMIC_PLANNER_SYSTEM_PROMPT
        + f"\n\nPROGRAM_REQUIREMENTS:\n{json.dumps(program_requirement, indent=2)}"
        + f"\n\nSTUDENT_DETAILS:\n{json.dumps(student_details, indent=2)}"
    )

    # Prior assistant turns are replayed in the same JSON envelope the system
    # prompt demands (not plain reply text) so the model doesn't drift away
    # from the required JSON format on later turns — same fix ask_async
    # applies for its own multi-turn replay (see its docstring).
    messages = []
    for turn in conversation:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "assistant":
            envelope = json.dumps({"reply": content, "student_details": student_details, "draft_plan": None})
            messages.append({"role": "assistant", "content": envelope})
        elif role == "user":
            messages.append({"role": "user", "content": content})
    messages.append({"role": "user", "content": message})

    response = await create_message(
        client, user,
        model=MODEL,
        max_tokens=4000,
        system=system,
        messages=messages,
    )

    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    data = _parse_model_json(raw)

    updated_student_details = data.get("student_details")
    if not isinstance(updated_student_details, dict):
        updated_student_details = student_details

    return {
        "reply": str(data.get("reply") or ""),
        "student_details": updated_student_details,
        "draft_plan": _enforce_grounding(data.get("draft_plan"), program_requirement),
    }
