"""
Exam workspace: a mutable ExamPlan layered over one confirmed test_quiz-type
calendar event — never a duplicate of the event itself. The event is always
resolved live from calendar_events.py's canonical read model by its id, so a
deleted or rescheduled event (which changes a syllabus-derived event's id)
safely surfaces as "not found" rather than showing stale data.

Composes existing systems rather than building new ones: mastery.py for
readiness by topic, CourseMaterial for the source library, and citations.py
for grounding the generated study guide. Practice questions reuse quiz.py's
existing generation/recording directly (topic-scoped to the plan) — this
module deliberately does not add another question store.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import calendar_events, citations, mastery, quiz, storage
from .client import MODEL_HAIKU, get_client

EXAM_EVENT_TYPE = "test_quiz"
READINESS_MASTERY_WEIGHT = 0.70
READINESS_COVERAGE_WEIGHT = 0.15
READINESS_RECENCY_WEIGHT = 0.15

STUDY_GUIDE_SYSTEM_PROMPT = """You are building a concise exam study guide for OnTrack from ONLY \
the provided course material for the listed topics (and any references given).

Rules:
- Write one section per topic, in the order given, using the exact topic name provided.
- Each section gets 3-6 short key-point bullets a student should know before the exam.
- Do not include anything not supported by the provided material.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "sections": [
    {"topic": "string", "key_points": ["string", ...]}
  ]
}
"""


class ExamNotFoundError(Exception):
    """No confirmed test_quiz event with this id exists for this user's course."""


class NoStudyMaterialSelectedError(Exception):
    """Raised when generating a study guide with nothing usable selected."""


def find_exam_event(user, course_id: str, event_id: str) -> dict:
    """Resolves the live, owned, confirmed test_quiz event this workspace is
    for. Always looked up fresh against the current calendar — never cached
    — so this is the one place that makes a stale ExamPlan (its event
    deleted or rescheduled to a new id) surface safely instead of crashing
    or serving stale content."""
    storage._validate_course_id(course_id)
    for event in calendar_events.all_events(user, course_ids=[course_id]):
        if event["id"] == event_id and event["type"] == EXAM_EVENT_TYPE:
            return event
    raise ExamNotFoundError(f"no exam '{event_id}' found for course '{course_id}'")


def list_exams(user, course_id: str, now: datetime = None) -> list:
    """Every confirmed test_quiz event for this course, soonest first."""
    storage._validate_course_id(course_id)
    now = now or datetime.now(timezone.utc)
    events = [e for e in calendar_events.all_events(user, course_ids=[course_id]) if e["type"] == EXAM_EVENT_TYPE]
    events.sort(key=lambda e: e["date"])
    return [
        {
            "id": e["id"],
            "title": e["title"],
            "date": e["date"],
            "days_until": (datetime.strptime(e["date"], "%Y-%m-%d").date() - now.date()).days,
        }
        for e in events
    ]


def _ready_materials(user, course_id: str):
    from agent.models import CourseMaterial

    return (
        CourseMaterial.objects.filter(user=user, course_id=course_id, processing_status=CourseMaterial.STATUS_READY)
        .exclude(review_status=CourseMaterial.REVIEW_SUPERSEDED)
        .order_by("-uploaded_at")
    )


def _default_plan_state(user, course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id, user)
    topics = list(syllabus.get("topics", [])) if syllabus else []
    material_ids = [str(m.material_id) for m in _ready_materials(user, course_id)]
    return {"included_topics": topics, "included_material_ids": material_ids}


def _plan_dict(plan) -> dict:
    return {
        "included_topics": plan.included_topics,
        "included_material_ids": plan.included_material_ids,
        "study_guide": plan.study_guide,
        "updated_at": plan.updated_at.isoformat(),
    }


def _get_or_create_plan_row(user, course_id: str, event_id: str):
    from agent.models import ExamPlan

    plan, _ = ExamPlan.objects.get_or_create(
        user=user, event_id=event_id,
        defaults={"course_id": course_id, **_default_plan_state(user, course_id)},
    )
    return plan


def get_or_create_plan(user, course_id: str, event_id: str) -> dict:
    return _plan_dict(_get_or_create_plan_row(user, course_id, event_id))


def update_plan(user, course_id: str, event_id: str, included_topics: list = None, included_material_ids: list = None) -> dict:
    """Confirms which topics/materials are in scope for this exam. Silently
    drops anything not actually owned/valid rather than rejecting the whole
    request — a stale client-side list (a topic renamed, a material deleted
    since page load) is a normal state here, not an error."""
    find_exam_event(user, course_id, event_id)  # raises ExamNotFoundError if stale/deleted/rescheduled/not owned
    plan = _get_or_create_plan_row(user, course_id, event_id)
    update_fields = []

    if included_topics is not None:
        syllabus = storage.read_syllabus(course_id, user) or {}
        valid_topics = set(syllabus.get("topics", []))
        plan.included_topics = [t for t in included_topics if t in valid_topics]
        update_fields.append("included_topics")

    if included_material_ids is not None:
        owned_ready_ids = {str(m.material_id) for m in _ready_materials(user, course_id)}
        plan.included_material_ids = [m for m in included_material_ids if m in owned_ready_ids]
        update_fields.append("included_material_ids")

    if update_fields:
        plan.save(update_fields=[*update_fields, "updated_at"])
    return _plan_dict(plan)


