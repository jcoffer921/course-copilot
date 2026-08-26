from datetime import datetime, timezone

import pytest
from rest_framework.test import APIClient

from agent.models import FlashcardProgress, QuizAttempt, StudySession
from agent.services import calendar_events, interactive_study, storage


pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def users(django_user_model):
    return (
        django_user_model.objects.create_user(username="owner"),
        django_user_model.objects.create_user(username="other"),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def seed_course(user):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Data Structures", "grading": [],
        "topics": ["Trees"],
        "dates": [{"date": "2026-09-28", "title": "Midterm", "type": "test_quiz"}],
    }, user)
    storage.write_notes("cs101", "lecture08", {
        "lecture_id": "lecture08", "source": "Trees.pdf", "topics": ["Trees"],
        "chunks": [{"id": "trees-1", "topic": "Trees", "text": "Preorder visits the root before its subtrees."}],
    }, user)
    return next(event["id"] for event in calendar_events.all_events(user, course_ids=["cs101"]) if event["type"] == "test_quiz")


def generated_question():
    return {"lecture_id": "lecture08", "chunk_id": "trees-1", "topic": "Trees",
            "question": "Which traversal visits the root first?",
            "choices": ["Inorder", "Preorder", "Postorder", "Breadth-first"],
            "correct_answer": "Preorder", "explanation": "The source states that preorder visits the root first."}


def test_practice_attempt_redacts_keys_and_is_two_user_scoped(isolated_courses_dir, users):
    owner, other = users
    quiz_id = seed_course(owner)
    session, _ = interactive_study.reserve_practice_attempt(owner, "cs101", quiz_id, "Midterm", 1)
    session.state = {**session.state, "status": "ready", "questions": [{
        **generated_question(), "question_id": "q1", "source_label": "lecture08 · confirmed course notes",
        "user_answer": None, "flagged": False,
    }]}
    session.save(update_fields=["state"])

    response = client_for(owner).get(f"/api/courses/cs101/study/quizzes/attempts/{session.session_id}/")
    assert response.status_code == 200
    assert "correct_answer" not in response.data["questions"][0]
    assert "explanation" not in response.data["questions"][0]

    denied = client_for(other).get(f"/api/courses/cs101/study/quizzes/attempts/{session.session_id}/")
    assert denied.status_code == 404


def test_practice_create_uses_confirmed_exam_topics_and_resumes(isolated_courses_dir, users, monkeypatch):
    owner, _ = users
    quiz_id = seed_course(owner)

    async def fake_generate(course_id, topic=None, **kwargs):
        assert course_id == "cs101"
        assert topic == "Trees"
        assert kwargs["user"] == owner
        return generated_question()

    monkeypatch.setattr(interactive_study.quiz, "generate_assessment_question_async", fake_generate)
    client = client_for(owner)
    url = f"/api/courses/cs101/study/quizzes/{quiz_id}/attempts/"
    created = client.post(url, {"question_count": 1}, format="json")
    assert created.status_code == 201
    assert "correct_answer" not in created.data["questions"][0]
    assert "explanation" not in created.data["questions"][0]

    resumed = client.post(url, {"question_count": 1}, format="json")
    assert resumed.status_code == 201
    assert resumed.data["attempt_id"] == created.data["attempt_id"]
    assert StudySession.objects.filter(user=owner, mode=StudySession.MODE_QUIZ).count() == 1


def test_practice_finalize_uses_server_key_once(isolated_courses_dir, users):
    owner, _ = users
    quiz_id = seed_course(owner)
    session, _ = interactive_study.reserve_practice_attempt(owner, "cs101", quiz_id, "Midterm", 1)
    session.state = {**session.state, "status": "ready", "questions": [{
        **generated_question(), "question_id": "q1", "source_label": "lecture08 · confirmed course notes",
        "user_answer": "Preorder", "flagged": True,
    }]}
    session.save(update_fields=["state"])
    client = client_for(owner)

    submitted = client.post(f"/api/courses/cs101/study/quizzes/attempts/{session.session_id}/finalize/", {}, format="json")
    assert submitted.status_code == 200
    assert submitted.data["summary"] == {"correct": 1, "answered": 1, "total": 1}
    assert submitted.data["questions"][0]["correct_answer"] == "Preorder"
    assert QuizAttempt.objects.filter(user=owner, course_id="cs101").count() == 1

    repeated = client.post(f"/api/courses/cs101/study/quizzes/attempts/{session.session_id}/finalize/", {}, format="json")
    assert repeated.status_code == 409
    assert QuizAttempt.objects.filter(user=owner, course_id="cs101").count() == 1


