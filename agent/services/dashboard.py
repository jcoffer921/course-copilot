"""
Cross-course summary for the Dashboard tab: global upcoming deadlines plus,
per course, everything the "Your courses" grid needs. Pure composition of
existing reads — no new storage format, nothing written.
"""

from . import mastery, reminders, storage, streak


def _merge_topics(syllabus_topics: list, weak_topics: list) -> list:
    """Every topic from the syllabus, in syllabus order, tagged with its
    mastery status. A topic mastery.weak_topics() hasn't scored yet (never
    quizzed) gets score=None, status="unassessed" rather than being omitted —
    the Progress tab's "Mastery by topic" list needs every syllabus topic
    represented, not just the ones with quiz history."""
    scores_by_topic = {t["topic"]: t for t in weak_topics}
    return [
        {
            "topic": topic,
            "score": scores_by_topic[topic]["score"] if topic in scores_by_topic else None,
            "status": scores_by_topic[topic]["status"] if topic in scores_by_topic else "unassessed",
        }
        for topic in syllabus_topics
    ]


def _course_summary(course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id)
    weak_topics = mastery.weak_topics(course_id)
    upcoming = reminders.upcoming_deadlines(within_days=None, course_ids=[course_id])
    syllabus_topics = syllabus.get("topics", [])

    return {
        "course_name": syllabus.get("course_name", course_id),
        "notes_count": len(storage.read_notes(course_id)),
        "topics_count": len(syllabus_topics),
        "quizzed_count": len(weak_topics),
        "next_deadline": upcoming[0] if upcoming else None,
        "grading": syllabus.get("grading", []),
        "weak_topics": weak_topics,
        "topics": _merge_topics(syllabus_topics, weak_topics),
    }


def build_dashboard() -> dict:
    """Never raises — a corrupt course's data is isolated to
    {"error": "..."} in its own slot rather than failing every other
    course's dashboard data along with it."""
    courses = {}
    good_course_ids = []
    for course_id in reminders.list_courses():
        try:
            courses[course_id] = _course_summary(course_id)
            good_course_ids.append(course_id)
        except (storage.SyllabusStorageError, storage.QuizStorageError) as e:
            courses[course_id] = {"error": str(e)}

    return {
        # Restricted to the courses that read cleanly above — passing no
        # course_ids would make upcoming_deadlines() re-scan every course
        # (via its own list_courses() call) including any corrupt one,
        # raising past the per-course isolation this function promises.
        "deadlines": reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids),
        "streak": streak.current_streak(),
        "courses": courses,
    }
