import pytest
from asgiref.sync import sync_to_async

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_read_references_empty_for_new_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="refs-empty", email="refs-empty@example.com")
    assert storage.read_references("cs101", user) == []


@pytest.mark.django_db
def test_read_reference_none_when_missing(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="refs-missing", email="refs-missing@example.com")
    assert storage.read_reference("cs101", "ch1", user) is None


@pytest.mark.django_db
def test_write_then_read_reference_roundtrip(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="refs-roundtrip", email="refs-roundtrip@example.com")
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data, user)

    assert storage.read_reference("cs101", "ch1", user) == data
    assert storage.read_references("cs101", user) == [data]


@pytest.mark.django_db
def test_write_reference_raises_on_existing_without_overwrite(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="refs-existing", email="refs-existing@example.com")
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data, user)

    with pytest.raises(FileExistsError):
        storage.write_reference("cs101", "ch1", data, user)


def test_validate_reference_rejects_empty_text():
    errors = storage.validate_reference({
        "reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "   ",
    })

    assert any("text" in e for e in errors)


def test_validate_reference_rejects_missing_field():
    errors = storage.validate_reference({"reference_id": "ch1", "title": "Chapter 1"})

    assert any("source_filename" in e for e in errors)
    assert any("text" in e for e in errors)


def test_validate_reference_accepts_valid_data():
    errors = storage.validate_reference({
        "reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello",
    })

    assert errors == []


@pytest.mark.django_db
def test_invalid_reference_id_rejected(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="refs-invalid-id", email="refs-invalid-id@example.com")
    with pytest.raises(storage.InvalidReferenceIdError):
        storage.write_reference("cs101", "../escape", {
            "reference_id": "ch1", "title": "x", "source_filename": "x.pdf", "text": "x",
        }, user)


from agent.services import references


@pytest.mark.django_db
async def test_ingest_reference_extracts_txt_and_generates_id(isolated_courses_dir, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="refs-ingest-1", email="refs-ingest-1@example.com",
    )
    data = await references.ingest_reference(
        "cs101", b"Some textbook content about recursion.", "chapter1.txt", user, title="Chapter 1: Recursion",
    )

    assert data["reference_id"] == "chapter-1-recursion"
    assert data["title"] == "Chapter 1: Recursion"
    assert data["source_filename"] == "chapter1.txt"
    assert data["text"] == "Some textbook content about recursion."


@pytest.mark.django_db
async def test_ingest_reference_defaults_title_to_filename_stem(isolated_courses_dir, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="refs-ingest-2", email="refs-ingest-2@example.com",
    )
    data = await references.ingest_reference("cs101", b"content", "notes.md", user)

    assert data["title"] == "notes"
    assert data["reference_id"] == "notes"


@pytest.mark.django_db
async def test_ingest_reference_dedupes_id_on_collision(isolated_courses_dir, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="refs-ingest-3", email="refs-ingest-3@example.com",
    )
    await sync_to_async(storage.write_reference)("cs101", "notes", {
        "reference_id": "notes", "title": "notes", "source_filename": "notes.md", "text": "existing",
    }, user)

    data = await references.ingest_reference("cs101", b"content", "notes.md", user)

    assert data["reference_id"] == "notes-2"


@pytest.mark.django_db
async def test_ingest_reference_rejects_unsupported_file_type(isolated_courses_dir, django_user_model):
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="refs-ingest-4", email="refs-ingest-4@example.com",
    )
    with pytest.raises(ValueError):
        await references.ingest_reference("cs101", b"content", "slides.pptx", user)


@pytest.mark.django_db
async def test_ingest_reference_truncates_long_title_to_fit_within_64_char_limit(isolated_courses_dir, django_user_model):
    """Verify that a title longer than 64 chars doesn't crash due to InvalidReferenceIdError
    and produces a reference_id within the 64-char storage limit."""
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="refs-ingest-5", email="refs-ingest-5@example.com",
    )
    long_title = "Chapter 12: Advanced Recursion, Memoization and Dynamic Programming with real examples"
    data = await references.ingest_reference("cs101", b"content", "chapter12.txt", user, title=long_title)

    assert len(data["reference_id"]) <= 64
    assert data["title"] == long_title
