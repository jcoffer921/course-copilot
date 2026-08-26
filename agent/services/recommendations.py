"""
Deterministic "what should I study next" ranking — no LLM. Every
recommendation's priority and explanation come from structured facts
(deadline urgency, assessment importance when known, mastery gap, and
recency) so the reason shown to a student is always traceable to the same
numbers that produced the ordering, never an invented rationale.

Recommendations are computed fresh on every call from mastery/deadline/
syllabus data that already exists elsewhere — nothing here is itself a
source of truth except which recommendations a student has dismissed or
deferred, which never affects the underlying academic data it's computed
from.
"""

from datetime import datetime, timezone

from . import mastery, reminders, storage

# A deadline this far out (or further) contributes ~0 urgency; overdue or
# due-today deadlines are maximally urgent.
URGENCY_HORIZON_DAYS = 14

# A topic not studied in this long is treated as fully "due for review";
# never-studied topics are treated as already past this horizon.
STALE_HORIZON_DAYS = 21

# A topic with no mastery data yet gets a moderate (not maximal) gap, so
# genuinely weak topics still outrank "haven't started" ones.
NEVER_ASSESSED_GAP = 0.6

ASSESSMENT_TYPES = {"test_quiz", "project"}
IMPORTANCE_BY_TYPE = {"test_quiz": 1.0, "project": 0.7, "hw": 0.4, "class": 0.1, "other": 0.1}

# Ranking weights, sum to 1.0 — deliberately kept as named constants (not
# inlined) so the explanation text and the score can cite the same numbers.
WEIGHT_GAP = 0.35
WEIGHT_URGENCY = 0.25
WEIGHT_IMPORTANCE = 0.15
WEIGHT_RECENCY = 0.25

SHORT_SESSION_MINUTES = 12  # at/below this, suggest flashcards only, not a full mixed session


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None


def _urgency(deadline: dict, today) -> float:
    if deadline is None:
        return 0.0
    deadline_date = _parse_date(deadline.get("date"))
    if deadline_date is None:
        return 0.0
    days_until = (deadline_date - today).days
    if days_until <= 0:
        return 1.0
    return max(0.0, 1.0 - days_until / URGENCY_HORIZON_DAYS)


def _grading_components(course_id: str, user) -> dict:
    syllabus = storage.read_syllabus(course_id, user)
    if not syllabus:
        return {}
    return {
        str(item.get("component") or "").strip().lower(): item.get("weight_pct", 0)
        for item in syllabus.get("grading", [])
        if isinstance(item, dict) and item.get("component")
    }


def _importance(deadline: dict, grading_components: dict) -> tuple:
    """Returns (importance 0..1, matched grading component name or None).
    Prefers a real grading weight when the deadline's title resolves to one
    of the syllabus's grading components; falls back to a coarse type-based
    tier ("assessment importance when known" — and honestly guessed when
    it isn't)."""
    if deadline is None:
        return 0.0, None
    title = str(deadline.get("title") or "").strip().lower()
    if title:
        for component, weight_pct in grading_components.items():
            if component and (component in title or title in component):
                try:
                    return min(1.0, float(weight_pct) / 40.0), component
                except (TypeError, ValueError):
                    break
    event_type = storage.normalize_date_type(deadline.get("type"))
    return IMPORTANCE_BY_TYPE.get(event_type, 0.1), None


def _nearest_assessment(deadlines: list, today) -> dict:
    upcoming = []
    for deadline in deadlines:
        if deadline.get("completed"):
            continue
        if storage.normalize_date_type(deadline.get("type")) not in ASSESSMENT_TYPES:
            continue
        deadline_date = _parse_date(deadline.get("date"))
        if deadline_date is None or deadline_date < today:
            continue
        upcoming.append((deadline_date, deadline))
    if not upcoming:
        return None
    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[0][1]


def _mastery_gap(score) -> float:
    if score is None:
        return NEVER_ASSESSED_GAP
    return max(0.0, 1.0 - score)


def _recency_pressure(last_seen_iso, now: datetime) -> float:
    if not last_seen_iso:
        return 1.0
    try:
        last_seen = datetime.fromisoformat(str(last_seen_iso))
    except ValueError:
        return 1.0
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last_seen).total_seconds() / 86400)
    return min(1.0, days / STALE_HORIZON_DAYS)


