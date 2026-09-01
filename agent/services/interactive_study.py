"""Resumable, owner-scoped practice attempts and flashcard sessions.

Answer keys and unrevealed flashcard definitions live only in StudySession.state.
The serializers in this module deliberately return redacted active-session data.
"""

from django.db import transaction
from django.utils import timezone

from . import exams, mastery, quiz, storage
from .study_sessions import StudySessionNotFoundError


class InteractiveStudyConflictError(Exception):
    pass


class InteractiveStudyValidationError(Exception):
    pass


def _owned(user, course_id, session_id, kind):
    from agent.models import StudySession

    session = StudySession.objects.filter(user=user, course_id=course_id, session_id=session_id).first()
    if session is None or session.state.get("kind") != kind:
        raise StudySessionNotFoundError("no such study session")
    return session


def _course_name(user, course_id):
    data = storage.read_course_metadata(course_id, user) or storage.read_syllabus(course_id, user) or {}
    return data.get("course_name") or course_id.upper()


def _practice_payload(session):
    state = session.state
    finalized = bool(state.get("finalized"))
    questions = []
    for item in state.get("questions", []):
        public = {
            "question_id": item["question_id"], "topic": item["topic"],
            "question": item["question"], "choices": item["choices"],
            "source_label": item.get("source_label", "Confirmed course material"),
            "user_answer": item.get("user_answer"), "flagged": bool(item.get("flagged")),
        }
        if finalized:
            public.update({
                "correct_answer": item["correct_answer"],
                "correct": item.get("correct"),
                "explanation": item.get("explanation", ""),
            })
        questions.append(public)
    answered = sum(1 for item in questions if item.get("user_answer") is not None)
    payload = {
        "attempt_id": str(session.session_id), "course_id": session.course_id,
        "course_name": state.get("course_name"), "quiz_id": state.get("quiz_id"),
        "title": state.get("title", "Practice exam"), "status": state.get("status", "ready"),
        "position": min(state.get("position", 0), max(len(questions) - 1, 0)),
        "question_count": len(questions), "answered_count": answered,
        "started_at": session.started_at.isoformat(), "duration_minutes": session.duration_minutes,
        "finalized": finalized, "questions": questions,
    }
    if finalized:
        payload["summary"] = state.get("summary", {})
    return payload


def reserve_practice_attempt(user, course_id, quiz_id, title, question_count):
    from agent.models import StudyActivity, StudySession

    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        sessions = StudySession.objects.filter(
            user=user, course_id=course_id, mode=StudySession.MODE_QUIZ,
            status=StudySession.STATUS_IN_PROGRESS,
        ).order_by("-started_at")
        existing = next((row for row in sessions if row.state.get("kind") == "practice_attempt" and row.state.get("quiz_id") == quiz_id), None)
        if existing:
            if existing.state.get("status") == "failed":
                existing.state = {**existing.state, "status": "preparing", "questions": [], "position": 0}
                existing.save(update_fields=["state"])
                return existing, True
            return existing, False
        session = StudySession.objects.create(
            user=user, course_id=course_id, mode=StudySession.MODE_QUIZ,
            duration_minutes=max(5, question_count * 2),
            state={"kind": "practice_attempt", "status": "preparing", "quiz_id": quiz_id,
                   "title": title, "course_name": _course_name(user, course_id), "position": 0,
                   "questions": [], "finalized": False},
        )
        StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_SESSION_STARTED,
                                     payload={"course_id": course_id, "mode": "quiz", "quiz_id": quiz_id}, position=0)
        return session, True


