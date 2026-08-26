import io

import pytest
from rest_framework.test import APIClient

from agent.models import CourseMaterial, GradeItem
from agent.services import materials, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def api_client(django_user_model):
    user = django_user_model.objects.create_user(username="material-api-user")
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


def text_upload(name="syllabus.txt", content=b"Course syllabus"):
    value = io.BytesIO(content)
    value.name = name
    return value


def syllabus(course_id="cs101", name="Extracted CS", topics=None):
    return {
        "course_id": course_id,
        "course_name": name,
        "dates": [{"date": "2026-10-10", "title": "Midterm", "type": "test_quiz"}],
        "grading": [{"component": "Tests", "weight_pct": 50}],
        "topics": topics if topics is not None else ["Recursion", "Sorting"],
    }


@pytest.mark.django_db
def test_syllabus_upload_is_staged_until_review_confirmation(isolated_courses_dir, api_client, monkeypatch):
    storage.write_syllabus("cs101", syllabus(name="Current trusted syllabus", topics=["Current"]), api_client.user)

    async def fake_extract(*_args, **_kwargs):
        return syllabus()

    monkeypatch.setattr(materials, "extract_syllabus_async", fake_extract)
    staged = api_client.post(
        "/api/courses/cs101/syllabus/extract/",
        {"file": text_upload()},
        format="multipart",
    )

    assert staged.status_code == 201
    assert staged.data["material"]["processing_status"] == "needs_review"
    assert staged.data["material"]["candidate"]["topics"] == ["Recursion", "Sorting"]
    assert storage.read_syllabus("cs101", api_client.user)["course_name"] == "Current trusted syllabus"

    material_id = staged.data["material"]["material_id"]
    reviewed = syllabus(name="Reviewed by student", topics=["Recursion"])
    confirmed = api_client.post(
        f"/api/courses/cs101/materials/{material_id}/confirm/",
        {"confirm": True, "syllabus": reviewed},
        format="json",
    )

    assert confirmed.status_code == 200
    assert confirmed.data["material"]["processing_status"] == "ready"
    assert confirmed.data["material"]["review_status"] == "confirmed"
    assert storage.read_syllabus("cs101", api_client.user)["course_name"] == "Reviewed by student"
    assert storage.read_syllabus("cs101", api_client.user)["topics"] == ["Recursion"]

    repeated = api_client.post(
        f"/api/courses/cs101/materials/{material_id}/confirm/",
        {"confirm": True, "syllabus": reviewed},
        format="json",
    )
    assert repeated.status_code == 200
    assert CourseMaterial.objects.filter(user=api_client.user, course_id="cs101").count() == 1


@pytest.mark.django_db
def test_discarding_pending_syllabus_preserves_confirmed_version(isolated_courses_dir, api_client):
    current = syllabus(name="Current trusted syllabus", topics=["Current"])
    storage.write_syllabus("cs101", current, api_client.user)
    pending = CourseMaterial.objects.create(
        user=api_client.user,
        course_id="cs101",
        original_filename="replacement.txt",
        material_type="syllabus",
        storage_key="d" * 32 + ".txt",
        size_bytes=5,
        processing_status="needs_review",
        review_status="pending",
        extracted_data=syllabus(name="Unconfirmed replacement"),
    )

    response = api_client.delete(
        f"/api/courses/cs101/materials/{pending.material_id}/",
        {"confirmation": "DELETE"},
        format="json",
    )

    assert response.status_code == 204
    assert storage.read_syllabus("cs101", api_client.user) == current
    assert not CourseMaterial.objects.filter(pk=pending.pk).exists()


@pytest.mark.django_db
def test_failed_syllabus_processing_preserves_confirmed_version(isolated_courses_dir, api_client, monkeypatch):
    current = syllabus(name="Keep this")
    storage.write_syllabus("cs101", current, api_client.user)

    async def fail_extract(*_args, **_kwargs):
        raise ValueError("model returned private raw failure")

    monkeypatch.setattr(materials, "extract_syllabus_async", fail_extract)
    response = api_client.post(
        "/api/courses/cs101/syllabus/extract/",
        {"file": text_upload()},
        format="multipart",
    )

    assert response.status_code == 422
    assert response.data["code"] == "extraction_failed"
    assert "private raw failure" not in response.data["detail"]
    assert storage.read_syllabus("cs101", api_client.user) == current
    assert CourseMaterial.objects.get(user=api_client.user).processing_status == "failed"