def test_foreign_practice_mutation_is_non_disclosing_and_unchanged(isolated_courses_dir, users):
    owner, other = users
    quiz_id = seed_course(owner)
    session, _ = interactive_study.reserve_practice_attempt(owner, "cs101", quiz_id, "Midterm", 1)
    session.state = {**session.state, "status": "ready", "questions": [{
        **generated_question(), "question_id": "q1", "source_label": "notes", "user_answer": None, "flagged": False,
    }]}
    session.save(update_fields=["state"])

    denied = client_for(other).patch(
        f"/api/courses/cs101/study/quizzes/attempts/{session.session_id}/",
        {"question_id": "q1", "user_answer": "Preorder"}, format="json",
    )
    assert denied.status_code == 404
    session.refresh_from_db()
    assert session.state["questions"][0]["user_answer"] is None


def test_flashcard_reveal_and_rating_are_redacted_idempotent_and_scoped(isolated_courses_dir, users):
    owner, other = users
    seed_course(owner)
    storage.remember_generated_flashcards("cs101", [{"key": "tree-card", "term": "Preorder", "definition": "Root, left, right."}], user=owner, topic="Trees")
    owner_client = client_for(owner)

    started = owner_client.post("/api/courses/cs101/study/flashcards/due/sessions/", {}, format="json")
    assert started.status_code == 201
    session_id = started.data["session_id"]
    assert "definition" not in started.data["current_card"]

    denied = client_for(other).get(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/")
    assert denied.status_code == 404

    revealed = owner_client.post(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/reveal/", {}, format="json")
    assert revealed.data["current_card"]["definition"] == "Root, left, right."
    hidden_again = owner_client.post(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/reveal/", {}, format="json")
    assert "definition" not in hidden_again.data["current_card"]
    owner_client.post(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/reveal/", {}, format="json")
    rated = owner_client.post(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/rate/", {"card_key": "tree-card", "rating": "good"}, format="json")
    assert rated.status_code == 200
    repeated = owner_client.post(f"/api/courses/cs101/study/flashcards/sessions/{session_id}/rate/", {"card_key": "tree-card", "rating": "good"}, format="json")
    assert repeated.status_code == 200
    assert FlashcardProgress.objects.get(user=owner, card_key="tree-card").review_count == 1


def test_generic_session_does_not_resume_specialized_state(isolated_courses_dir, users):
    from agent.services import study_sessions

    owner, _ = users
    seed_course(owner)
    storage.remember_generated_flashcards("cs101", [{"key": "tree-card", "term": "Preorder", "definition": "Root first."}], user=owner, topic="Trees")
    specialized = interactive_study.start_flashcard_session(owner, "cs101", "due")
    generic = study_sessions.start_session(owner, "cs101", mode="flashcards")
    assert generic["session_id"] != specialized["session_id"]


def test_interactive_pages_require_login_and_owned_resources(isolated_courses_dir, users):
    from django.test import Client

    owner, other = users
    quiz_id = seed_course(owner)
    session, _ = interactive_study.reserve_practice_attempt(owner, "cs101", quiz_id, "Midterm", 1)
    anonymous = APIClient()
    path = f"/courses/cs101/study/quizzes/{quiz_id}/attempts/{session.session_id}/"
    assert anonymous.get(path).status_code == 302
    other_browser = Client(); other_browser.force_login(other)
    owner_browser = Client(); owner_browser.force_login(owner)
    assert other_browser.get(path).status_code == 404
    assert owner_browser.get(path).status_code == 200
    assert owner_browser.get("/courses/cs101/study/flashcards/due/").status_code == 200
