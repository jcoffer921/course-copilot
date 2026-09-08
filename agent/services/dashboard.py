"""
Cross-course summary for the Dashboard tab: global upcoming deadlines plus,
per course, everything the "Your courses" grid needs. Pure composition of
existing reads — no new storage format, nothing written.
"""

from . import calendar_events, mastery, recommendations, reminders, storage, streak

TODAY_PLAN_LIMIT = 3
RECOMMENDATION_TASK_EFFORT_MINUTES = 30


def _merge_topics(syllabus_topics: list, weak_topics: list, note_topics: list = None) -> list:
    """Every topic from the syllabus, in syllabus order, tagged with its
    mastery status, followed by any scored topic that isn't in the syllabus
    at all. A topic mastery.weak_topics() hasn't scored yet (never quizzed
    or flashcard-reviewed) gets score=None, status="not_started" — the same
    sentinel mastery.py itself would use for a topic with zero activity —
    rather than being omitted. The Progress tab's "Mastery by topic" list
    needs every syllabus topic represented, not just the ones with history.

    Off-syllabus topics are real: chunk_notes.py's chunking prompt
    explicitly allows a chunk to be tagged with its own topic name when it
    doesn't cleanly match a syllabus topic, and that topic still gets
    quizzed and scored like any other — it must still show up here rather
    than silently vanishing from "Mastery by topic"."""
    scores_by_topic = {t["topic"]: t for t in weak_topics}
    note_topics = note_topics or []
    syllabus_topic_set = set(syllabus_topics)
    base_topic_set = set(syllabus_topics)
    not_started_reason = "Not started yet."
    merged = [
        {
            "topic": topic,
            "score": scores_by_topic[topic]["score"] if topic in scores_by_topic else None,
            "status": scores_by_topic[topic]["status"] if topic in scores_by_topic else mastery.NOT_STARTED,
            "reason": scores_by_topic[topic].get("reason", "") if topic in scores_by_topic else not_started_reason,
        }
        for topic in syllabus_topics
    ]
    for topic in note_topics:
        if topic not in base_topic_set:
            scored_topic = scores_by_topic.get(topic)
            merged.append(
                {
                    "topic": topic,
                    "score": scored_topic["score"] if scored_topic else None,
                    "status": scored_topic["status"] if scored_topic else mastery.NOT_STARTED,
                    "reason": scored_topic.get("reason", "") if scored_topic else not_started_reason,
                }
            )
            base_topic_set.add(topic)

    merged += [
        {"topic": t["topic"], "score": t["score"], "status": t["status"], "reason": t.get("reason", "")}
        for t in weak_topics
        if t["topic"] not in base_topic_set
    ]
    return merged


def _note_topics(course_id: str, user) -> list:
    seen = set()
    topics = []
    for lecture in storage.read_notes(course_id, user):
        for chunk in lecture.get("chunks", []):
            topic = str(chunk.get("topic") or "").strip()
            if topic and topic not in seen:
                seen.add(topic)
                topics.append(topic)
    return topics


def _quiz_accuracy_counts(course_id: str, user=None) -> dict:
    attempts = storage.read_quiz_history(course_id, user=user).get("attempts", [])
    return {
        "quiz_attempts_count": len(attempts),
        "quiz_correct_count": len([a for a in attempts if a.get("correct")]),
    }


def _mastery_pct(syllabus_topics: list, weak_topics: list) -> int:
    """Whole-course mastery, for the "Your courses" card's single summary
    bar: the average of each SYLLABUS topic's score (0 for a never-assessed
    one — a topic the syllabus lists but nothing has covered yet is a real
    gap, not a value to skip out of the average), or None before there's
    even a syllabus topic to average over. Off-syllabus topics (see
    _merge_topics) are intentionally excluded — this is "how much of the
    listed course is mastered", not "how well have quizzes gone overall"."""
    if not syllabus_topics:
        return None
    scores_by_topic = {t["topic"]: t["score"] for t in weak_topics}
    if not any(topic in scores_by_topic for topic in syllabus_topics):
        return None
    total = sum(scores_by_topic.get(topic) or 0.0 for topic in syllabus_topics)
    return round((total / len(syllabus_topics)) * 100)


def _course_summary(course_id: str, user=None) -> dict:
    syllabus = storage.read_syllabus(course_id, user)
    weak_topics = mastery.weak_topics(course_id, user=user)
    quiz_counts = _quiz_accuracy_counts(course_id, user=user)
    upcoming = reminders.upcoming_deadlines(user, within_days=None, course_ids=[course_id])
    syllabus_topics = syllabus.get("topics", [])
    note_topics = _note_topics(course_id, user)
    syllabus_topic_set = set(syllabus_topics)

    return {
        "course_id": course_id,
        "course_name": syllabus.get("course_name", course_id),
        "course_color": calendar_events.course_color(course_id),
        "notes_count": len(storage.read_notes(course_id, user)),
        "topics_count": len(syllabus_topics),
        **quiz_counts,
        # Only counts syllabus topics that have been quizzed — an
        # off-syllabus scored topic (see _merge_topics) must not inflate
        # this past topics_count, since "X of Y topics quizzed" and the
        # syllabus-covered percentage derived from it would otherwise be
        # able to exceed 100%.
        "quizzed_count": len([t for t in weak_topics if t["topic"] in syllabus_topic_set]),
        "next_deadline": upcoming[0] if upcoming else None,
        "grading": syllabus.get("grading", []),
        "weak_topics": weak_topics,
        "topics": _merge_topics(syllabus_topics, weak_topics, note_topics),
        "mastery_pct": _mastery_pct(syllabus_topics, weak_topics),
    }