def _rank_score(gap: float, urgency: float, importance: float, recency: float) -> float:
    return round(
        WEIGHT_GAP * gap + WEIGHT_URGENCY * urgency + WEIGHT_IMPORTANCE * importance + WEIGHT_RECENCY * recency,
        4,
    )


def _suggested_mode(session_minutes) -> str:
    if session_minutes is not None and session_minutes <= SHORT_SESSION_MINUTES:
        return "flashcards"
    return "mixed"


def _explain(topic: str, status: str, recency: float, deadline: dict, component: str) -> str:
    if status == mastery.NOT_STARTED:
        clause = f"You haven't studied “{topic}” yet"
    elif status == mastery.AT_RISK:
        clause = f"“{topic}” was strong but hasn't been reviewed recently"
    else:
        clause = f"“{topic}” is {status.replace('_', ' ')}"

    if deadline is not None:
        due_clause = f"{deadline.get('title')} is due {deadline.get('date')}"
        if component:
            due_clause += f" and counts toward {component}"
        return f"{clause}, and {due_clause}."
    if recency >= 0.9:
        return f"{clause}, and it's been a while since you last reviewed it."
    return f"{clause}."


def _is_dismissed(dismissed: dict, topic: str, now: datetime) -> bool:
    if topic not in dismissed:
        return False
    dismissed_until = dismissed[topic]
    if dismissed_until is None:
        return True
    return dismissed_until > now


def candidates_for_course(course_id: str, user, now: datetime) -> list:
    """One ranked candidate per syllabus topic that isn't already
    exam-ready or dismissed/deferred. Never raises for missing grading,
    mastery, or deadline data — those are normal, common states here, not
    error conditions."""
    syllabus = storage.read_syllabus(course_id, user)
    if not syllabus:
        return []
    topics = syllabus.get("topics", [])
    if not topics:
        return []

    today = now.date()
    mastery_by_topic = {row["topic"]: row for row in mastery.weak_topics(course_id, user=user)}
    deadlines = reminders.list_all_deadlines(user=user, course_id=course_id)
    nearest = _nearest_assessment(deadlines, today)
    urgency = _urgency(nearest, today)
    importance, component = _importance(nearest, _grading_components(course_id, user))
    dismissed = storage.read_recommendation_dismissals(course_id, user=user)

    candidates = []
    for topic in topics:
        if _is_dismissed(dismissed, topic, now):
            continue
        row = mastery_by_topic.get(topic)
        status = row["status"] if row else mastery.NOT_STARTED
        if status == mastery.EXAM_READY:
            continue  # nothing left to gain from recommending this one

        score = row["score"] if row else None
        last_seen = row["last_seen"] if row else None
        gap = _mastery_gap(score)
        recency = _recency_pressure(last_seen, now)

        candidates.append({
            "course_id": course_id,
            "topic": topic,
            "status": status,
            "mastery_score": score,
            "gap": round(gap, 4),
            "urgency": round(urgency, 4),
            "importance": round(importance, 4),
            "recency": round(recency, 4),
            "rank_score": _rank_score(gap, urgency, importance, recency),
            "nearest_deadline": {"title": nearest["title"], "date": nearest["date"]} if nearest else None,
            "grading_component": component,
            "reason": _explain(topic, status, recency, nearest, component),
        })
    return candidates


def rank_recommendations(user, session_minutes: int = None, limit: int = 3, now: datetime = None, course_ids: list = None) -> list:
    """Deterministic top-`limit` "what to study next" candidates across every
    course (or just `course_ids`, when a caller has already isolated which
    courses read cleanly — e.g. dashboard.py's per-course corruption
    isolation), ranked highest-priority first. `now` is injectable for
    deterministic tests; `session_minutes`, when given, only changes each
    result's suggested study mode (flashcards-only for a short session),
    never the ranking order itself."""
    now = now or datetime.now(timezone.utc)
    all_candidates = []
    for course_id in (course_ids if course_ids is not None else reminders.list_courses(user)):
        all_candidates.extend(candidates_for_course(course_id, user, now))
    all_candidates.sort(key=lambda c: (-c["rank_score"], c["course_id"], c["topic"]))

    top = all_candidates[:limit]
    suggested_mode = _suggested_mode(session_minutes)
    for item in top:
        item["suggested_mode"] = suggested_mode
    return top


def dismiss_recommendation(user, course_id: str, topic: str, defer_until: datetime = None) -> None:
    storage.dismiss_recommendation(course_id, topic, user=user, dismissed_until=defer_until)
