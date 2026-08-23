import io
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from agent.models import CalendarSyncRecord, CourseSession, FlashcardProgress, GradeItem, MasteryScore, QuizAttempt
from agent import views
from agent.services import ask, storage


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


def _seed_syllabus(course_id):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    })


def test_profile_get_uses_display_name_and_settings(api_client):
    api_client.user.first_name = "Jordan Lee"
    api_client.user.email = "jordan@example.com"
    api_client.user.save()

    response = api_client.get("/api/profile/")

    assert response.status_code == 200
    assert response.data["display_name"] == "Jordan Lee"
    assert response.data["email"] == "jordan@example.com"
    assert response.data["notifications_enabled"] is False


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


def test_profile_patch_rejects_duplicate_username(api_client, django_user_model):
    django_user_model.objects.create_user(username="taken")

    response = api_client.patch("/api/profile/", {"username": "taken"}, format="json")

    assert response.status_code == 409


def test_references_post_then_get(isolated_courses_dir, api_client):
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


def test_references_post_rejects_unsupported_file_type(isolated_courses_dir, api_client):
    upload = io.BytesIO(b"binary junk")
    upload.name = "slides.pptx"

    response = api_client.post("/api/courses/cs101/references/", {"file": upload}, format="multipart")

    assert response.status_code == 400


def test_domains_get_empty_before_approval(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/domains/")

    assert response.status_code == 200
    assert response.data == {"domains": []}


def test_domains_put_replaces_approved_list(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["docs.python.org"]}, format="json",
    )

    assert response.status_code == 200
    assert storage.read_trusted_domains("cs101") == ["docs.python.org"]


def test_domains_put_rejects_empty_domain_string(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/domains/", {"domains": ["good.com", ""]}, format="json",
    )

    assert response.status_code == 422


