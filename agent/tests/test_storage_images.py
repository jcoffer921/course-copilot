import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _entry(**overrides):
    entry = {"image_id": "p001-01", "source_page": 1, "chunk_ids": ["recursion-base"], "match_method": "proximity"}
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------
# validate_image_manifest — schema validation success + failure modes
# --------------------------------------------------------------------------

def test_validate_image_manifest_accepts_valid_entries():
    assert storage.validate_image_manifest([_entry(), _entry(image_id="p001-02", chunk_ids=[])]) == []


def test_validate_image_manifest_rejects_non_list():
    errors = storage.validate_image_manifest({"not": "a list"})
    assert errors == ["manifest must be a list"]


def test_validate_image_manifest_rejects_duplicate_image_id():
    errors = storage.validate_image_manifest([_entry(), _entry()])
    assert any("duplicate" in e for e in errors)


def test_validate_image_manifest_rejects_unsafe_image_id():
    errors = storage.validate_image_manifest([_entry(image_id="../escape")])
    assert any("safe identifier" in e for e in errors)


def test_validate_image_manifest_rejects_non_positive_source_page():
    errors = storage.validate_image_manifest([_entry(source_page=0)])
    assert any("source_page" in e for e in errors)

    errors = storage.validate_image_manifest([_entry(source_page="1")])
    assert any("source_page" in e for e in errors)


def test_validate_image_manifest_rejects_bad_chunk_ids_shape():
    errors = storage.validate_image_manifest([_entry(chunk_ids="recursion-base")])
    assert any("chunk_ids" in e for e in errors)

    errors = storage.validate_image_manifest([_entry(chunk_ids=[""])])
    assert any("chunk_ids" in e for e in errors)


def test_validate_image_manifest_rejects_unknown_match_method():
    errors = storage.validate_image_manifest([_entry(match_method="vision")])
    assert any("match_method" in e for e in errors)


def test_validate_image_manifest_rejects_missing_image_id():
    entry = _entry()
    del entry["image_id"]
    errors = storage.validate_image_manifest([entry])
    assert any("image_id" in e for e in errors)


# --------------------------------------------------------------------------
# validate_notes — additive "page"/"image_ids" chunk fields
# --------------------------------------------------------------------------

def _notes(chunk_overrides=None):
    chunk = {"id": "recursion-base", "topic": "Recursion", "text": "text"}
    chunk.update(chunk_overrides or {})
    return {"lecture_id": "lecture01", "source": "notes", "topics": ["Recursion"], "chunks": [chunk]}


def test_validate_notes_accepts_chunks_without_page_or_image_ids():
    assert storage.validate_notes(_notes()) == []


def test_validate_notes_accepts_null_page_and_populated_image_ids():
    assert storage.validate_notes(_notes({"page": None, "image_ids": ["p001-01"]})) == []


def test_validate_notes_accepts_positive_page():
    assert storage.validate_notes(_notes({"page": 3})) == []


def test_validate_notes_rejects_non_positive_page():
    errors = storage.validate_notes(_notes({"page": 0}))
    assert any("page" in e for e in errors)


def test_validate_notes_rejects_non_integer_page():
    errors = storage.validate_notes(_notes({"page": "3"}))
    assert any("page" in e for e in errors)


def test_validate_notes_rejects_bad_image_ids_shape():
    errors = storage.validate_notes(_notes({"image_ids": "p001-01"}))
    assert any("image_ids" in e for e in errors)

    errors = storage.validate_notes(_notes({"image_ids": [""]}))
    assert any("image_ids" in e for e in errors)


# --------------------------------------------------------------------------
# lecture_image_path — path-traversal guard
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_lecture_image_path_rejects_traversal(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-path-1", email="img-path-1@example.com")
    with pytest.raises(storage.InvalidImageIdError):
        storage.lecture_image_path("cs101", "lecture01", "../escape", user)


@pytest.mark.django_db
def test_lecture_image_path_resolves_within_lecture_dir(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-path-2", email="img-path-2@example.com")
    path = storage.lecture_image_path("cs101", "lecture01", "p001-01", user)
    assert path.name == "p001-01.png"
    assert path.parent.name == "lecture01"


# --------------------------------------------------------------------------
# read/write_image_manifest — round trip, plan-then-pause, corrupt file
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_read_image_manifest_none_when_missing(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-manifest-1", email="img-manifest-1@example.com")
    assert storage.read_image_manifest("cs101", "lecture01", user) is None


@pytest.mark.django_db
def test_write_then_read_image_manifest_roundtrip(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-manifest-2", email="img-manifest-2@example.com")
    entries = [_entry()]
    storage.write_image_manifest("cs101", "lecture01", entries, user)

    assert storage.read_image_manifest("cs101", "lecture01", user) == entries


@pytest.mark.django_db
def test_write_image_manifest_raises_on_existing_without_overwrite(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-manifest-3", email="img-manifest-3@example.com")
    storage.write_image_manifest("cs101", "lecture01", [_entry()], user)

    with pytest.raises(FileExistsError):
        storage.write_image_manifest("cs101", "lecture01", [_entry()], user)


@pytest.mark.django_db
def test_write_image_manifest_rejects_invalid_entries_before_writing(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-manifest-4", email="img-manifest-4@example.com")
    with pytest.raises(storage.ImageManifestStorageError):
        storage.write_image_manifest("cs101", "lecture01", [_entry(source_page=0)], user)

    assert storage.read_image_manifest("cs101", "lecture01", user) is None


@pytest.mark.django_db
def test_read_image_manifest_raises_on_corrupt_file(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-manifest-5", email="img-manifest-5@example.com")
    lecture_dir = isolated_courses_dir / str(user.pk) / "cs101" / "images" / "lecture01"
    lecture_dir.mkdir(parents=True)
    (lecture_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(storage.ImageManifestStorageError):
        storage.read_image_manifest("cs101", "lecture01", user)


# --------------------------------------------------------------------------
# write_lecture_image / delete_lecture_images
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_write_lecture_image_then_path_exists(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-write-1", email="img-write-1@example.com")
    out_path = storage.write_lecture_image("cs101", "lecture01", "p001-01", b"fake-png-bytes", user)

    assert out_path.exists()
    assert out_path.read_bytes() == b"fake-png-bytes"


@pytest.mark.django_db
def test_write_lecture_image_raises_on_existing_without_overwrite(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-write-2", email="img-write-2@example.com")
    storage.write_lecture_image("cs101", "lecture01", "p001-01", b"one", user)

    with pytest.raises(FileExistsError):
        storage.write_lecture_image("cs101", "lecture01", "p001-01", b"two", user)


@pytest.mark.django_db
def test_delete_lecture_images_removes_manifest_and_pngs(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-delete-1", email="img-delete-1@example.com")
    storage.write_lecture_image("cs101", "lecture01", "p001-01", b"png", user)
    storage.write_image_manifest("cs101", "lecture01", [_entry()], user)

    storage.delete_lecture_images("cs101", "lecture01", user)

    assert storage.read_image_manifest("cs101", "lecture01", user) is None


@pytest.mark.django_db
def test_delete_lecture_images_is_a_noop_when_nothing_exists(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="img-delete-2", email="img-delete-2@example.com")
    storage.delete_lecture_images("cs101", "lecture01", user)  # must not raise