@pytest.mark.django_db
def test_material_status_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    storage.write_course_draft("cs101", "CS 101", api_client.user)
    other = django_user_model.objects.create_user(username="other-material-user")
    storage.write_course_draft("cs101", "Other CS 101", other)
    material = CourseMaterial.objects.create(
        user=other,
        course_id="cs101",
        original_filename="private.txt",
        material_type="notes",
        storage_key="a" * 32 + ".txt",
        size_bytes=5,
    )

    response = api_client.get(f"/api/courses/cs101/materials/{material.material_id}/")

    assert response.status_code == 404
    assert "private.txt" not in str(response.data)


@pytest.mark.django_db
def test_notes_failure_does_not_replace_existing_lecture(isolated_courses_dir, api_client, monkeypatch):
    storage.write_syllabus("cs101", syllabus(), api_client.user)
    existing = {
        "lecture_id": "lecture-01", "source": "notes", "date": None,
        "topics": ["Current"], "chunks": [{"id": "c1", "topic": "Current", "text": "Keep me"}],
    }
    storage.write_notes("cs101", "lecture-01", existing, api_client.user)

    async def fail_chunk(*_args, **_kwargs):
        raise ValueError("bad model output")

    monkeypatch.setattr(materials.chunk_notes, "chunk_notes_async", fail_chunk)
    response = api_client.post(
        "/api/courses/cs101/notes/chunk/",
        {"file": text_upload("lecture.txt", b"replacement"), "lecture_id": "lecture-01", "overwrite": True},
        format="multipart",
    )

    assert response.status_code == 422
    assert storage.read_lecture("cs101", "lecture-01", api_client.user) == existing


@pytest.mark.django_db
def test_notes_upload_reaches_ready_status(isolated_courses_dir, api_client, monkeypatch):
    storage.write_syllabus("cs101", syllabus(), api_client.user)

    async def fake_chunk(_course_id, lecture_id, _text, _source, lecture_date, **_kwargs):
        return {
            "lecture_id": lecture_id,
            "source": "notes",
            "date": lecture_date,
            "topics": ["Recursion"],
            "chunks": [{"id": "chunk-1", "topic": "Recursion", "text": "A base case stops recursion."}],
        }

    monkeypatch.setattr(materials.chunk_notes, "chunk_notes_async", fake_chunk)
    response = api_client.post(
        "/api/courses/cs101/notes/chunk/",
        {"file": text_upload("lecture.txt", b"A base case stops recursion."), "lecture_id": "lecture-02", "date": "2026-09-03"},
        format="multipart",
    )

    assert response.status_code == 201
    assert response.data["material"]["processing_status"] == "ready"
    assert response.data["material"]["source_date"] == "2026-09-03"
    assert storage.read_lecture("cs101", "lecture-02", api_client.user)["chunks"][0]["topic"] == "Recursion"


@pytest.mark.django_db
def test_replaced_lecture_is_superseded_and_old_upload_delete_keeps_current_source(isolated_courses_dir, api_client, monkeypatch):
    storage.write_syllabus("cs101", syllabus(), api_client.user)
    call_count = 0

    async def fake_chunk(_course_id, lecture_id, _text, _source, lecture_date, **_kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "lecture_id": lecture_id,
            "source": "notes",
            "date": lecture_date,
            "topics": ["Recursion"],
            "chunks": [{"id": f"chunk-{call_count}", "topic": "Recursion", "text": f"Version {call_count}"}],
        }

    monkeypatch.setattr(materials.chunk_notes, "chunk_notes_async", fake_chunk)
    first = api_client.post(
        "/api/courses/cs101/notes/chunk/",
        {"file": text_upload("first.txt", b"first"), "lecture_id": "lecture-03"},
        format="multipart",
    )
    second = api_client.post(
        "/api/courses/cs101/notes/chunk/",
        {"file": text_upload("second.txt", b"second"), "lecture_id": "lecture-03", "overwrite": True},
        format="multipart",
    )

    assert first.status_code == second.status_code == 201
    old = CourseMaterial.objects.get(material_id=first.data["material"]["material_id"])
    assert old.review_status == "superseded"
    deleted = api_client.delete(
        f"/api/courses/cs101/materials/{old.material_id}/",
        {"confirmation": "DELETE"},
        format="json",
    )
    assert deleted.status_code == 204
    assert storage.read_lecture("cs101", "lecture-03", api_client.user)["chunks"][0]["text"] == "Version 2"