def test_domain_suggestions_view_never_writes(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101")

    async def fake_suggest_domains(course_id):
        return ["docs.python.org", "nist.gov"]

    monkeypatch.setattr(views.domain_suggestions, "suggest_domains", fake_suggest_domains)

    response = api_client.post("/api/courses/cs101/domains/suggest/")

    assert response.status_code == 200
    assert response.data == {"suggested": ["docs.python.org", "nist.gov"]}
    assert storage.read_trusted_domains("cs101") == []


def test_domain_suggestions_view_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/nocourse/domains/suggest/")

    assert response.status_code == 404


def test_flashcards_generate_annotates_saved_progress(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101")

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


def test_quiz_history_rejects_malformed_limit(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/quiz/history/?limit=abc")

    assert response.status_code == 400
    assert response.data == {"detail": "limit must be an integer"}


def test_reminders_rejects_malformed_within_days(api_client):
    response = api_client.get("/api/reminders/?within_days=soon")

    assert response.status_code == 400
    assert response.data == {"detail": "within_days must be an integer"}


def test_flashcard_progress_patch_and_reset(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

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
    assert storage.read_flashcard_progress("cs101", user=api_client.user)["cards"] == {}


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
    _seed_syllabus("cs101")

    response = api_client.patch(
        "/api/courses/cs101/flashcards/progress/",
        {"term": "Closure", "definition": "Captured state.", "status": "done", "starred": False},
        format="json",
    )

    assert response.status_code == 400


def test_deadline_post_accepts_duration_completion_and_legacy_category(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

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
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["type"] == "test_quiz"
    assert response.data["end_time"] == "10:30"
    assert response.data["completed"] is True


def test_deadline_post_rejects_bad_duration_and_category(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

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
    _seed_syllabus("cs101")
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


def test_create_course_draft_returns_201(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/courses/newclass/", {"course_name": "New Class"}, format="json",
    )

    assert response.status_code == 201
    assert response.data == {"course_id": "newclass", "course_name": "New Class"}
    assert (isolated_courses_dir / "newclass" / "course.json").exists()


def test_create_course_draft_rejects_blank_name(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/newclass/", {"course_name": ""}, format="json")

    assert response.status_code == 400


def test_create_course_draft_conflicts_with_existing_draft(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    assert response.status_code == 409


def test_create_course_draft_conflicts_with_existing_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.post("/api/courses/cs101/", {"course_name": "Intro to CS"}, format="json")

    assert response.status_code == 409


def test_rename_draft_course(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.patch("/api/courses/newclass/", {"course_name": "Renamed Class"}, format="json")

    assert response.status_code == 200
    assert response.data == {"course_id": "newclass", "course_name": "Renamed Class"}
    assert storage.read_syllabus("newclass") is None  # still a draft, not promoted


def test_rename_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.patch("/api/courses/cs101/", {"course_name": "Renamed"}, format="json")

    assert response.status_code == 200
    assert storage.read_syllabus("cs101")["course_name"] == "Renamed"


def test_rename_nonexistent_course_404s(isolated_courses_dir, api_client):
    response = api_client.patch("/api/courses/nocourse/", {"course_name": "X"}, format="json")

    assert response.status_code == 404


def test_delete_draft_course(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.delete("/api/courses/newclass/")

    assert response.status_code == 204
    assert not (isolated_courses_dir / "newclass").exists()


def test_delete_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.delete("/api/courses/cs101/")

    assert response.status_code == 204
    assert not (isolated_courses_dir / "cs101").exists()


def test_delete_nonexistent_course_404s(isolated_courses_dir, api_client):
    response = api_client.delete("/api/courses/nocourse/")

    assert response.status_code == 404


def test_delete_course_also_removes_its_custom_events(isolated_courses_dir, api_client):
    from agent.services import custom_events

    _seed_syllabus("cs101")
    _seed_syllabus("cs102")
    custom_events.create_event("cs101", "2026-09-01", None, "Delete me", "other")
    custom_events.create_event("cs102", "2026-09-01", None, "Keep me (other course)", "other")
    custom_events.create_event(None, "2026-09-01", None, "Keep me (general)", "other")

    response = api_client.delete("/api/courses/cs101/")

    assert response.status_code == 204
    remaining_titles = {e["title"] for e in custom_events.list_events()}
    assert remaining_titles == {"Keep me (other course)", "Keep me (general)"}


def test_delete_course_removes_db_backed_course_state(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")
    _seed_syllabus("cs102")
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

    response = api_client.delete("/api/courses/cs101/")

    assert response.status_code == 204
    assert FlashcardProgress.objects.filter(course_id="cs101").count() == 0
    assert GradeItem.objects.filter(course_id="cs101").count() == 0
    assert CalendarSyncRecord.objects.filter(course_id="cs101").count() == 0
    assert QuizAttempt.objects.filter(course_id="cs101").count() == 0
    assert MasteryScore.objects.filter(course_id="cs101").count() == 0
    assert CourseSession.objects.filter(course_id="cs101").count() == 0
    assert GradeItem.objects.filter(course_id="cs102").count() == 1


class _NeverCalledMessages:
    async def create(self, **kwargs):
        raise AssertionError(
            "API client should not be reached — corrupt reference file must fail first"
        )


class _NeverCalledClient:
    def __init__(self):
        self.messages = _NeverCalledMessages()


def test_ask_returns_500_not_crash_on_corrupt_reference_file(isolated_courses_dir, api_client, monkeypatch):
    _seed_syllabus("cs101")

    # get_client() is called before storage.read_references() inside
    # ask_async, so it must be mocked so construction succeeds — but its
    # messages.create() must never actually be reached, since the
    # corrupt-file error should raise before any network call happens.
    monkeypatch.setattr(ask, "get_client", lambda: _NeverCalledClient())

    references_dir = isolated_courses_dir / "cs101" / "references"
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
    })

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["grading"] == [{"component": "Homework", "weight_pct": 100}]
    assert response.data["grade_scale"]["passing_pct"] == 60


def test_grading_config_get_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grading/")
    assert response.status_code == 404


def test_grading_config_put_updates_categories(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 5}]},
        format="json",
    )

    assert response.status_code == 200
    updated = storage.read_syllabus("cs101")
    assert updated["grading"] == [{"component": "Homework", "weight_pct": 100, "total_items": 5, "drop_lowest": None}]


def test_grading_config_put_rejects_invalid_total_items(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 0}]},
        format="json",
    )

    assert response.status_code == 422


def test_grading_config_put_accepts_non_summing_weights_with_warning(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

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
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
    ]})

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
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["category_choices"] == storage.GRADING_CATEGORY_CHOICES


def test_grades_get_returns_items_and_breakdown(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
    ]})

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
    })

    response = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["component"] == "Homework"
    assert len(storage.read_grades("cs101")["items"]) == 1