async def create_practice_attempt(user, course_id, quiz_id, question_count=10, topics=None):
    from asgiref.sync import sync_to_async

    if quiz_id == "course-practice":
        if not await sync_to_async(storage.course_or_draft_exists)(course_id, user):
            raise storage.CourseNotFoundError(course_id)
        syllabus = await sync_to_async(storage.read_syllabus)(course_id, user)
        confirmed_topics = await sync_to_async(quiz.available_topics)(course_id, user)
        title = "Course Practice Quiz"
        empty_message = "Upload and process notes for at least one topic before starting a practice quiz."
    else:
        event = await sync_to_async(exams.find_exam_event)(user, course_id, quiz_id)
        plan = await sync_to_async(exams.get_or_create_plan)(user, course_id, quiz_id)
        quiz_topics = set(await sync_to_async(quiz.available_topics)(course_id, user))
        confirmed_topics = [topic for topic in (plan.get("included_topics") or []) if topic in quiz_topics]
        title = event["title"]
        empty_message = "Upload processed notes for at least one included exam topic first."
    if not confirmed_topics:
        raise InteractiveStudyValidationError(empty_message)
    selected_topics = list(dict.fromkeys(topics or confirmed_topics))
    if any(topic not in confirmed_topics for topic in selected_topics):
        raise InteractiveStudyValidationError("The selected topic does not have processed notes available for quiz questions.")
    session, created = await sync_to_async(reserve_practice_attempt)(
        user, course_id, quiz_id, title, question_count,
    )
    if not created:
        return await sync_to_async(_practice_payload)(session)

    questions = []
    previous = []
    try:
        for index in range(question_count):
            generated = await quiz.generate_assessment_question_async(
                course_id, topic=selected_topics[index % len(selected_topics)], question_type="multiple_choice",
                previous_questions=previous, user=user,
            )
            previous.append(generated["question"])
            questions.append({
                "question_id": f"q{index + 1}", "topic": generated["topic"],
                "lecture_id": generated["lecture_id"], "chunk_id": generated["chunk_id"],
                "question": generated["question"], "choices": generated["choices"],
                "correct_answer": generated["correct_answer"], "explanation": generated["explanation"],
                "source_label": f"{generated['lecture_id']} · confirmed course notes",
                "user_answer": None, "flagged": False,
            })
    except quiz.NoChunksAvailableError as exc:
        def mark_failed():
            row = _owned(user, course_id, session.session_id, "practice_attempt")
            row.state = {**row.state, "status": "failed"}
            row.save(update_fields=["state"])
        await sync_to_async(mark_failed)()
        raise InteractiveStudyValidationError(
            "The selected topic does not have processed notes available for quiz questions."
        ) from exc
    except Exception:
        def mark_failed():
            row = _owned(user, course_id, session.session_id, "practice_attempt")
            row.state = {**row.state, "status": "failed"}
            row.save(update_fields=["state"])
        await sync_to_async(mark_failed)()
        raise

    def publish():
        row = _owned(user, course_id, session.session_id, "practice_attempt")
        row.state = {**row.state, "status": "ready", "questions": questions}
        row.save(update_fields=["state"])
        return _practice_payload(row)
    return await sync_to_async(publish)()


def practice_detail(user, course_id, attempt_id):
    return _practice_payload(_owned(user, course_id, attempt_id, "practice_attempt"))


def update_practice(user, course_id, attempt_id, question_id, user_answer=None, flagged=None, position=None):
    from agent.models import StudySession

    with transaction.atomic():
        session = StudySession.objects.select_for_update().filter(
            user=user, course_id=course_id, session_id=attempt_id,
        ).first()
        if session is None or session.state.get("kind") != "practice_attempt":
            raise StudySessionNotFoundError("no such study session")
        state = dict(session.state)
        if state.get("finalized"):
            raise InteractiveStudyConflictError("This practice attempt has already been submitted.")
        questions = [dict(item) for item in state.get("questions", [])]
        target = next((item for item in questions if item["question_id"] == question_id), None)
        if target is None:
            raise InteractiveStudyValidationError("Unknown question.")
        if user_answer is not None:
            if user_answer not in target["choices"]:
                raise InteractiveStudyValidationError("Answer must be one of this question's choices.")
            target["user_answer"] = user_answer
        if flagged is not None:
            target["flagged"] = bool(flagged)
        if position is not None:
            if position < 0 or position >= len(questions):
                raise InteractiveStudyValidationError("Position is outside this attempt.")
            state["position"] = position
        state["questions"] = questions
        session.state = state
        session.save(update_fields=["state"])
        return _practice_payload(session)


