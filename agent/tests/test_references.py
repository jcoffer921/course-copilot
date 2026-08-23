import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_references_empty_for_new_course(isolated_courses_dir):
    assert storage.read_references("cs101") == []


def test_read_reference_none_when_missing(isolated_courses_dir):
    assert storage.read_reference("cs101", "ch1") is None


def test_write_then_read_reference_roundtrip(isolated_courses_dir):
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data)

    assert storage.read_reference("cs101", "ch1") == data
    assert storage.read_references("cs101") == [data]


def test_write_reference_raises_on_existing_without_overwrite(isolated_courses_dir):
    data = {"reference_id": "ch1", "title": "Chapter 1", "source_filename": "ch1.pdf", "text": "hello"}
    storage.write_reference("cs101", "ch1", data)

    with pytest.raises(FileExistsError):
        storage.write_reference("cs101", "ch1", data)


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


def test_invalid_reference_id_rejected(isolated_courses_dir):
    with pytest.raises(storage.InvalidReferenceIdError):
        storage.write_reference("cs101", "../escape", {
            "reference_id": "ch1", "title": "x", "source_filename": "x.pdf", "text": "x",
        })


from agent.services import references


async def test_ingest_reference_extracts_txt_and_generates_id(isolated_courses_dir):
    data = await references.ingest_reference(
        "cs101", b"Some textbook content about recursion.", "chapter1.txt", title="Chapter 1: Recursion",
    )

    assert data["reference_id"] == "chapter-1-recursion"
    assert data["title"] == "Chapter 1: Recursion"
    assert data["source_filename"] == "chapter1.txt"
    assert data["text"] == "Some textbook content about recursion."


async def test_ingest_reference_defaults_title_to_filename_stem(isolated_courses_dir):
    data = await references.ingest_reference("cs101", b"content", "notes.md")

    assert data["title"] == "notes"
    assert data["reference_id"] == "notes"


async def test_ingest_reference_dedupes_id_on_collision(isolated_courses_dir):
    storage.write_reference("cs101", "notes", {
        "reference_id": "notes", "title": "notes", "source_filename": "notes.md", "text": "existing",
    })

    data = await references.ingest_reference("cs101", b"content", "notes.md")

    assert data["reference_id"] == "notes-2"


async def test_ingest_reference_rejects_unsupported_file_type(isolated_courses_dir):
    with pytest.raises(ValueError):
        await references.ingest_reference("cs101", b"content", "slides.pptx")


async def test_ingest_reference_truncates_long_title_to_fit_within_64_char_limit(isolated_courses_dir):
    """Verify that a title longer than 64 chars doesn't crash due to InvalidReferenceIdError
    and produces a reference_id within the 64-char storage limit."""
    long_title = "Chapter 12: Advanced Recursion, Memoization and Dynamic Programming with real examples"
    data = await references.ingest_reference("cs101", b"content", "chapter12.txt", title=long_title)

    assert len(data["reference_id"]) <= 64
    assert data["title"] == long_title
