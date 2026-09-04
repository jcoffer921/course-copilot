import io
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from agent.models import CalendarSyncRecord, CourseMaterial, CourseSession, FlashcardProgress, GradeItem, MasteryScore, Notification, QuizAttempt, SavedSite
from agent import views
from agent.services import ask, material_files, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def api_client(django_user_model):
    user = django_user_model.objects.create_user(username="test-user")
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


def _seed_syllabus(course_id, user):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    }, user)


def _seed_recommendation_material(course_id, user):
    key = material_files.object_storage.save(user, course_id, ".pdf", b"%PDF-test")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="course-syllabus.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS, source_key="syllabus",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_CONFIRMED,
        storage_key=key, size_bytes=9, content_type="application/pdf",
        extracted_data={"course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"]},
    )
    storage.write_notes(course_id, "recommendation-a", {
        "lecture_id": "recommendation-a", "topics": ["A"],
        "chunks": [{"id": "a", "topic": "A", "text": "Processed course content for A."}],
    }, user)
    notes_key = material_files.object_storage.save(user, course_id, ".docx", b"course-content")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="course-notes.docx",
        material_type=CourseMaterial.TYPE_NOTES, source_key="recommendation-a",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=notes_key, size_bytes=14,
    )


def test_profile_get_uses_display_name_and_settings(api_client):
    api_client.user.first_name = "Jordan Lee"
    api_client.user.email = "jordan@example.com"
    api_client.user.save()

    response = api_client.get("/api/profile/")

    assert response.status_code == 200
    assert response.data["display_name"] == "Jordan Lee"
    assert response.data["email"] == "jordan@example.com"
    assert response.data["notifications_enabled"] is False
    assert response.data["email_notifications_enabled"] is False
    assert response.data["study_reminder_time"] == "09:00"