@pytest.mark.django_db
def test_material_delete_requires_exact_confirmation(isolated_courses_dir, api_client):
    storage.write_course_draft("cs101", "CS 101", api_client.user)
    key = "b" * 32 + ".txt"
    material = CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="source.txt",
        material_type="notes", storage_key=key, size_bytes=6,
    )

    rejected = api_client.delete(
        f"/api/courses/cs101/materials/{material.material_id}/",
        {"confirmation": "delete"}, format="json",
    )

    assert rejected.status_code == 400
    assert CourseMaterial.objects.filter(pk=material.pk).exists()


@pytest.mark.django_db
def test_retry_reprocesses_failed_syllabus_material_in_place(isolated_courses_dir, api_client, monkeypatch):
    storage.write_course_draft("cs101", "CS 101", api_client.user)

    async def fail_extract(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(materials, "extract_syllabus_async", fail_extract)
    staged = api_client.post(
        "/api/courses/cs101/syllabus/extract/",
        {"file": text_upload()},
        format="multipart",
    )
    assert staged.status_code == 422
    material_id = staged.data["material"]["material_id"]
    assert CourseMaterial.objects.get(material_id=material_id).processing_status == "failed"

    async def succeed_extract(*_args, **_kwargs):
        return syllabus()

    monkeypatch.setattr(materials, "extract_syllabus_async", succeed_extract)
    retried = api_client.post(f"/api/courses/cs101/materials/{material_id}/retry/")

    assert retried.status_code == 200
    assert retried.data["material"]["material_id"] == material_id
    assert retried.data["material"]["processing_status"] == "needs_review"
    assert CourseMaterial.objects.filter(user=api_client.user, course_id="cs101").count() == 1


@pytest.mark.django_db
def test_retry_rejects_non_failed_material(isolated_courses_dir, api_client, monkeypatch):
    storage.write_course_draft("cs101", "CS 101", api_client.user)

    async def fake_extract(*_args, **_kwargs):
        return syllabus()

    monkeypatch.setattr(materials, "extract_syllabus_async", fake_extract)
    staged = api_client.post(
        "/api/courses/cs101/syllabus/extract/",
        {"file": text_upload()},
        format="multipart",
    )
    material_id = staged.data["material"]["material_id"]

    retried = api_client.post(f"/api/courses/cs101/materials/{material_id}/retry/")

    assert retried.status_code == 409


@pytest.mark.django_db
def test_retry_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    other = django_user_model.objects.create_user(username="other-retry-user")
    storage.write_course_draft("cs101", "Other CS 101", other)
    material = CourseMaterial.objects.create(
        user=other, course_id="cs101", original_filename="private.txt", material_type="notes",
        storage_key="e" * 32 + ".txt", size_bytes=5, processing_status="failed",
    )

    response = api_client.post(f"/api/courses/cs101/materials/{material.material_id}/retry/")

    assert response.status_code == 404
    assert "private.txt" not in str(response.data)


@pytest.mark.django_db
def test_download_returns_original_bytes_with_safe_headers(isolated_courses_dir, api_client):
    storage.write_course_draft("cs101", "CS 101", api_client.user)
    storage_key = materials.material_files.object_storage.save(api_client.user, "cs101", ".txt", b"hello world")
    material = CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="notes.txt", material_type="notes",
        storage_key=storage_key, size_bytes=11, content_type="text/plain",
        processing_status="ready", review_status="not_required",
    )

    response = api_client.get(f"/api/courses/cs101/materials/{material.material_id}/download/")

    assert response.status_code == 200
    assert response.content == b"hello world"
    assert response.headers["Content-Type"] == "text/plain"
    assert "notes.txt" in response.headers["Content-Disposition"]
    assert response.headers["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_download_is_owner_scoped(isolated_courses_dir, api_client, django_user_model):
    other = django_user_model.objects.create_user(username="other-download-user")
    storage.write_course_draft("cs101", "Other CS 101", other)
    material = CourseMaterial.objects.create(
        user=other, course_id="cs101", original_filename="private.txt", material_type="notes",
        storage_key="f" * 32 + ".txt", size_bytes=5, processing_status="ready",
    )

    response = api_client.get(f"/api/courses/cs101/materials/{material.material_id}/download/")

    assert response.status_code == 404
    assert "private.txt" not in str(response.data)


@pytest.mark.django_db
def test_download_rejects_legacy_material_id(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", syllabus(), api_client.user)

    response = api_client.get("/api/courses/cs101/materials/legacy-syllabus/download/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_upload_rejects_when_user_storage_quota_exceeded(isolated_courses_dir, api_client, monkeypatch):
    storage.write_course_draft("cs101", "CS 101", api_client.user)
    monkeypatch.setenv("ONTRACK_MAX_UPLOAD_BYTES_PER_USER", "20")
    CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="already-uploaded.txt",
        material_type="notes", storage_key="g" * 32 + ".txt", size_bytes=15,
    )

    response = api_client.post(
        "/api/courses/cs101/references/",
        {"file": text_upload("reference.txt", b"more than five bytes")},
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["code"] == "storage_quota_exceeded"
    assert CourseMaterial.objects.filter(original_filename="reference.txt").count() == 0


@pytest.mark.django_db
def test_upload_quota_is_per_user_not_shared(isolated_courses_dir, api_client, django_user_model, monkeypatch):
    other = django_user_model.objects.create_user(username="other-quota-user")
    storage.write_course_draft("cs101", "CS 101", api_client.user)
    storage.write_course_draft("cs101", "Other CS 101", other)
    monkeypatch.setenv("ONTRACK_MAX_UPLOAD_BYTES_PER_USER", "1000000")
    CourseMaterial.objects.create(
        user=api_client.user, course_id="cs101", original_filename="owner-file.txt",
        material_type="notes", storage_key="h" * 32 + ".txt", size_bytes=999_000,
    )
    CourseMaterial.objects.create(
        user=other, course_id="cs101", original_filename="other-file.txt",
        material_type="notes", storage_key="i" * 32 + ".txt", size_bytes=999_000,
    )

    other_client = APIClient()
    other_client.force_authenticate(user=other)
    response = other_client.post(
        "/api/courses/cs101/references/",
        {"file": text_upload("second-reference.txt", b"small upload")},
        format="multipart",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_course_delete_removes_owned_materials_and_dependent_state_only(isolated_courses_dir, api_client, django_user_model):
    owner = api_client.user
    other = django_user_model.objects.create_user(username="other-course-owner")
    storage.write_syllabus("cs101", syllabus(), owner)
    storage.write_syllabus("cs101", syllabus(name="Other"), other)
    owned = CourseMaterial.objects.create(
        user=owner, course_id="cs101", original_filename="owned.txt", material_type="notes",
        storage_key="c" * 32 + ".txt", size_bytes=5,
    )
    theirs = CourseMaterial.objects.create(
        user=other, course_id="cs101", original_filename="theirs.txt", material_type="notes",
        storage_key="d" * 32 + ".txt", size_bytes=6,
    )
    GradeItem.objects.create(
        user=owner, course_id="cs101", item_id="hw1", component="Homework",
        title="HW 1", score=9, max_points=10,
    )

    missing_confirmation = api_client.delete("/api/courses/cs101/", {}, format="json")
    deleted = api_client.delete("/api/courses/cs101/", {"confirmation": "cs101"}, format="json")

    assert missing_confirmation.status_code == 400
    assert deleted.status_code == 204
    assert not CourseMaterial.objects.filter(pk=owned.pk).exists()
    assert CourseMaterial.objects.filter(pk=theirs.pk).exists()
    assert not GradeItem.objects.filter(user=owner, course_id="cs101").exists()
    assert storage.read_syllabus("cs101", other)["course_name"] == "Other"