def build_workspace(user, course_id: str, event_id: str, now: datetime = None) -> dict:
    """Everything the exam workspace page needs in one call: the resolved
    event, its countdown, the plan, per-topic readiness, and the owned
    source library — always recomputed fresh, so a mastery rebuild or a new
    upload is reflected on the very next call."""
    from agent.models import StudySession, UserSettings

    settings, _ = UserSettings.objects.get_or_create(user=user)
    user_zone = ZoneInfo(settings.timezone)
    supplied_now = now is not None
    now = now or datetime.now(timezone.utc)
    # Injected test/service times represent the caller's already-selected
    # local date. Runtime UTC timestamps are converted to the user's zone.
    local_today = now.date() if supplied_now else now.astimezone(user_zone).date()
    event = find_exam_event(user, course_id, event_id)
    plan = get_or_create_plan(user, course_id, event_id)

    event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
    days_until = (event_date - local_today).days

    mastery_by_topic = {row["topic"]: row for row in mastery.weak_topics(course_id, user=user)}
    syllabus = storage.read_syllabus(course_id, user) or {}
    topics = [
        {
            "topic": topic,
            "included": topic in plan["included_topics"],
            "status": mastery_by_topic.get(topic, {}).get("status", mastery.NOT_STARTED),
            "score": mastery_by_topic.get(topic, {}).get("score"),
            "reason": mastery_by_topic.get(topic, {}).get("reason", "Not started yet."),
        }
        for topic in syllabus.get("topics", [])
    ]
    weak_topics = sorted(
        (t for t in topics if t["included"] and t["status"] not in {mastery.PROFICIENT, mastery.EXAM_READY}),
        key=lambda t: t["score"] if t["score"] is not None else -1,
    )

    materials = [
        {
            "material_id": str(m.material_id),
            "original_filename": m.original_filename,
            "material_type": m.material_type,
            "included": str(m.material_id) in plan["included_material_ids"],
        }
        for m in _ready_materials(user, course_id)
    ]

    included = [topic for topic in topics if topic["included"]]
    known_scores = [topic["score"] for topic in included if topic["score"] is not None]
    mastery_factor = sum(known_scores) / len(known_scores) if known_scores else 0.0
    coverage_factor = len(known_scores) / len(included) if included else 0.0
    recent_cutoff = now - timedelta(days=30)
    recent_sessions = StudySession.objects.filter(
        user=user, course_id=course_id, status=StudySession.STATUS_COMPLETED, completed_at__gte=recent_cutoff,
    ).count()
    recency_factor = min(recent_sessions / max(len(included), 1), 1.0)
    readiness_score = round(100 * (
        READINESS_MASTERY_WEIGHT * mastery_factor
        + READINESS_COVERAGE_WEIGHT * coverage_factor
        + READINESS_RECENCY_WEIGHT * recency_factor
    ))
    readiness_label = (
        "Nearly exam ready" if readiness_score >= 80 else
        "Making good progress" if readiness_score >= 60 else
        "Needs focused preparation" if readiness_score >= 30 else
        "Just getting started"
    )
    strongest = sorted(included, key=lambda item: item["score"] if item["score"] is not None else -1, reverse=True)[:2]
    recommendation = weak_topics[0] if weak_topics else (included[0] if included else None)

    session_minutes = settings.preferred_session_minutes
    active_days = max(days_until, 1)
    block_count = max(1, min(12, len(included) * 2)) if included else 0
    first_span = max(1, active_days // 2)
    plan_phases = []
    if recommendation:
        plan_phases.append({
            "label": "Focus now", "date_range": f"Next {first_span} day{'s' if first_span != 1 else ''}",
            "topic": recommendation["topic"], "blocks": max(1, block_count // 2),
            "minutes": max(1, block_count // 2) * session_minutes, "status": "in_progress",
        })
        if len(included) > 1:
            plan_phases.append({
                "label": "Build coverage", "date_range": "Before final review", "topic": "Remaining exam topics",
                "blocks": max(1, block_count - max(1, block_count // 2) - 1),
                "minutes": max(1, block_count - max(1, block_count // 2) - 1) * session_minutes, "status": "upcoming",
            })
        plan_phases.append({
            "label": "Final review", "date_range": "Day before exam", "topic": "Mixed practice & review",
            "blocks": 1, "minutes": session_minutes, "status": "upcoming",
        })

    course = storage.read_course_metadata(course_id, user) or syllabus

    return {
        "event": {"id": event["id"], "title": event["title"], "date": event["date"], "course_id": course_id},
        "course_name": course.get("course_name", course_id.upper()),
        "days_until": days_until,
        "timezone": settings.timezone,
        "plan": plan,
        "preparation": {"phases": plan_phases, "total_minutes": sum(phase["minutes"] for phase in plan_phases)},
        "readiness": {
            "score": readiness_score, "label": readiness_label,
            "strong_topics": [item["topic"] for item in strongest if item["score"] is not None],
            "factors": {"mastery": mastery_factor, "coverage": coverage_factor, "recent_practice": recency_factor},
        },
        "recommendation": ({
            "topic": recommendation["topic"], "readiness": round((recommendation["score"] or 0) * 100),
            "reason": recommendation["reason"],
            "factors": ["Lowest current readiness", "Included in this exam", "Benefits from focused recent practice"],
        } if recommendation else None),
        "topics": topics,
        "weak_topics": weak_topics,
        "materials": materials,
    }


def _split_material_ids(user, course_id: str, material_ids: list) -> tuple:
    from agent.models import CourseMaterial

    rows = CourseMaterial.objects.filter(user=user, course_id=course_id, material_id__in=material_ids)
    lecture_ids = {r.source_key for r in rows if r.material_type in (CourseMaterial.TYPE_NOTES, CourseMaterial.TYPE_SLIDES)}
    reference_ids = {r.source_key for r in rows if r.material_type == CourseMaterial.TYPE_REFERENCE}
    return lecture_ids, reference_ids


def _topic_chunks(course_id: str, user, included_topics: list, included_lecture_ids: set) -> dict:
    chunks_by_topic = {topic: [] for topic in included_topics}
    for lecture in storage.read_notes(course_id, user):
        if lecture.get("lecture_id") not in included_lecture_ids:
            continue
        for chunk in lecture.get("chunks", []):
            topic = chunk.get("topic")
            if topic in chunks_by_topic:
                chunks_by_topic[topic].append({"lecture_id": lecture["lecture_id"], "chunk_id": chunk.get("id"), "text": chunk.get("text", "")})
    return chunks_by_topic


def _resolve_citation(user, course_id: str, label: str, bias_text: str):
    try:
        return citations.resolve_citations(user, course_id, [label], bias_text, bias_text)[0]
    except ValueError:
        return None


async def generate_study_guide(user, course_id: str, event_id: str) -> dict:
    """Generates (and saves onto the plan) a study guide from ONLY the
    plan's currently-included topics/materials, with a citation per section
    resolved through the existing owned-source citation resolver — never an
    unowned or fabricated source."""
    from asgiref.sync import sync_to_async

    await sync_to_async(find_exam_event)(user, course_id, event_id)
    plan = await sync_to_async(get_or_create_plan)(user, course_id, event_id)
    if not plan["included_topics"]:
        raise NoStudyMaterialSelectedError("select at least one topic before generating a study guide")

    included_lecture_ids, included_reference_ids = await sync_to_async(_split_material_ids)(
        user, course_id, plan["included_material_ids"]
    )
    topic_chunks = await sync_to_async(_topic_chunks)(course_id, user, plan["included_topics"], included_lecture_ids)
    topics_with_material = [t for t in plan["included_topics"] if topic_chunks.get(t)]
    if not topics_with_material and not included_reference_ids:
        raise NoStudyMaterialSelectedError("none of the selected material has usable content yet")

    reference_texts = []
    for reference_id in sorted(included_reference_ids):
        reference = await sync_to_async(storage.read_reference)(course_id, reference_id, user)
        if reference:
            reference_texts.append(f"Reference — {reference.get('title', reference_id)}:\n{reference.get('text', '')}")

    prompt_sections = [
        f"Topic: {topic}\n" + "\n".join(c["text"] for c in topic_chunks[topic])
        for topic in topics_with_material
    ]
    user_prompt = "\n\n---\n\n".join(prompt_sections + reference_texts)

    client = get_client()
    response = await client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=2048,
        system=STUDY_GUIDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text").strip()
    data = quiz._parse_json(raw)

    sections = []
    for section in data.get("sections", []):
        topic = section.get("topic")
        key_points = [str(p).strip() for p in section.get("key_points", []) if str(p).strip()]
        if topic not in topics_with_material or not key_points:
            continue
        lecture_id = sorted(c["lecture_id"] for c in topic_chunks[topic])[0]
        citation = await sync_to_async(_resolve_citation)(user, course_id, lecture_id, topic)
        sections.append({"topic": topic, "key_points": key_points, "citation": citation})

    if not sections:
        raise ValueError(f"model did not return any usable study-guide sections: {data}")

    reference_citations = []
    for reference_id in sorted(included_reference_ids):
        citation = await sync_to_async(_resolve_citation)(user, course_id, reference_id, "")
        if citation:
            reference_citations.append(citation)

    guide = {
        "sections": sections,
        "reference_citations": reference_citations,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    def _save():
        from agent.models import ExamPlan

        ExamPlan.objects.filter(user=user, event_id=event_id).update(study_guide=guide)

    await sync_to_async(_save)()
    return guide