def finalize_practice(user, course_id, attempt_id):
    from agent.models import StudyActivity, StudySession

    with transaction.atomic():
        session = StudySession.objects.select_for_update().filter(
            user=user, course_id=course_id, session_id=attempt_id,
        ).first()
        if session is None or session.state.get("kind") != "practice_attempt":
            raise StudySessionNotFoundError("no such study session")
        state = dict(session.state)
        if state.get("finalized"):
            raise InteractiveStudyConflictError("This practice attempt has already been submitted.")
        questions = [dict(item) for item in state.get("questions", [])]
        correct_count = 0
        next_position = session.activities.count()
        for item in questions:
            answer = item.get("user_answer")
            item["correct"] = bool(answer is not None and answer.strip().casefold() == item["correct_answer"].strip().casefold())
            correct_count += int(item["correct"])
            if answer is not None:
                quiz.record_attempt(session.course_id, item["lecture_id"], item["chunk_id"], item["topic"],
                                    item["question"], item["correct_answer"], answer, user=user)
                StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_QUIZ_ANSWERED,
                                             payload={"question_id": item["question_id"], "correct": item["correct"]},
                                             position=next_position)
                next_position += 1
        summary = {"correct": correct_count, "answered": sum(item.get("user_answer") is not None for item in questions),
                   "total": len(questions)}
        state.update({"questions": questions, "finalized": True, "status": "completed", "summary": summary})
        session.state = state
        session.status = StudySession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=["state", "status", "completed_at"])
        StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_SESSION_COMPLETED,
                                     payload=summary, position=next_position)
        return _practice_payload(session)


def _flashcard_payload(session):
    from agent.models import FlashcardProgress

    state = session.state
    keys = state.get("keys", [])
    position = min(state.get("position", 0), len(keys))
    records = {record.card_key: record for record in FlashcardProgress.objects.filter(
        user=session.user, course_id=session.course_id, card_key__in=keys,
    )}
    current = None
    if position < len(keys):
        record = records.get(keys[position])
        if record:
            current = {"key": record.card_key, "term": record.term, "topic": record.topic,
                       "source_label": "Source unavailable for this saved card"}
            if state.get("revealed"):
                current["definition"] = record.definition
    reviewed = state.get("reviewed", {})
    focus = {}
    for key in keys:
        record = records.get(key)
        topic = (record.topic if record else "") or "Other course material"
        item = focus.setdefault(topic, {"topic": topic, "cards": 0, "reviewed": 0})
        item["cards"] += 1
        item["reviewed"] += int(key in reviewed)
    return {"session_id": str(session.session_id), "course_id": session.course_id,
            "course_name": state.get("course_name"), "deck_id": state.get("deck_id"),
            "title": state.get("title"), "status": session.status, "position": position,
            "card_count": len(keys), "reviewed_count": len(reviewed), "revealed": bool(state.get("revealed")),
            "current_card": current, "ratings": reviewed, "deck_focus": list(focus.values())}