def test_profile_patch_updates_name_username_and_notifications(api_client):
    response = api_client.patch(
        "/api/profile/",
        {"display_name": "Alex Rivera", "username": "alex", "notifications_enabled": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["display_name"] == "Alex Rivera"
    assert response.data["username"] == "alex"
    assert response.data["notifications_enabled"] is True
    api_client.user.refresh_from_db()
    assert api_client.user.first_name == "Alex Rivera"
    assert api_client.user.username == "alex"


def test_profile_patch_updates_notification_channels_independently(api_client):
    response = api_client.patch(
        "/api/profile/",
        {"notifications_enabled": True, "email_notifications_enabled": False},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["notifications_enabled"] is True
    assert response.data["email_notifications_enabled"] is False

    response = api_client.patch(
        "/api/profile/",
        {"notifications_enabled": False, "email_notifications_enabled": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["notifications_enabled"] is False
    assert response.data["email_notifications_enabled"] is True


def test_profile_patch_validates_and_persists_study_preferences(api_client):
    response = api_client.patch("/api/profile/", {
        "timezone": "America/Los_Angeles", "preferred_session_minutes": 60,
        "available_study_days": [1, 3, 5], "reminder_lead_minutes": 30,
        "study_reminder_time": "18:30",
    }, format="json")

    assert response.status_code == 200
    assert response.data["timezone"] == "America/Los_Angeles"
    assert response.data["available_study_days"] == [1, 3, 5]
    assert response.data["study_reminder_time"] == "18:30"


def test_profile_patch_rejects_invalid_timezone_and_duplicate_days(api_client):
    response = api_client.patch("/api/profile/", {
        "timezone": "Mars/Olympus", "available_study_days": [1, 1],
    }, format="json")

    assert response.status_code == 400
    assert "timezone" in response.data
    assert "available_study_days" in response.data


def test_profile_patch_rejects_duplicate_username(api_client, django_user_model):
    django_user_model.objects.create_user(username="taken")

    response = api_client.patch("/api/profile/", {"username": "taken"}, format="json")

    assert response.status_code == 409


def test_references_post_then_get(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    upload = io.BytesIO(b"Some reference content.")
    upload.name = "chapter1.txt"

    response = api_client.post(
        "/api/courses/cs101/references/", {"file": upload, "title": "Chapter 1"}, format="multipart",
    )

    assert response.status_code == 201
    assert response.data["reference"]["reference_id"] == "chapter-1"
    assert response.data["reference"]["text"] == "Some reference content."

    list_response = api_client.get("/api/courses/cs101/references/")
    assert list_response.status_code == 200
    assert len(list_response.data["references"]) == 1
    assert list_response.data["references"][0]["reference_id"] == "chapter-1"


def test_references_get_empty_for_new_course(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/references/")

    assert response.status_code == 200
    assert response.data["references"] == []


def test_saved_sites_post_then_get_stores_url_metadata_only(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/courses/cs101/saved-sites/",
        {"url": "https://example.edu/book", "title": "Course Book"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["site"]["title"] == "Course Book"
    assert response.data["site"]["url"] == "https://example.edu/book"
    assert SavedSite.objects.get(course_id="cs101").url == "https://example.edu/book"

    list_response = api_client.get("/api/courses/cs101/saved-sites/")
    assert list_response.status_code == 200
    assert list_response.data["sites"][0]["title"] == "Course Book"
    assert "text" not in list_response.data["sites"][0]


def test_saved_sites_post_rejects_non_http_url(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/courses/cs101/saved-sites/",
        {"url": "ftp://example.edu/book", "title": "Course Book"},
        format="json",
    )

    assert response.status_code == 400


def test_references_post_rejects_unsupported_file_type(isolated_courses_dir, api_client):
    upload = io.BytesIO(b"binary junk")
    upload.name = "slides.pptx"

    response = api_client.post("/api/courses/cs101/references/", {"file": upload}, format="multipart")

    assert response.status_code == 400


def test_domains_get_empty_before_approval(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/domains/")

    assert response.status_code == 200
    assert response.data == {"domains": []}


def test_domains_put_replaces_approved_list(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["docs.python.org"]}, format="json",
    )

    assert response.status_code == 200
    assert storage.read_trusted_domains("cs101", api_client.user) == ["docs.python.org"]


def test_domains_put_rejects_empty_domain_string(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["good.com", ""]}, format="json",
    )

    assert response.status_code == 422


def test_domain_suggestions_view_never_writes(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)

    async def fake_suggest_domains(course_id, user):
        return ["docs.python.org", "nist.gov"]

    monkeypatch.setattr(views.domain_suggestions, "suggest_domains", fake_suggest_domains)

    response = api_client.post("/api/courses/cs101/domains/suggest/")

    assert response.status_code == 200
    assert response.data == {"suggested": ["docs.python.org", "nist.gov"]}
    assert storage.read_trusted_domains("cs101", api_client.user) == []


def test_domain_suggestions_view_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/nocourse/domains/suggest/")

    assert response.status_code == 404


def test_flashcards_generate_annotates_saved_progress(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)

    async def fake_generate_flashcards_async(course_id, topic=None, chunk_id=None, count=8, user=None):
        return {
            "course_id": course_id,
            "model": "fake",
            "flashcards": [{"term": "Closure", "definition": "Captured state.", "source": "course", "url": None}],
        }

    saved = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "mastered",
        "starred": True,
    }, user=api_client.user)
    monkeypatch.setattr(views.quiz, "generate_flashcards_async", fake_generate_flashcards_async)

    response = api_client.post("/api/courses/cs101/flashcards/generate/", {"count": 1}, format="json")

    assert response.status_code == 200
    card = response.data["flashcards"][0]
    assert card["key"] == saved["key"]
    assert card["status"] == "mastered"
    assert card["starred"] is True


def test_flashcards_generate_reuses_saved_deck(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)
    saved = storage.update_flashcard_progress("cs101", {
        "term": "Closure",
        "definition": "Captured state.",
        "status": "in_progress",
        "starred": False,
    }, user=api_client.user)

    async def fail_generate_flashcards_async(*args, **kwargs):
        raise AssertionError("flashcards should not regenerate when saved cards exist")

    monkeypatch.setattr(views.quiz, "generate_flashcards_async", fail_generate_flashcards_async)

    response = api_client.post("/api/courses/cs101/flashcards/generate/", {"count": 1}, format="json")

    assert response.status_code == 200
    assert response.data["model"] == "saved"
    assert response.data["flashcards"] == [{
        "key": saved["key"],
        "term": "Closure",
        "definition": "Captured state.",
        "source": "saved",
        "url": None,
        "status": "in_progress",
        "starred": False,
    }]


def test_flashcards_generate_regenerate_flag_bypasses_saved_deck(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)
    storage.update_flashcard_progress("cs101", {
        "term": "Old",
        "definition": "Existing card.",
        "status": "mastered",
        "starred": False,
    }, user=api_client.user)

    async def fake_generate_flashcards_async(course_id, topic=None, chunk_id=None, count=8, user=None):
        return {
            "course_id": course_id,
            "model": "fake",
            "flashcards": [{"term": "New", "definition": "Fresh card.", "source": "course", "url": None}],
        }

    monkeypatch.setattr(views.quiz, "generate_flashcards_async", fake_generate_flashcards_async)

    response = api_client.post(
        "/api/courses/cs101/flashcards/generate/",
        {"count": 1, "regenerate": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["model"] == "fake"
    assert response.data["flashcards"][0]["term"] == "New"


def test_flashcard_review_schedules_next_review(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/courses/cs101/flashcards/review/",
        {"key": "card-1", "rating": "good"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["rating"] == "good"
    assert response.data["review_count"] == 1
    assert response.data["next_review"] is not None


def test_flashcard_review_rejects_invalid_rating(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/courses/cs101/flashcards/review/",
        {"key": "card-1", "rating": "meh"},
        format="json",
    )

    assert response.status_code == 400


def test_flashcard_review_of_suspended_card_returns_conflict(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    api_client.post("/api/courses/cs101/flashcards/review/", {"key": "card-1", "rating": "good"}, format="json")
    api_client.post("/api/courses/cs101/flashcards/suspend/", {"key": "card-1"}, format="json")

    response = api_client.post(
        "/api/courses/cs101/flashcards/review/",
        {"key": "card-1", "rating": "good"},
        format="json",
    )

    assert response.status_code == 409


def test_flashcard_suspend_and_due_queue(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    storage.remember_generated_flashcards("cs101", [
        {"key": "card-1", "term": "A", "definition": "One"},
        {"key": "card-2", "term": "B", "definition": "Two"},
    ], user=api_client.user)

    suspend_response = api_client.post(
        "/api/courses/cs101/flashcards/suspend/", {"key": "card-2"}, format="json",
    )
    assert suspend_response.status_code == 200
    assert suspend_response.data["suspended"] is True

    due_response = api_client.get("/api/courses/cs101/flashcards/due/")
    assert due_response.status_code == 200
    due_keys = {card["key"] for card in due_response.data["cards"]}
    assert "card-1" in due_keys
    assert "card-2" not in due_keys


def test_flashcards_due_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    _seed_syllabus("cs101", api_client.user)
    storage.remember_generated_flashcards("cs101", [{"key": "card-1", "term": "A", "definition": "One"}], user=api_client.user)

    other = django_user_model.objects.create_user(username="due-other")
    other_client = APIClient()
    other_client.force_authenticate(user=other)

    response = other_client.get("/api/courses/cs101/flashcards/due/")

    assert response.status_code == 404
    assert "card-1" not in str(response.data)


def test_quiz_record_rejects_forged_chunk_reference(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    }, api_client.user)
    storage.write_notes("cs101", "lecture01", {
        "lecture_id": "lecture01", "source": "notes", "topics": ["A"],
        "chunks": [{"id": "chunk1", "topic": "A", "text": "Real chunk text."}],
    }, api_client.user)

    response = api_client.post(
        "/api/courses/cs101/quiz/record/",
        {
            "lecture_id": "someone-elses-lecture", "chunk_id": "someone-elses-chunk", "topic": "A",
            "question": "Q?", "correct_answer": "yes", "user_answer": "yes",
        },
        format="json",
    )

    assert response.status_code == 400
    assert QuizAttempt.objects.count() == 0


def test_quiz_record_accepts_a_real_owned_chunk(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    }, api_client.user)
    storage.write_notes("cs101", "lecture01", {
        "lecture_id": "lecture01", "source": "notes", "topics": ["A"],
        "chunks": [{"id": "chunk1", "topic": "A", "text": "Real chunk text."}],
    }, api_client.user)

    response = api_client.post(
        "/api/courses/cs101/quiz/record/",
        {
            "lecture_id": "lecture01", "chunk_id": "chunk1", "topic": "A",
            "question": "Q?", "correct_answer": "yes", "user_answer": "yes",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["correct"] is True
    assert QuizAttempt.objects.count() == 1


def test_study_session_lifecycle_via_api(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    start = api_client.post(
        "/api/courses/cs101/study/sessions/",
        {"topic": "A", "duration_minutes": 15, "mode": "mixed"},
        format="json",
    )
    assert start.status_code == 201
    session_id = start.data["session_id"]

    activity = api_client.post(
        f"/api/courses/cs101/study/sessions/{session_id}/activities/",
        {"kind": "flashcard_reviewed", "payload": {"key": "card-1"}},
        format="json",
    )
    assert activity.status_code == 201

    complete = api_client.post(f"/api/courses/cs101/study/sessions/{session_id}/complete/")
    assert complete.status_code == 200
    assert complete.data["summary"]["flashcards_reviewed"] == 1

    detail = api_client.get(f"/api/courses/cs101/study/sessions/{session_id}/")
    assert detail.status_code == 200
    assert len(detail.data["activities"]) == 3

    history = api_client.get("/api/courses/cs101/study/sessions/")
    assert history.status_code == 200
    assert history.data["sessions"][0]["session_id"] == session_id


def test_guided_study_plan_api_returns_owned_note_and_reference_grounding(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    storage.write_notes("cs101", "lecture-a", {
        "lecture_id": "lecture-a", "topics": ["A"],
        "chunks": [{"id": "a-1", "topic": "A", "text": "Course note evidence."}],
    }, api_client.user)
    storage.write_reference("cs101", "reference-a", {
        "reference_id": "reference-a", "title": "Reference for A",
        "source_filename": "reference.txt", "text": "Supporting material for topic A.",
    }, api_client.user)
    notes_key = material_files.object_storage.save(api_client.user, "cs101", ".docx", b"course-notes")
    CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="lecture-a.docx",
        material_type=CourseMaterial.TYPE_NOTES, source_key="lecture-a",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=notes_key, size_bytes=12,
    )
    reference_key = material_files.object_storage.save(api_client.user, "cs101", ".pdf", b"%PDF-reference")
    CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="reference-a.pdf",
        material_type=CourseMaterial.TYPE_REFERENCE, source_key="reference-a",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=reference_key, size_bytes=14,
    )

    response = api_client.get(
        "/api/courses/cs101/study/plan/",
        {"duration_minutes": 15, "mode": "mixed"},
    )

    assert response.status_code == 200
    assert response.data["topic"] == "A"
    assert response.data["grounded"] is True
    assert response.data["can_generate"] is True
    assert response.data["has_course_materials"] is True
    assert response.data["source_counts"] == {"notes": 1, "references": 1, "files": 2}


def test_study_session_start_rejects_missing_owned_course_and_unconfirmed_topic(isolated_courses_dir, api_client):
    missing = api_client.post("/api/courses/private/study/sessions/", {"topic": "A"}, format="json")
    assert missing.status_code == 404
    _seed_syllabus("cs101", api_client.user)
    invalid_topic = api_client.post("/api/courses/cs101/study/sessions/", {"topic": "Not confirmed"}, format="json")
    assert invalid_topic.status_code == 400


def test_study_session_activity_after_completion_is_rejected(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    start = api_client.post("/api/courses/cs101/study/sessions/", {}, format="json")
    session_id = start.data["session_id"]
    api_client.post(f"/api/courses/cs101/study/sessions/{session_id}/complete/")

    response = api_client.post(
        f"/api/courses/cs101/study/sessions/{session_id}/activities/",
        {"kind": "quiz_answered", "payload": {"correct": True}},
        format="json",
    )

    assert response.status_code == 409


def test_study_session_detail_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    _seed_syllabus("cs101", api_client.user)
    start = api_client.post("/api/courses/cs101/study/sessions/", {}, format="json")
    session_id = start.data["session_id"]

    other = django_user_model.objects.create_user(username="study-session-other-api")
    other_client = APIClient()
    other_client.force_authenticate(user=other)

    response = other_client.get(f"/api/courses/cs101/study/sessions/{session_id}/")

    assert response.status_code == 404


def test_quiz_history_rejects_malformed_limit(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/quiz/history/?limit=abc")

    assert response.status_code == 400
    assert response.data == {"detail": "limit must be an integer"}


def test_reminders_rejects_malformed_within_days(api_client):
    response = api_client.get("/api/reminders/?within_days=soon")

    assert response.status_code == 400
    assert response.data == {"detail": "within_days must be an integer"}


def test_recommendations_endpoint_returns_ranked_candidates(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    _seed_recommendation_material("cs101", api_client.user)

    response = api_client.get("/api/recommendations/")

    assert response.status_code == 200
    assert response.data["recommendations"][0]["course_id"] == "cs101"
    assert response.data["recommendations"][0]["topic"] == "A"
    assert response.data["recommendations"][0]["status"] == "not_started"


def test_recommendations_endpoint_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    _seed_syllabus("cs101", api_client.user)
    _seed_recommendation_material("cs101", api_client.user)

    other = django_user_model.objects.create_user(username="recommendations-other")
    other_client = APIClient()
    other_client.force_authenticate(user=other)

    response = other_client.get("/api/recommendations/")

    assert response.status_code == 200
    assert response.data["recommendations"] == []


def test_recommendations_dismiss_hides_it_from_future_results(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    _seed_recommendation_material("cs101", api_client.user)

    dismiss_response = api_client.post(
        "/api/recommendations/dismiss/", {"course_id": "cs101", "topic": "A"}, format="json",
    )
    assert dismiss_response.status_code == 200

    response = api_client.get("/api/recommendations/")
    assert response.data["recommendations"] == []


def test_recommendations_dismiss_rejects_invalid_course_id(isolated_courses_dir, api_client):
    bad_id = "x" * 65

    response = api_client.post(
        "/api/recommendations/dismiss/", {"course_id": bad_id, "topic": "A"}, format="json",
    )

    assert response.status_code == 400


def test_mastery_insight_returns_the_analyzer_result(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)

    async def fake_analyze(user, course_id, topic=None):
        assert course_id == "cs101"
        assert topic == "A"
        return {"insight": "Misses base cases.", "recommended_action": "Review base cases.", "confidence": "medium"}

    monkeypatch.setattr(views.mastery_analyzer, "analyze", fake_analyze)

    response = api_client.post("/api/courses/cs101/mastery/insight/", {"topic": "A"}, format="json")

    assert response.status_code == 200
    assert response.data == {"insight": "Misses base cases.", "recommended_action": "Review base cases.", "confidence": "medium"}


def test_mastery_insight_404s_for_missing_course(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/does-not-exist/mastery/insight/", {}, format="json")

    assert response.status_code == 404


def test_mastery_insight_returns_422_when_no_data_yet(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)

    async def fake_analyze(user, course_id, topic=None):
        raise views.mastery_analyzer.NoMasteryDataError("nothing to analyze yet")

    monkeypatch.setattr(views.mastery_analyzer, "analyze", fake_analyze)

    response = api_client.post("/api/courses/cs101/mastery/insight/", {}, format="json")

    assert response.status_code == 422


def test_study_plan_endpoint_returns_the_planner_result(isolated_courses_dir, api_client, monkeypatch):
    async def fake_generate_plan(user, available_minutes=None, course_ids=None):
        assert available_minutes == 90
        return {"plan": [{"course_id": "cs101", "course_name": "Test", "topic": "A", "activity": "Quiz", "minutes": 30, "reason": "Weak.", "priority": 1}], "summary": "Focus on A."}

    monkeypatch.setattr(views.study_planner, "generate_plan", fake_generate_plan)

    response = api_client.get("/api/study-plan/?available_minutes=90")

    assert response.status_code == 200
    assert response.data["summary"] == "Focus on A."
    assert response.data["plan"][0]["topic"] == "A"


def test_study_plan_endpoint_returns_422_when_no_context(isolated_courses_dir, api_client, monkeypatch):
    async def fake_generate_plan(user, available_minutes=None, course_ids=None):
        raise views.study_planner.NoStudyContextError("no courses yet")

    monkeypatch.setattr(views.study_planner, "generate_plan", fake_generate_plan)

    response = api_client.get("/api/study-plan/")

    assert response.status_code == 422


def test_study_plan_endpoint_rejects_a_non_positive_available_minutes(isolated_courses_dir, api_client):
    response = api_client.get("/api/study-plan/?available_minutes=0")

    assert response.status_code == 400


def _seed_exam_course(course_id, user, *, title="Midterm", date="2026-03-01"):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [{"date": date, "title": title, "type": "test_quiz"}],
        "grading": [], "topics": ["A"],
    }, user)
    from agent.services import calendar_events
    return next(e["id"] for e in calendar_events.all_events(user, course_ids=[course_id]) if e["type"] == "test_quiz")


def test_exams_list_and_workspace_endpoints(isolated_courses_dir, api_client):
    event_id = _seed_exam_course("cs101", api_client.user)

    list_response = api_client.get("/api/courses/cs101/exams/")
    assert list_response.status_code == 200
    assert list_response.data["exams"][0]["id"] == event_id

    workspace_response = api_client.get(f"/api/courses/cs101/exams/{event_id}/")
    assert workspace_response.status_code == 200
    assert workspace_response.data["event"]["title"] == "Midterm"
    assert workspace_response.data["topics"][0]["topic"] == "A"


def test_exam_workspace_404s_for_unknown_event(isolated_courses_dir, api_client):
    _seed_exam_course("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/exams/not-a-real-event/")

    assert response.status_code == 404


def test_exam_plan_patch_updates_included_topics(isolated_courses_dir, api_client):
    event_id = _seed_exam_course("cs101", api_client.user)

    response = api_client.patch(
        f"/api/courses/cs101/exams/{event_id}/plan/", {"included_topics": []}, format="json",
    )

    assert response.status_code == 200
    assert response.data["included_topics"] == []


def test_exam_plan_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    event_id = _seed_exam_course("cs101", api_client.user)

    other = django_user_model.objects.create_user(username="exam-plan-other")
    other_client = APIClient()
    other_client.force_authenticate(user=other)

    response = other_client.patch(
        f"/api/courses/cs101/exams/{event_id}/plan/", {"included_topics": []}, format="json",
    )

    assert response.status_code == 404


def test_exam_study_guide_rejects_when_nothing_selected(isolated_courses_dir, api_client):
    event_id = _seed_exam_course("cs101", api_client.user)
    api_client.patch(f"/api/courses/cs101/exams/{event_id}/plan/", {"included_topics": []}, format="json")

    response = api_client.post(f"/api/courses/cs101/exams/{event_id}/study-guide/")

    assert response.status_code == 422


def test_flashcard_progress_patch_and_reset(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.patch(
        "/api/courses/cs101/flashcards/progress/",
        {"term": "Closure", "definition": "Captured state.", "status": "in_progress", "starred": False},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == "in_progress"
    assert response.data["starred"] is False
    key = response.data["key"]
    assert key in storage.read_flashcard_progress("cs101", user=api_client.user)["cards"]

    reset_response = api_client.post(
        "/api/courses/cs101/flashcards/progress/reset/",
        {"keys": [key]},
        format="json",
    )

    assert reset_response.status_code == 200
    card = storage.read_flashcard_progress("cs101", user=api_client.user)["cards"][key]
    assert card["term"] == "Closure"
    assert card["definition"] == "Captured state."
    assert "status" not in card


def test_flashcard_progress_patch_rejects_missing_course(isolated_courses_dir, api_client):
    response = api_client.patch(
        "/api/courses/missing/flashcards/progress/",
        {"term": "Closure", "definition": "Captured state.", "status": "mastered", "starred": False},
        format="json",
    )

    assert response.status_code == 404


def test_flashcard_progress_patch_rejects_invalid_course_id(isolated_courses_dir, api_client):
    bad_id = "x" * 65

    response = api_client.patch(
        f"/api/courses/{bad_id}/flashcards/progress/",
        {"term": "Closure", "definition": "Captured state.", "status": "mastered", "starred": False},
        format="json",
    )

    assert response.status_code == 400


def test_flashcard_progress_patch_rejects_bad_status(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.patch(
        "/api/courses/cs101/flashcards/progress/",
        {"term": "Closure", "definition": "Captured state.", "status": "done", "starred": False},
        format="json",
    )

    assert response.status_code == 400


def test_deadline_post_accepts_duration_completion_and_legacy_category(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/deadlines/",
        {
            "course_id": "cs101",
            "date": "2026-09-01",
            "time": "09:00",
            "end_time": "10:30",
            "title": "Midterm",
            "type": "exam",
            "completed": True,
            "estimated_effort_minutes": 75,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["type"] == "test_quiz"
    assert response.data["end_time"] == "10:30"
    assert response.data["completed"] is True
    assert response.data["source"] == "manual"
    assert response.data["estimated_effort_minutes"] == 75


def test_deadline_post_rejects_bad_duration_and_category(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    bad_duration = api_client.post(
        "/api/deadlines/",
        {
            "course_id": "cs101",
            "date": "2026-09-01",
            "time": "11:00",
            "end_time": "10:30",
            "title": "Project",
            "type": "project",
        },
        format="json",
    )
    bad_category = api_client.post(
        "/api/deadlines/",
        {
            "course_id": "cs101",
            "date": "2026-09-01",
            "title": "Project",
            "type": "random",
        },
        format="json",
    )

    assert bad_duration.status_code == 400
    assert bad_category.status_code == 400


def test_notifications_endpoint_generates_overdue_deadline_once(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    overdue = (date.today() - timedelta(days=1)).isoformat()
    create_response = api_client.post(
        "/api/deadlines/",
        {
            "course_id": "cs101",
            "date": overdue,
            "title": "Problem set",
            "type": "hw",
            "completed": False,
        },
        format="json",
    )
    assert create_response.status_code == 201

    first = api_client.get("/api/notifications/")
    second = api_client.get("/api/notifications/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["unread_count"] == 1
    assert second.data["unread_count"] == 1
    assert len(second.data["notifications"]) == 1
    assert second.data["notifications"][0]["category"] == "hw"

    mark_read = api_client.patch("/api/notifications/read/", {"ids": [second.data["notifications"][0]["id"]]}, format="json")

    assert mark_read.status_code == 200
    assert mark_read.data["unread_count"] == 0
    assert mark_read.data["notifications"] == []
    assert api_client.get("/api/notifications/").data["notifications"] == []


def test_notifications_endpoint_never_returns_another_users_rows(api_client, django_user_model):
    other = django_user_model.objects.create_user(username="notification-other")
    Notification.objects.create(
        user=api_client.user, notification_key="mine", kind="overdue_deadline",
        title="My deadline", body="Owned by the signed-in user.",
    )
    Notification.objects.create(
        user=other, notification_key="theirs", kind="overdue_deadline",
        title="Private other deadline", body="Must not cross the user boundary.",
    )

    response = api_client.get("/api/notifications/")

    assert response.status_code == 200
    assert [item["title"] for item in response.data["notifications"]] == ["My deadline"]
    assert response.data["unread_count"] == 1


def test_create_course_draft_returns_201(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/courses/newclass/", {"course_name": "New Class"}, format="json",
    )

    assert response.status_code == 201
    assert response.data == {"course_id": "newclass", "course_name": "New Class"}
    assert (isolated_courses_dir / str(api_client.user.pk) / "newclass" / "course.json").exists()


def test_create_course_draft_rejects_blank_name(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/newclass/", {"course_name": ""}, format="json")

    assert response.status_code == 400


def test_create_course_draft_conflicts_with_existing_draft(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    assert response.status_code == 409


def test_create_course_draft_conflicts_with_existing_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post("/api/courses/cs101/", {"course_name": "Intro to CS"}, format="json")

    assert response.status_code == 409


def test_rename_draft_course(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.patch("/api/courses/newclass/", {"course_name": "Renamed Class"}, format="json")

    assert response.status_code == 200
    assert response.data == {"course_id": "newclass", "course_name": "Renamed Class"}
    assert storage.read_syllabus("newclass", api_client.user) is None  # still a draft, not promoted


def test_rename_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.patch("/api/courses/cs101/", {"course_name": "Renamed"}, format="json")

    assert response.status_code == 200
    assert storage.read_syllabus("cs101", api_client.user)["course_name"] == "Renamed"


def test_rename_nonexistent_course_404s(isolated_courses_dir, api_client):
    response = api_client.patch("/api/courses/nocourse/", {"course_name": "X"}, format="json")

    assert response.status_code == 404


def test_courses_overview_returns_saved_metadata_without_placeholder_facts(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/cmpsc221/", {
        "course_name": "Data Structures", "course_code": "CMPSC 221",
        "instructor": "Dr. Linda Park", "semester": "fall-2026", "color": "#527d47",
    }, format="json")
    assert response.status_code == 201

    overview = api_client.get("/api/courses/overview/?semester=fall-2026")

    assert overview.status_code == 200
    assert overview.data["courses"][0]["name"] == "Data Structures"
    assert overview.data["courses"][0]["code"] == "CMPSC 221"
    assert overview.data["courses"][0]["next_deadline"] is None
    assert overview.data["courses"][0]["mastery"]["label"] == "Not enough data"


def test_course_semester_move_requires_explicit_confirmation(isolated_courses_dir, api_client):
    api_client.post("/api/courses/cmpsc221/", {
        "course_name": "Data Structures", "semester": "fall-2026",
    }, format="json")

    denied = api_client.patch("/api/courses/cmpsc221/", {"semester": "spring-2027"}, format="json")
    allowed = api_client.patch("/api/courses/cmpsc221/", {
        "semester": "spring-2027", "confirm_semester_move": True,
    }, format="json")

    assert denied.status_code == 409
    assert denied.data["code"] == "semester_move_confirmation_required"
    assert allowed.status_code == 200
    assert storage.read_course_metadata("cmpsc221", api_client.user)["semester"] == "spring-2027"


def test_archive_restore_is_owner_scoped_and_preserves_foreign_course(isolated_courses_dir, api_client, django_user_model):
    other = django_user_model.objects.create_user(username="archive-other")
    storage.write_course_draft("shared", "Other private course", other, semester="fall-2026", archived=False)

    denied = api_client.patch("/api/courses/shared/archive/", {"archived": True}, format="json")

    assert denied.status_code == 404
    assert storage.read_course_metadata("shared", other)["archived"] is False

    storage.write_course_draft("mine", "My course", api_client.user, semester="fall-2026", archived=False)
    archived = api_client.patch("/api/courses/mine/archive/", {"archived": True}, format="json")
    restored = api_client.patch("/api/courses/mine/archive/", {"archived": False}, format="json")

    assert archived.status_code == restored.status_code == 200
    assert storage.read_course_metadata("mine", api_client.user)["archived"] is False


def test_courses_overview_never_lists_another_users_same_slug(isolated_courses_dir, api_client, django_user_model):
    other = django_user_model.objects.create_user(username="overview-other")
    storage.write_course_draft("shared", "Other private course", other, semester="fall-2026", archived=False)

    response = api_client.get("/api/courses/overview/?semester=fall-2026")

    assert response.status_code == 200
    assert response.data["courses"] == []
    assert response.data["summary"]["active_courses"] == 0


def test_courses_overview_rejects_invalid_semester(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/overview/?semester=../../../private")

    assert response.status_code == 400


def test_delete_draft_course(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.delete("/api/courses/newclass/", {"confirmation": "newclass"}, format="json")

    assert response.status_code == 204
    assert not (isolated_courses_dir / str(api_client.user.pk) / "newclass").exists()


def test_delete_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.delete("/api/courses/cs101/", {"confirmation": "cs101"}, format="json")

    assert response.status_code == 204
    assert not (isolated_courses_dir / str(api_client.user.pk) / "cs101").exists()


def test_delete_nonexistent_course_404s(isolated_courses_dir, api_client):
    response = api_client.delete("/api/courses/nocourse/", {"confirmation": "nocourse"}, format="json")

    assert response.status_code == 404


def test_delete_course_also_removes_its_custom_events(isolated_courses_dir, api_client):
    from agent.services import custom_events

    user = api_client.user
    _seed_syllabus("cs101", user)
    _seed_syllabus("cs102", user)
    custom_events.create_event("cs101", "2026-09-01", None, "Delete me", "other", user=user)
    custom_events.create_event("cs102", "2026-09-01", None, "Keep me (other course)", "other", user=user)
    custom_events.create_event(None, "2026-09-01", None, "Keep me (general)", "other", user=user)

    response = api_client.delete("/api/courses/cs101/", {"confirmation": "cs101"}, format="json")

    assert response.status_code == 204
    remaining_titles = {e["title"] for e in custom_events.list_events(user=user)}
    assert remaining_titles == {"Keep me (other course)", "Keep me (general)"}


def test_delete_course_only_removes_the_owning_users_custom_events(isolated_courses_dir, api_client, django_user_model):
    from agent.services import custom_events

    owner = api_client.user
    other = django_user_model.objects.create_user(username="other-user")

    _seed_syllabus("cs101", owner)
    _seed_syllabus("cs101", other)
    custom_events.create_event("cs101", "2026-09-01", None, "Owner's deadline", "other", user=owner)
    custom_events.create_event("cs101", "2026-09-01", None, "Other user's deadline", "other", user=other)

    response = api_client.delete("/api/courses/cs101/", {"confirmation": "cs101"}, format="json")

    assert response.status_code == 204
    assert {e["title"] for e in custom_events.list_events(user=owner)} == set()
    assert {e["title"] for e in custom_events.list_events(user=other)} == {"Other user's deadline"}


def test_delete_course_removes_db_backed_course_state(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)
    _seed_syllabus("cs102", api_client.user)
    user = api_client.user
    storage.update_flashcard_progress("cs101", {
        "term": "Closure", "definition": "Captured state.", "status": "mastered", "starred": False,
    }, user=user)
    GradeItem.objects.create(
        course_id="cs101", user=user, item_id="hw1", component="Homework",
        title="HW 1", score=9, max_points=10,
    )
    CalendarSyncRecord.objects.create(
        course_id="cs101", user=user, date="2026-09-01", title="Midterm",
        type="test_quiz", google_event_id="g1", synced_at="now",
    )
    QuizAttempt.objects.create(
        course_id="cs101", user=user, lecture_id="l1", chunk_id="c1", topic="A",
        question="Q", correct_answer="A", user_answer="A", correct=True, timestamp="2026-09-01T00:00:00+00:00",
    )
    MasteryScore.objects.create(
        course_id="cs101", user=user, topic="A", score=1, attempts=1,
        last_seen="2026-09-01T00:00:00+00:00", status="mastered", rebuilt_at="now",
    )
    CourseSession.objects.create(
        course_id="cs101", user=user, session_id="s1",
        created_at="2026-09-01T00:00:00+00:00", updated_at="2026-09-01T00:00:00+00:00",
    )
    GradeItem.objects.create(
        course_id="cs102", user=user, item_id="hw1", component="Homework",
        title="Keep", score=10, max_points=10,
    )

    response = api_client.delete("/api/courses/cs101/", {"confirmation": "cs101"}, format="json")

    assert response.status_code == 204
    # Scoped by user, not just course_id: course_id="cs101" is reused as a
    # fixture value across many tests in this file (and other users'
    # records for it may legitimately exist in the shared test database),
    # so a global course_id-only count would be sensitive to unrelated
    # tests rather than verifying delete_course cleaned up *this* user's
    # state, which is what's actually under test.
    assert FlashcardProgress.objects.filter(course_id="cs101", user=user).count() == 0
    assert GradeItem.objects.filter(course_id="cs101", user=user).count() == 0
    assert CalendarSyncRecord.objects.filter(course_id="cs101", user=user).count() == 0
    assert QuizAttempt.objects.filter(course_id="cs101", user=user).count() == 0
    assert MasteryScore.objects.filter(course_id="cs101", user=user).count() == 0
    assert CourseSession.objects.filter(course_id="cs101", user=user).count() == 0
    assert GradeItem.objects.filter(course_id="cs102", user=user).count() == 1


class _NeverCalledMessages:
    async def create(self, **kwargs):
        raise AssertionError(
            "API client should not be reached — corrupt reference file must fail first"
        )


class _NeverCalledClient:
    def __init__(self):
        self.messages = _NeverCalledMessages()


def test_ask_returns_500_not_crash_on_corrupt_reference_file(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101", api_client.user)

    # get_client() is called before storage.read_references() inside
    # ask_async, so it must be mocked so construction succeeds — but its
    # messages.create() must never actually be reached, since the
    # corrupt-file error should raise before any network call happens.
    monkeypatch.setattr(ask, "get_client", lambda: _NeverCalledClient())

    references_dir = isolated_courses_dir / str(api_client.user.pk) / "cs101" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    (references_dir / "bad.json").write_text("not valid json {{{", encoding="utf-8")

    response = api_client.post(
        "/api/courses/cs101/ask/", {"question": "what is this course about?"}, format="json",
    )

    assert response.status_code == 500
    assert "detail" in response.data


def test_grading_config_get_returns_default_scale_when_unset(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["grading"] == [{"component": "Homework", "weight_pct": 100}]
    assert response.data["grade_scale"]["passing_pct"] == 60


def test_grading_config_get_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grading/")
    assert response.status_code == 404


def test_grading_config_put_updates_categories(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 5}]},
        format="json",
    )

    assert response.status_code == 200
    updated = storage.read_syllabus("cs101", api_client.user)
    assert updated["grading"] == [{"component": "Homework", "weight_pct": 100, "total_items": 5, "drop_lowest": None}]


def test_grading_config_put_rejects_invalid_total_items(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 0}]},
        format="json",
    )

    assert response.status_code == 422


def test_grading_config_put_accepts_non_summing_weights_with_warning(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 50}]},
        format="json",
    )

    assert response.status_code == 200
    assert any("sum to" in w for w in response.data["warnings"])


def test_grading_config_put_warns_about_orphaned_grades(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
        ]}, user=api_client.user)

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Projects", "weight_pct": 100}]},
        format="json",
    )

    assert response.status_code == 200
    assert any("Homework" in w for w in response.data["warnings"])


def test_grading_config_put_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.put(
        "/api/courses/cs101/grading/", {"grading": []}, format="json",
    )
    assert response.status_code == 404


def test_grading_config_get_includes_category_choices(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["category_choices"] == storage.GRADING_CATEGORY_CHOICES


def test_grades_get_returns_items_and_breakdown(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
        ]}, user=api_client.user)

    response = api_client.get("/api/courses/cs101/grades/")

    assert response.status_code == 200
    assert len(response.data["items"]) == 1
    assert response.data["grade"]["overall_pct"] == 90.0


def test_grades_get_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grades/")
    assert response.status_code == 404


def test_grade_items_post_adds_item(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)

    response = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["component"] == "Homework"
    assert len(storage.read_grades("cs101", user=api_client.user)["items"]) == 1


def test_grade_items_post_422s_for_unknown_component(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)

    response = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Nonexistent", "title": "X", "score": 1, "max_points": 1},
        format="json",
    )

    assert response.status_code == 422


def test_grade_item_detail_patch_updates(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)
    add = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )
    item_id = add.data["id"]

    response = api_client.patch(f"/api/courses/cs101/grades/items/{item_id}/", {"score": 95}, format="json")

    assert response.status_code == 200
    assert response.data["score"] == 95


def test_grade_item_detail_patch_404s_for_unknown_item(isolated_courses_dir, api_client):
    response = api_client.patch("/api/courses/cs101/grades/items/nope/", {"score": 1}, format="json")
    assert response.status_code == 404


def test_grade_item_detail_delete_removes_item(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)
    add = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )
    item_id = add.data["id"]

    response = api_client.delete(f"/api/courses/cs101/grades/items/{item_id}/")

    assert response.status_code == 204
    assert storage.read_grades("cs101")["items"] == []


def test_grades_whatif_returns_needed_and_missable(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100, "total_items": 4}], "topics": [],
    }, api_client.user)

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")

    assert response.status_code == 200
    assert "grade_needed" in response.data
    assert "missable_by_category" in response.data


def test_grades_whatif_400s_for_non_numeric_target(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=notanumber")

    assert response.status_code == 400


def test_grades_whatif_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")
    assert response.status_code == 404


def test_grades_summary_returns_rollup(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 88, "max_points": 100},
        ]}, user=api_client.user)

    response = api_client.get("/api/grades/summary/")

    assert response.status_code == 200
    assert response.data["average_pct"] == 88.0


def test_grades_summary_empty_when_no_courses(isolated_courses_dir, api_client):
    response = api_client.get("/api/grades/summary/")

    assert response.status_code == 200
    assert response.data["courses"] == []


def test_anonymous_request_to_api_is_rejected(isolated_courses_dir):
    from rest_framework.test import APIClient
    anonymous_client = APIClient()  # deliberately not the (soon-to-be authenticated) api_client fixture

    response = anonymous_client.get("/api/courses/cs101/syllabus/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_basic_auth_with_valid_password_is_rejected(isolated_courses_dir, django_user_model):
    import base64

    user = django_user_model.objects.create_user(username="has-password", password="correct-horse-battery-staple")
    client = APIClient()
    credentials = base64.b64encode(b"has-password:correct-horse-battery-staple").decode()

    response = client.get("/api/courses/cs101/syllabus/", HTTP_AUTHORIZATION=f"Basic {credentials}")

    assert response.status_code == 401


def test_anonymous_request_to_ontrack_page_renders_welcome(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Stay organized." in response.content


@pytest.mark.django_db
def test_reminders_view_scopes_service_call_to_authenticated_user(api_client, monkeypatch):
    from agent.services import reminders

    calls = []

    def fake_upcoming(user, within_days=None, course_ids=None):
        calls.append((user, within_days, course_ids))
        return []

    monkeypatch.setattr(reminders, "upcoming_deadlines", fake_upcoming)

    response = api_client.get("/api/reminders/?within_days=7&course_id=cs101")

    assert response.status_code == 200
    assert calls == [(api_client.handler._force_user, 7, ["cs101"])]


@pytest.mark.django_db
def test_calendar_sync_creates_event(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import MagicMock, patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "event-abc"}
    with patch("agent.services.calendar_sync.build", return_value=mock_service):
        response = client.post(
            "/api/courses/cs101/calendar-sync/",
            {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
            format="json",
        )

    assert response.status_code == 201
    assert response.data == {"google_event_id": "event-abc"}


@pytest.mark.django_db
def test_calendar_sync_rejects_duplicate(isolated_courses_dir):
    from datetime import timedelta

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection
    from agent.services import storage

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    }, user=user)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/courses/cs101/calendar-sync/",
        {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
        format="json",
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_calendar_sync_returns_502_when_google_auth_fails(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    def _fake_refresh_failure(self, request):
        from google.auth.exceptions import RefreshError
        raise RefreshError("invalid_grant")

    with patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        response = client.post(
            "/api/courses/cs101/calendar-sync/",
            {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
            format="json",
        )

    assert response.status_code == 502


@pytest.mark.django_db
def test_calendar_sync_rejects_malformed_date(isolated_courses_dir):
    from datetime import timedelta

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/courses/cs101/calendar-sync/",
        {"date": "not-a-date", "title": "X", "type": "exam"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_calendar_sync_requires_separate_calendar_connection(isolated_courses_dir):
    from django.contrib.auth.models import User
    from rest_framework.test import APIClient

    user = User.objects.create_user(username="identity-only-user")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/courses/cs101/calendar-sync/",
        {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "calendar_not_connected"


@pytest.mark.django_db
def test_calendar_sync_returns_502_not_raw_500_on_unexpected_service_error(isolated_courses_dir, api_client, monkeypatch):
    # Backstop for any *future* unexpected exception from the service layer
    # — the endpoint's binding constraint is that it must never surface a
    # raw 500, even for a failure mode the specific except clauses don't
    # already name.
    def _boom(user, course_id, date, title, event_type):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr(views.calendar_sync, "add_deadline_to_calendar", _boom)

    response = api_client.post(
        "/api/courses/cs101/calendar-sync/",
        {"date": "2026-09-01", "title": "Midterm", "type": "exam"},
        format="json",
    )

    assert response.status_code == 502
    assert response.data == {"detail": "Could not add to Google Calendar."}


@pytest.mark.django_db
def test_deadlines_get_returns_merged_list(isolated_courses_dir, api_client):
    from agent.services import custom_events

    custom_events.create_event("cs101", "2099-01-01", None, "Future thing", "other", user=api_client.user)

    response = api_client.get("/api/deadlines/")

    assert response.status_code == 200
    assert any(d["title"] == "Future thing" for d in response.data)


@pytest.mark.django_db
def test_calendar_api_returns_complete_confirmed_snapshot(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Computer Science",
        "dates": [{"date": "2025-01-01", "title": "Past class", "type": "class"}],
        "grading": [], "topics": [],
    }, api_client.user)
    response = api_client.get("/api/calendar/")
    assert response.status_code == 200
    assert response.data["events"][0]["title"] == "Past class"
    assert response.data["events"][0]["confirmed"] is True
    assert response.data["courses"][0]["name"] == "Computer Science"


@pytest.mark.django_db
def test_calendar_api_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    from rest_framework.test import APIClient
    from agent.services import custom_events
    other = django_user_model.objects.create_user(username="calendar-other")
    custom_events.create_event(None, "2026-09-01", None, "Private event", "other", user=other)
    assert api_client.get("/api/calendar/").data["events"] == []
    other_client = APIClient()
    other_client.force_authenticate(user=other)
    event_id = other_client.get("/api/calendar/").data["events"][0]["id"]
    assert api_client.delete(f"/api/deadlines/{event_id}/").status_code == 404


@pytest.mark.django_db
def test_deadline_crud_round_trips_location_and_notes(isolated_courses_dir, api_client):
    created = api_client.post("/api/deadlines/", {
        "date": "2026-09-01", "title": "Office hours", "type": "other",
        "location": "Library 201", "notes": "Bring chapter notes.",
    }, format="json")
    assert created.status_code == 201
    event_id = created.data["id"]
    assert api_client.get("/api/calendar/").data["events"][0]["location"] == "Library 201"
    updated = api_client.patch(f"/api/deadlines/{event_id}/", {"notes": "Bring questions."}, format="json")
    assert updated.status_code == 200
    assert updated.data["notes"] == "Bring questions."


@pytest.mark.django_db
def test_deadlines_get_can_filter_by_course_id(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS", "dates": [{"date": "2099-01-01", "title": "CS Final", "type": "exam"}],
        "grading": [], "topics": [],
    }, api_client.user)
    storage.write_syllabus("math201", {
        "course_id": "math201", "course_name": "Math", "dates": [{"date": "2099-01-01", "title": "Math Final", "type": "exam"}],
        "grading": [], "topics": [],
    }, api_client.user)

    response = api_client.get("/api/deadlines/?course_id=cs101")

    assert response.status_code == 200
    assert [d["title"] for d in response.data] == ["CS Final"]


@pytest.mark.django_db
def test_deadlines_get_for_draft_course_returns_empty_list(isolated_courses_dir, api_client):
    storage.write_course_draft("draft101", "Draft Class", api_client.user)

    response = api_client.get("/api/deadlines/?course_id=draft101")

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_deadlines_post_replacement_hides_syllabus_deadline(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS", "dates": [{"date": "2099-01-01", "title": "Project Due", "type": "assignment"}],
        "grading": [], "topics": [],
    }, api_client.user)
    original = api_client.get("/api/deadlines/?course_id=cs101").data[0]

    response = api_client.post(
        "/api/deadlines/",
        {
            "course_id": "cs101",
            "date": "2099-01-02",
            "time": "15:00",
            "title": "Project draft due",
            "type": "assignment",
            "replaces_syllabus_key": original["key"],
        },
        format="json",
    )

    assert response.status_code == 201
    deadlines = api_client.get("/api/deadlines/?course_id=cs101").data
    assert [d["title"] for d in deadlines] == ["Project draft due"]
    assert deadlines[0]["source"] == "manual"


@pytest.mark.django_db
def test_deadlines_post_creates_custom_event(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/deadlines/",
        {"course_id": "cs101", "date": "2026-09-01", "time": "14:00", "title": "Study group", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Study group"
    # The view converts the validated TimeField back to a plain "HH:MM"
    # string (d["time"].strftime("%H:%M")) before calling create_event, and
    # the response is that same stored dict returned as-is (not re-run
    # through DRF serialization) — so it comes back "HH:MM", not "HH:MM:SS".
    assert response.data["time"] == "14:00"


@pytest.mark.django_db
def test_deadlines_post_general_event_has_null_course_id(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-11-26", "title": "Thanksgiving break", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["course_id"] is None


@pytest.mark.django_db
def test_deadlines_post_rejects_invalid_type(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "X", "type": "not-a-real-type"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_deadlines_post_rejects_nonexistent_course_id(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/deadlines/",
        {"course_id": "nope", "date": "2026-09-01", "title": "X", "type": "other"},
        format="json",
    )

    assert response.status_code == 422
    assert api_client.get("/api/deadlines/").data == []


@pytest.mark.django_db
def test_deadlines_post_accepts_real_course_id(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    response = api_client.post(
        "/api/deadlines/",
        {"course_id": "cs101", "date": "2026-09-01", "title": "X", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["course_id"] == "cs101"


@pytest.mark.django_db
def test_custom_event_detail_patch_updates_event(isolated_courses_dir, api_client):
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Original", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    response = api_client.patch(f"/api/deadlines/{event_id}/", {"title": "Renamed"}, format="json")

    assert response.status_code == 200
    assert response.data["title"] == "Renamed"


@pytest.mark.django_db
def test_custom_event_detail_patch_null_time_clears_it(isolated_courses_dir, api_client):
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "time": "14:00", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]
    assert create_response.data["time"] == "14:00"

    response = api_client.patch(f"/api/deadlines/{event_id}/", {"time": None}, format="json")

    assert response.status_code == 200
    assert response.data["time"] is None


@pytest.mark.django_db
def test_custom_event_detail_patch_null_course_id_becomes_general(isolated_courses_dir, api_client):
    _seed_syllabus("cs101", api_client.user)

    create_response = api_client.post(
        "/api/deadlines/",
        {"course_id": "cs101", "date": "2026-09-01", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]
    assert create_response.data["course_id"] == "cs101"

    response = api_client.patch(f"/api/deadlines/{event_id}/", {"course_id": None}, format="json")

    assert response.status_code == 200
    assert response.data["course_id"] is None


@pytest.mark.django_db
def test_custom_event_detail_patch_rejects_nonexistent_course_id(isolated_courses_dir, api_client):
    future_date = (date.today() + timedelta(days=7)).isoformat()
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": future_date, "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    response = api_client.patch(f"/api/deadlines/{event_id}/", {"course_id": "nope"}, format="json")

    assert response.status_code == 422
    assert api_client.get("/api/deadlines/").data[0]["course_id"] is None


@pytest.mark.django_db
def test_custom_event_detail_patch_404_when_not_found(isolated_courses_dir, api_client):
    response = api_client.patch("/api/deadlines/nonexistent-id/", {"title": "X"}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
def test_custom_event_detail_delete_removes_event(isolated_courses_dir, api_client):
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "X", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    response = api_client.delete(f"/api/deadlines/{event_id}/")

    assert response.status_code == 204
    assert api_client.get("/api/deadlines/").data == []


@pytest.mark.django_db
def test_custom_event_detail_delete_404_when_not_found(isolated_courses_dir, api_client):
    response = api_client.delete("/api/deadlines/nonexistent-id/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_custom_event_calendar_sync_creates_event(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import MagicMock, patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    create_response = client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-abc"}
    with patch("agent.services.custom_events.calendar_sync.build", return_value=mock_service):
        response = client.post(f"/api/deadlines/{event_id}/calendar-sync/")

    assert response.status_code == 201
    assert response.data == {"google_event_id": "evt-abc"}


@pytest.mark.django_db
def test_custom_event_calendar_sync_409_when_already_synced(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection
    from agent.services import calendar_sync

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    create_response = client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    with patch(
        "agent.services.custom_events.sync_event_to_calendar",
        side_effect=calendar_sync.AlreadySyncedError("already synced"),
    ):
        response = client.post(f"/api/deadlines/{event_id}/calendar-sync/")

    assert response.status_code == 409


@pytest.mark.django_db
def test_custom_event_calendar_sync_404_when_event_not_found(isolated_courses_dir, api_client):
    response = api_client.post("/api/deadlines/nonexistent-id/calendar-sync/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_custom_event_calendar_sync_returns_502_when_google_auth_fails(isolated_courses_dir):
    # Mirrors test_calendar_sync_returns_502_when_google_auth_fails for the
    # old per-course calendar-sync endpoint: an expired token whose refresh
    # is rejected by Google should surface as a clean 502, not a raw 500.
    from datetime import timedelta
    from unittest.mock import patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleCalendarConnection

    user = User.objects.create_user(username="sub-123")
    GoogleCalendarConnection.objects.create(
        user=user,
        access_token="stale-token", refresh_token="revoked-refresh-token",
        token_expiry=timezone.now() - timedelta(hours=1),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    create_response = client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Study group", "type": "other"},
        format="json",
    )
    event_id = create_response.data["id"]

    def _fake_refresh_failure(self, request):
        from google.auth.exceptions import RefreshError
        raise RefreshError("invalid_grant")

    with patch("google.oauth2.credentials.Credentials.refresh", _fake_refresh_failure):
        response = client.post(f"/api/deadlines/{event_id}/calendar-sync/")

    assert response.status_code == 502


@pytest.mark.django_db
def test_deadlines_get_degrades_on_corrupt_custom_events_json(isolated_courses_dir, api_client):
    # custom_events.json corruption shouldn't take down the whole endpoint —
    # reminders.list_all_deadlines() isolates it to an empty custom-events
    # list, same "isolate the corruption" philosophy already used for a
    # corrupt calendar_sync.json.
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=60)).isoformat()
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test",
        "dates": [{"date": far_date, "title": "Final Exam", "type": "exam"}],
        "grading": [], "topics": [],
    }, api_client.user)
    (isolated_courses_dir / "custom_events.json").write_text("{not valid json", encoding="utf-8")

    response = api_client.get("/api/deadlines/")

    assert response.status_code == 200
    assert any(d["title"] == "Final Exam" for d in response.data)


@pytest.mark.django_db
def test_deadlines_post_ignores_legacy_corrupt_custom_events_json(isolated_courses_dir, api_client):
    # Custom events are now stored in SQLite; a stale/corrupt legacy JSON
    # file should not block creating a new DB-backed event.
    (isolated_courses_dir / "custom_events.json").write_text("{not valid json", encoding="utf-8")

    response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "X", "type": "other"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["title"] == "X"


def test_grade_projection_rejects_zero_max_points(isolated_courses_dir, api_client):
    # max_points=0 must be rejected here the same way the real grades-write
    # path already rejects it (serializers.py's min_value=0.01) — otherwise
    # it reaches grades._category_pcts's score / max_points unguarded and
    # raises ZeroDivisionError as a raw 500.
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    }, api_client.user)

    response = api_client.get("/api/courses/cs101/grades/project/?component=Homework&score=90&max_points=0")

    assert response.status_code == 400


def test_course_header_isolates_corrupt_syllabus_as_controlled_error(isolated_courses_dir, api_client):
    # A corrupt syllabus.json must not 500 the course workspace header with
    # an unhandled exception/raw traceback — same isolation intent as
    # build_courses_page's per-course warning, translated to a single-course
    # endpoint as a controlled error response instead of an uncaught crash.
    course_dir = isolated_courses_dir / str(api_client.user.pk) / "cs101"
    course_dir.mkdir(parents=True)
    (course_dir / "syllabus.json").write_text("{bad json", encoding="utf-8")

    response = api_client.get("/api/courses/cs101/header/")

    assert response.status_code == 500
    assert "detail" in response.data