def test_grade_items_post_422s_for_unknown_component(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })

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
    })
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
    })
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
    })

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")

    assert response.status_code == 200
    assert "grade_needed" in response.data
    assert "missable_by_category" in response.data


def test_grades_whatif_400s_for_non_numeric_target(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=notanumber")

    assert response.status_code == 400


def test_grades_whatif_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")
    assert response.status_code == 404


def test_grades_summary_returns_rollup(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 88, "max_points": 100},
    ]})

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


def test_anonymous_request_to_ontrack_page_redirects_to_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.django_db
def test_calendar_sync_creates_event(isolated_courses_dir):
    from datetime import timedelta
    from unittest.mock import MagicMock, patch

    from django.contrib.auth.models import User
    from django.utils import timezone
    from rest_framework.test import APIClient

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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

    from agent.models import GoogleAccount
    from agent.services import storage

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
        access_token="valid-token", refresh_token="refresh-token",
        token_expiry=timezone.now() + timedelta(hours=1),
    )
    storage.append_calendar_sync_record("cs101", {
        "date": "2026-09-01", "title": "Midterm", "type": "exam",
        "google_event_id": "evt-1", "synced_at": "2026-08-20T00:00:00+00:00",
    })
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

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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

    custom_events.create_event("cs101", "2099-01-01", None, "Future thing", "other")

    response = api_client.get("/api/deadlines/")

    assert response.status_code == 200
    assert any(d["title"] == "Future thing" for d in response.data)


@pytest.mark.django_db
def test_deadlines_get_can_filter_by_course_id(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS", "dates": [{"date": "2099-01-01", "title": "CS Final", "type": "exam"}],
        "grading": [], "topics": [],
    })
    storage.write_syllabus("math201", {
        "course_id": "math201", "course_name": "Math", "dates": [{"date": "2099-01-01", "title": "Math Final", "type": "exam"}],
        "grading": [], "topics": [],
    })

    response = api_client.get("/api/deadlines/?course_id=cs101")

    assert response.status_code == 200
    assert [d["title"] for d in response.data] == ["CS Final"]


@pytest.mark.django_db
def test_deadlines_get_for_draft_course_returns_empty_list(isolated_courses_dir, api_client):
    storage.write_course_draft("draft101", "Draft Class")

    response = api_client.get("/api/deadlines/?course_id=draft101")

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_deadlines_post_replacement_hides_syllabus_deadline(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS", "dates": [{"date": "2099-01-01", "title": "Project Due", "type": "assignment"}],
        "grading": [], "topics": [],
    })
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
    assert deadlines[0]["source"] == "custom"


@pytest.mark.django_db
def test_deadlines_post_creates_custom_event(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

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
    _seed_syllabus("cs101")

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
    _seed_syllabus("cs101")

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
    create_response = api_client.post(
        "/api/deadlines/",
        {"date": "2026-09-01", "title": "Study group", "type": "other"},
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

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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

    from agent.models import GoogleAccount
    from agent.services import calendar_sync

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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

    from agent.models import GoogleAccount

    user = User.objects.create_user(username="sub-123")
    GoogleAccount.objects.create(
        user=user, google_sub="sub-123", email="jordan@example.com",
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
    })
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