def start_flashcard_session(user, course_id, deck_id="due"):
    from agent.models import StudyActivity, StudySession

    if not storage.course_or_draft_exists(course_id, user):
        raise storage.CourseNotFoundError("Course not found.")
    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        sessions = StudySession.objects.filter(user=user, course_id=course_id, mode=StudySession.MODE_FLASHCARDS,
                                               status=StudySession.STATUS_IN_PROGRESS).order_by("-started_at")
        existing = next((row for row in sessions if row.state.get("kind") == "flashcard_deck" and row.state.get("deck_id") == deck_id), None)
        if existing:
            return _flashcard_payload(existing)
        due = storage.due_flashcards(course_id, user=user, limit=100)
        keys = [card["key"] for card in due]
        due_topics = list(dict.fromkeys(card.get("topic") for card in due if card.get("topic")))
        title = due_topics[0] if len(due_topics) == 1 else "Mixed course review"
        session = StudySession.objects.create(user=user, course_id=course_id, mode=StudySession.MODE_FLASHCARDS,
            state={"kind": "flashcard_deck", "deck_id": deck_id, "course_name": _course_name(user, course_id),
                   "title": title, "keys": keys, "position": 0, "revealed": False, "reviewed": {}})
        StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_SESSION_STARTED,
                                     payload={"course_id": course_id, "mode": "flashcards", "deck_id": deck_id}, position=0)
        return _flashcard_payload(session)


def flashcard_detail(user, course_id, session_id):
    return _flashcard_payload(_owned(user, course_id, session_id, "flashcard_deck"))


def reveal_flashcard(user, course_id, session_id):
    session = _owned(user, course_id, session_id, "flashcard_deck")
    if session.status != session.STATUS_IN_PROGRESS:
        raise InteractiveStudyConflictError("This flashcard session has ended.")
    session.state = {**session.state, "revealed": not bool(session.state.get("revealed"))}
    session.save(update_fields=["state"])
    return _flashcard_payload(session)


def navigate_flashcard(user, course_id, session_id, position):
    session = _owned(user, course_id, session_id, "flashcard_deck")
    keys = session.state.get("keys", [])
    if position < 0 or position >= len(keys):
        raise InteractiveStudyValidationError("Position is outside this deck.")
    session.state = {**session.state, "position": position, "revealed": False}
    session.save(update_fields=["state"])
    return _flashcard_payload(session)


def rate_flashcard(user, course_id, session_id, card_key, rating):
    from agent.models import StudyActivity, StudySession

    with transaction.atomic():
        session = StudySession.objects.select_for_update().filter(user=user, course_id=course_id, session_id=session_id).first()
        if session is None or session.state.get("kind") != "flashcard_deck":
            raise StudySessionNotFoundError("no such study session")
        if session.status != StudySession.STATUS_IN_PROGRESS:
            raise InteractiveStudyConflictError("This flashcard session has ended.")
        state = dict(session.state)
        reviewed = dict(state.get("reviewed", {}))
        if card_key in reviewed:
            return _flashcard_payload(session)
        keys = state.get("keys", [])
        position = state.get("position", 0)
        if not state.get("revealed") or position >= len(keys) or keys[position] != card_key:
            raise InteractiveStudyConflictError("Reveal the current card before rating it.")
        storage.review_flashcard(course_id, card_key, rating, user=user)
        mastery.rebuild_scores(course_id, user=user)
        reviewed[card_key] = rating
        state.update({"reviewed": reviewed, "position": min(position + 1, len(keys)), "revealed": False})
        session.state = state
        session.save(update_fields=["state"])
        StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_FLASHCARD_REVIEWED,
                                     payload={"card_key": card_key, "rating": rating}, position=session.activities.count())
        return _flashcard_payload(session)


def end_flashcard_session(user, course_id, session_id):
    from agent.models import StudyActivity, StudySession

    with transaction.atomic():
        session = StudySession.objects.select_for_update().filter(user=user, course_id=course_id, session_id=session_id).first()
        if session is None or session.state.get("kind") != "flashcard_deck":
            raise StudySessionNotFoundError("no such study session")
        if session.status == StudySession.STATUS_COMPLETED:
            return _flashcard_payload(session)
        session.status = StudySession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at"])
        StudyActivity.objects.create(session=session, kind=StudyActivity.KIND_SESSION_COMPLETED,
                                     payload={"reviewed": len(session.state.get("reviewed", {}))},
                                     position=session.activities.count())
        return _flashcard_payload(session)
