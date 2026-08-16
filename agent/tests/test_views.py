import io

import pytest
from rest_framework.test import APIClient

from agent.services import storage


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
