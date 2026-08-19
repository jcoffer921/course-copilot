import io

import pytest
from rest_framework.test import APIClient

from agent import views
from agent.services import ask, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def api_client():
    return APIClient()


def _seed_syllabus(course_id):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Test", "dates": [], "grading": [], "topics": ["A"],
    })


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


def test_grading_config_put_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.put(
        "/api/courses/cs101/grading/", {"grading": []}, format="json",
    )
    assert response.status_code == 404


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
