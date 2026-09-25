import uuid

import pytest

from agent.models import CourseMaterial
from agent.services import citations, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="citation-images-owner")


def _seed_course_with_chunk(user, course_id="cs101", *, image_ids=None):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "Computer Science", "dates": [], "grading": [], "topics": ["Recursion"],
    }, user)
    chunk = {"id": "recursion-base", "topic": "Recursion", "text": "A base case stops recursive calls."}
    if image_ids is not None:
        chunk["image_ids"] = image_ids
    storage.write_notes(course_id, "lecture-01", {
        "lecture_id": "lecture-01", "source": "notes", "date": "2026-08-25",
        "topics": ["Recursion"], "chunks": [chunk],
    }, user)
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="recursion-notes.txt",
        material_type=CourseMaterial.TYPE_NOTES, source_key="lecture-01",
        storage_key=f"{uuid.uuid4().hex}.txt", size_bytes=100,
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
    )


@pytest.mark.django_db
def test_citation_for_chunk_omits_images_key_when_chunk_has_no_image_ids(isolated_courses_dir, owner):
    _seed_course_with_chunk(owner)

    citation = citations.citation_for_chunk(owner, "cs101", "lecture-01", "recursion-base")

    assert "images" not in citation


@pytest.mark.django_db
def test_citation_for_chunk_surfaces_real_images_from_disk(isolated_courses_dir, owner):
    _seed_course_with_chunk(owner, image_ids=["p001-01"])
    expected_path = storage.write_lecture_image("cs101", "lecture-01", "p001-01", b"fake-png", owner)

    citation = citations.citation_for_chunk(owner, "cs101", "lecture-01", "recursion-base")

    assert citation["images"] == [{"image_id": "p001-01", "path": str(expected_path)}]


@pytest.mark.django_db
def test_citation_for_chunk_never_claims_an_image_id_missing_from_disk(isolated_courses_dir, owner):
    """A chunk can reference an image_id whose PNG was later deleted (or the
    manifest edited out of band) — never surface a path that doesn't exist."""
    _seed_course_with_chunk(owner, image_ids=["p001-01", "p002-01"])
    storage.write_lecture_image("cs101", "lecture-01", "p001-01", b"fake-png", owner)
    # p002-01 is referenced on the chunk but was never actually written to disk.

    citation = citations.citation_for_chunk(owner, "cs101", "lecture-01", "recursion-base")

    assert [image["image_id"] for image in citation["images"]] == ["p001-01"]


@pytest.mark.django_db
def test_notes_citation_via_resolve_citations_surfaces_chunk_images(isolated_courses_dir, owner):
    _seed_course_with_chunk(owner, image_ids=["p001-01"])
    storage.write_lecture_image("cs101", "lecture-01", "p001-01", b"fake-png", owner)

    resolved = citations.resolve_citations(
        owner, "cs101", ["lecture-01"], "What stops recursion?", "The base case.",
    )[0]

    assert resolved["images"] == [{"image_id": "p001-01", "path": str(
        storage.lecture_image_path("cs101", "lecture-01", "p001-01", owner)
    )}]


@pytest.mark.django_db
def test_preview_source_recomputes_images_for_the_requested_chunk(isolated_courses_dir, owner):
    """preview_source re-looks-up the chunk by chunk_id rather than trusting
    client-supplied image data — a stale/forged 'images' field in the
    client's citation payload must not leak through unexamined."""
    _seed_course_with_chunk(owner, image_ids=["p001-01"])
    storage.write_lecture_image("cs101", "lecture-01", "p001-01", b"fake-png", owner)
    material = CourseMaterial.objects.get(user=owner, course_id="cs101", source_key="lecture-01")

    forged = {
        "material_id": str(material.material_id),
        "material_type": "notes",
        "lecture_id": "lecture-01",
        "chunk_id": "recursion-base",
        "images": [{"image_id": "not-a-real-image", "path": "/etc/passwd"}],
    }

    resolved = citations.preview_source(owner, "cs101", forged)

    assert resolved["images"] == [{"image_id": "p001-01", "path": str(
        storage.lecture_image_path("cs101", "lecture-01", "p001-01", owner)
    )}]


@pytest.mark.django_db
def test_preview_source_omits_images_key_when_requested_chunk_has_none(isolated_courses_dir, owner):
    _seed_course_with_chunk(owner)
    material = CourseMaterial.objects.get(user=owner, course_id="cs101", source_key="lecture-01")

    citation = {
        "material_id": str(material.material_id), "material_type": "notes",
        "lecture_id": "lecture-01", "chunk_id": "recursion-base",
    }

    resolved = citations.preview_source(owner, "cs101", citation)

    assert "images" not in resolved
