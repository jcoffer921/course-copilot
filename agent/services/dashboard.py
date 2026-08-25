"""
Cross-course summary for the Dashboard tab: global upcoming deadlines plus,
per course, everything the "Your courses" grid needs. Pure composition of
existing reads — no new storage format, nothing written.
"""

from . import mastery, reminders, storage, streak


def _merge_topics(syllabus_topics: list, weak_topics: list, note_topics: list = None) -> list:
    """Every topic from the syllabus, in syllabus order, tagged with its
    mastery status, followed by any scored topic that isn't in the syllabus
    at all. A topic mastery.weak_topics() hasn't scored yet (never quizzed)
    gets score=None, status="unassessed" rather than being omitted — the
    Progress tab's "Mastery by topic" list needs every syllabus topic
    represented, not just the ones with quiz history.

    Off-syllabus topics are real: chunk_notes.py's chunking prompt
    explicitly allows a chunk to be tagged with its own topic name when it
    doesn't cleanly match a syllabus topic, and that topic still gets
    quizzed and scored like any other — it must still show up here rather
    than silently vanishing from "Mastery by topic"."""
    scores_by_topic = {t["topic"]: t for t in weak_topics}
    note_topics = note_topics or []
    syllabus_topic_set = set(syllabus_topics)
    base_topic_set = set(syllabus_topics)
    merged = [
        {
            "topic": topic,
            "score": scores_by_topic[topic]["score"] if topic in scores_by_topic else None,
            "status": scores_by_topic[topic]["status"] if topic in scores_by_topic else "unassessed",
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
                    "status": scored_topic["status"] if scored_topic else "unassessed",
                }
            )
            base_topic_set.add(topic)

    merged += [
        {"topic": t["topic"], "score": t["score"], "status": t["status"]}
        for t in weak_topics
        if t["topic"] not in base_topic_set
    ]
    return merged


def _note_topics(course_id: str) -> list:
    seen = set()
    topics = []
    for lecture in storage.read_notes(course_id):
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


def _annotate_synced(deadlines: list, user=None) -> list:
    """Marks each deadline with whether it's already been pushed to Google
    Calendar, by cross-referencing that course's calendar_sync.json (read
    once per distinct course_id present in the list, not once per
    deadline).

    A course with a corrupt calendar_sync.json degrades that course's
    deadlines to synced=False rather than raising — same "isolate the
    corrupt course, don't fail everything" spirit as build_dashboard()'s
    per-course try/except, extended to this call outside that loop."""
    synced_by_course = {}
    annotated = []
    for d in deadlines:
        course_id = d["course_id"]
        if course_id not in synced_by_course:
            try:
                synced_by_course[course_id] = storage.read_calendar_sync(course_id, user=user)
            except storage.CalendarSyncStorageError:
                synced_by_course[course_id] = None
        course_synced = synced_by_course[course_id]
        is_synced = course_synced is not None and any(
            r["date"] == d["date"] and r["title"] == d["title"]
            for r in course_synced
        )
        annotated.append(dict(d, synced=is_synced))
    return annotated


def _course_summary(course_id: str, user=None) -> dict:
    syllabus = storage.read_syllabus(course_id)
    weak_topics = mastery.weak_topics(course_id, user=user)
    quiz_counts = _quiz_accuracy_counts(course_id, user=user)
    upcoming = reminders.upcoming_deadlines(within_days=None, course_ids=[course_id])
    syllabus_topics = syllabus.get("topics", [])
    note_topics = _note_topics(course_id)
    syllabus_topic_set = set(syllabus_topics)

    return {
        "course_name": syllabus.get("course_name", course_id),
        "notes_count": len(storage.read_notes(course_id)),
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
    }


def build_dashboard(user=None) -> dict:
    """Never raises — a corrupt course's data is isolated to
    {"error": "..."} in its own slot rather than failing every other
    course's dashboard data along with it."""
    courses = {}
    good_course_ids = []
    for course_id in reminders.list_courses():
        try:
            courses[course_id] = _course_summary(course_id, user=user)
            good_course_ids.append(course_id)
        except (storage.SyllabusStorageError, storage.QuizStorageError) as e:
            courses[course_id] = {"error": str(e)}

    return {
        # Restricted to the courses that read cleanly above — passing no
        # course_ids would make upcoming_deadlines() re-scan every course
        # (via its own list_courses() call) including any corrupt one,
        # raising past the per-course isolation this function promises.
        "deadlines": _annotate_synced(
            reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids),
            user=user,
        ),
        "streak": streak.current_streak(user=user),
        "courses": courses,
        "drafts": reminders.list_draft_courses(),
    }
