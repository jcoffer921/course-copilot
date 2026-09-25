import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from agent.services import material_files


def upload(name, content, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def test_prepare_upload_sanitizes_display_name_and_keeps_valid_text():
    prepared = material_files.prepare_upload(upload("../week\n1.txt", b"Grounded notes"))

    assert prepared.display_filename == "week1.txt"
    assert prepared.data == b"Grounded notes"


@pytest.mark.parametrize("name", ["notes.exe", "notes.csv", "notes.html"])
def test_prepare_upload_rejects_unsupported_suffix(name):
    with pytest.raises(material_files.UploadValidationError) as exc:
        material_files.prepare_upload(upload(name, b"content"))

    assert exc.value.code == "unsupported_type"


def test_prepare_upload_rejects_empty_and_whitespace_text():
    with pytest.raises(material_files.UploadValidationError) as empty:
        material_files.prepare_upload(upload("notes.txt", b""))
    with pytest.raises(material_files.UploadValidationError) as whitespace:
        material_files.prepare_upload(upload("notes.md", b"  \n"))

    assert empty.value.code == whitespace.value.code == "empty_file"


def test_prepare_upload_rejects_oversized_content(monkeypatch):
    monkeypatch.setenv("ONTRACK_MAX_UPLOAD_BYTES", "4")

    with pytest.raises(material_files.UploadValidationError) as exc:
        material_files.prepare_upload(upload("notes.txt", b"12345"))

    assert exc.value.code == "file_too_large"


@pytest.mark.parametrize(
    ("name", "content", "expected_code"),
    [
        ("fake.pdf", b"plain text", "content_mismatch"),
        ("fake.txt", b"%PDF-1.7\n", "content_mismatch"),
        ("fake.docx", b"PK\x03\x04not-a-zip", "corrupt_file"),
    ],
)
def test_prepare_upload_rejects_deceptive_or_corrupt_content(name, content, expected_code):
    with pytest.raises(material_files.UploadValidationError) as exc:
        material_files.prepare_upload(upload(name, content))

    assert exc.value.code == expected_code


def test_prepare_upload_rejects_zip_with_wrong_office_document_type():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")

    with pytest.raises(material_files.UploadValidationError) as exc:
        material_files.prepare_upload(upload("slides.pptx", stream.getvalue()))

    assert exc.value.code == "content_mismatch"


@pytest.mark.django_db
def test_local_storage_uses_randomized_keys_under_owned_course(tmp_path, monkeypatch, django_user_model):
    from agent.services import storage

    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    user = django_user_model.objects.create_user(username="material-owner")
    storage.write_course_draft("cs101", "CS 101", user)

    first = material_files.object_storage.save(user, "cs101", ".txt", b"one")
    second = material_files.object_storage.save(user, "cs101", ".txt", b"two")

    assert first != second
    assert material_files.STORAGE_KEY_RE.fullmatch(first)
    assert material_files.object_storage.read(user, "cs101", first) == b"one"
    assert (tmp_path / str(user.pk) / "cs101" / "uploads" / first).exists()