def _next_exam(deadlines: list) -> dict:
    return next((d for d in deadlines if d.get("type") == "test_quiz"), None)


def _next_non_exam_deadline(deadlines: list) -> dict:
    """Keep the deadline and exam summary cards meaningfully distinct."""
    return next((d for d in deadlines if d.get("type") != "test_quiz"), None)


def _with_course_display(event: dict | None, courses: dict) -> dict | None:
    if not event:
        return None
    decorated = dict(event)
    course = courses.get(event.get("course_id"), {})
    if course and not course.get("error"):
        decorated["course_name"] = course.get("course_name")
        decorated["course_color"] = course.get("course_color")
    return decorated


def _today_plan(user, deadlines: list, good_course_ids: list, limit: int = TODAY_PLAN_LIMIT, ranked=None) -> list:
    """Read-only composition, never itself persisted: upcoming deadlines
    with a real effort estimate (only ever present on a manually-added
    deadline — never fabricated for a syllabus date that doesn't carry
    one), plus top study recommendations for courses not already covered,
    most-urgent first. "Marking done" always acts on the underlying record
    directly (the deadline's own completion via the existing deadlines API,
    or dismissing the recommendation via the existing recommendations API)
    — nothing here is a second source of truth for either."""
    items = []
    for d in deadlines:
        if d.get("completed") or not d.get("estimated_effort_minutes"):
            continue
        items.append({
            "kind": "deadline",
            "id": d.get("id"),
            "course_id": d.get("course_id"),
            "title": d.get("title"),
            "detail": str(d.get("type") or "").replace("_", " ").title(),
            "effort_minutes": d["estimated_effort_minutes"],
            "date": d.get("date"),
        })

    covered_courses = {i["course_id"] for i in items}
    if len(items) < limit:
        for rec in ranked if ranked is not None else recommendations.rank_recommendations(user, limit=limit, course_ids=good_course_ids):
            if rec["course_id"] in covered_courses:
                continue
            items.append({
                "kind": "recommendation",
                "course_id": rec["course_id"],
                "topic": rec["topic"],
                "title": f"Review {rec['topic']}",
                # Short on purpose, to match a deadline item's one-word
                # detail line — the full "reason" sentence has its own
                # home on the "Recommended by Cora" card.
                "detail": rec["status"].replace("_", " ").title(),
                "effort_minutes": RECOMMENDATION_TASK_EFFORT_MINUTES,
                "date": None,
            })
            covered_courses.add(rec["course_id"])
            if len(items) >= limit:
                break

    items.sort(key=lambda i: i["date"] or "9999-99-99")
    return items[:limit]


def build_dashboard(user=None) -> dict:
    """Never raises — a corrupt course's data is isolated to
    {"error": "..."} in its own slot rather than failing every other
    course's dashboard data along with it."""
    courses = {}
    good_course_ids = []
    for course_id in reminders.list_courses(user):
        try:
            courses[course_id] = _course_summary(course_id, user=user)
            good_course_ids.append(course_id)
        except (storage.SyllabusStorageError, storage.QuizStorageError) as e:
            courses[course_id] = {"error": str(e)}

    # Restricted to the courses that read cleanly above — passing no
    # course_ids would make upcoming_deadlines() re-scan every course (via
    # its own list_courses() call) including any corrupt one, raising past
    # the per-course isolation this function promises.
    deadlines = reminders.upcoming_deadlines(
        user, within_days=14, course_ids=good_course_ids, include_general=True,
    )

    decorated_deadlines = [_with_course_display(deadline, courses) for deadline in deadlines]
    ranked = recommendations.rank_recommendations(user, limit=TODAY_PLAN_LIMIT, course_ids=good_course_ids)

    return {
        "deadlines": decorated_deadlines,
        "next_deadline": _with_course_display(_next_non_exam_deadline(deadlines), courses),
        "next_exam": _with_course_display(_next_exam(deadlines), courses),
        "streak": streak.current_streak(user=user),
        "streak_week": streak.week_activity(user=user),
        "today_plan": _today_plan(user, deadlines, good_course_ids, ranked=ranked),
        "courses": courses,
        "drafts": reminders.list_draft_courses(user),
        "recommendation": ranked[0] if ranked else None,
        "warnings": [
            {"course_id": course_id, "detail": summary["error"]}
            for course_id, summary in courses.items()
            if summary.get("error")
        ],
    }
