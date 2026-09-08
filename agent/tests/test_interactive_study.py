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


def test_course_practice_create_uses_selected_confirmed_topic_without_an_exam(isolated_courses_dir, users, monkeypatch):
    owner, other = users
    seed_course(owner)

    async def fake_generate(course_id, topic=None, **kwargs):
        assert course_id == "cs101"
        assert topic == "Trees"
        assert kwargs["user"] == owner
        return generated_question()

    monkeypatch.setattr(interactive_study.quiz, "generate_assessment_question_async", fake_generate)
    url = "/api/courses/cs101/study/quizzes/course-practice/attempts/"
    created = client_for(owner).post(url, {"question_count": 1, "topics": ["Trees"]}, format="json")

    assert created.status_code == 201
    assert created.data["quiz_id"] == "course-practice"
    assert created.data["title"] == "Course Practice Quiz"
    assert created.data["question_count"] == 1
    assert "correct_answer" not in created.data["questions"][0]
    assert client_for(other).post(url, {"question_count": 1}, format="json").status_code == 404


def test_course_practice_rejects_unconfirmed_topic(isolated_courses_dir, users):
    owner, _ = users
    seed_course(owner)

    response = client_for(owner).post(
        "/api/courses/cs101/study/quizzes/course-practice/attempts/",
        {"question_count": 1, "topics": ["Not in the syllabus"]}, format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "The selected topic does not have processed notes available for quiz questions."


@pytest.mark.parametrize("question_count", [0, 21])
def test_course_practice_validates_question_count_at_api_boundary(isolated_courses_dir, users, question_count):
    owner, _ = users
    seed_course(owner)

    response = client_for(owner).post(
        "/api/courses/cs101/study/quizzes/course-practice/attempts/",
        {"question_count": question_count}, format="json",
    )

    assert response.status_code == 400
    assert "question_count" in response.data


def test_course_practice_requires_quiz_ready_material(isolated_courses_dir, users):
    owner, _ = users
    storage.write_syllabus("empty101", {
        "course_id": "empty101", "course_name": "Empty Course", "dates": [], "grading": [], "topics": ["Topic"],
    }, owner)

    response = client_for(owner).post(
        "/api/courses/empty101/study/quizzes/course-practice/attempts/",
        {"question_count": 5}, format="json",
    )

    assert response.status_code == 400
    assert "Upload and process notes" in response.data["detail"]


def test_course_practice_skips_syllabus_topics_without_note_chunks(isolated_courses_dir, users, monkeypatch):
    owner, _ = users
    seed_course(owner)
    syllabus = storage.read_syllabus("cs101", owner)
    syllabus["topics"].append("More transformations and Basic Animation")
    storage.write_syllabus("cs101", syllabus, owner, overwrite=True)
    generated_topics = []

    async def fake_generate(course_id, topic=None, **kwargs):
        generated_topics.append(topic)
        return generated_question()

    monkeypatch.setattr(interactive_study.quiz, "generate_assessment_question_async", fake_generate)
    response = client_for(owner).post(
        "/api/courses/cs101/study/quizzes/course-practice/attempts/",
        {"question_count": 2}, format="json",
    )

    assert response.status_code == 201
    assert generated_topics == ["Trees", "Trees"]


def test_syllabus_response_lists_only_quiz_capable_topics(isolated_courses_dir, users):
    owner, _ = users
    seed_course(owner)
    syllabus = storage.read_syllabus("cs101", owner)
    syllabus["topics"].append("Topic without notes")
    storage.write_syllabus("cs101", syllabus, owner, overwrite=True)

    response = client_for(owner).get("/api/courses/cs101/syllabus/")

    assert response.status_code == 200
    assert response.data["topics"] == ["Trees", "Topic without notes"]
    assert response.data["quiz_topics"] == ["Trees"]


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
    scores = storage.read_mastery_scores("cs101", owner)
    assert next(item for item in scores["scores"] if item["topic"] == "Trees")["attempts"] == 1

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
    practice_response = owner_browser.get(path)
    assert practice_response.status_code == 200
    practice_html = practice_response.content.decode()
    for hook in (
        'id="pa-question-meta"', 'id="pa-timer"', 'id="pa-grid"',
        'id="pa-choices"', 'id="pa-flag"', 'id="pa-submit"',
        'id="pa-ring"', 'id="pa-answered"', 'id="pa-cora"',
        'id="pa-save-status"',
    ):
        assert hook in practice_html
    assert 'src="/static/agent/js/practice_attempt.js?v=interactive-20260831-4"' in practice_html
    sidebar = practice_html[practice_html.index('<aside id="app-sidebar"'):practice_html.index("</aside>")]
    assert 'href="/study/" class="app-nav-link active"' in sidebar
    assert 'href="/dashboard/" class="app-nav-link active"' not in sidebar
    assert "Grounded in your materials" in practice_html
    assert "Ask Cora about this question" in practice_html

    flashcard_response = owner_browser.get("/courses/cs101/study/flashcards/due/")
    assert flashcard_response.status_code == 200
    flashcard_html = flashcard_response.content.decode()
    for hook in (
        'id="fc-progress"', 'id="fc-card"', 'id="fc-ratings"',
        'id="fc-summary-ring"', 'id="fc-focus-list"', 'id="fc-topics-dialog"',
        'id="fc-save-status"',
    ):
        assert hook in flashcard_html
    assert 'src="/static/agent/js/interactive_flashcards.js?v=interactive-20260831-4"' in flashcard_html
