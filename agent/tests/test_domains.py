import json

import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_read_trusted_domains_empty_before_approval(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="domains-empty", email="domains-empty@example.com")
    assert storage.read_trusted_domains("cs101", user) == []


@pytest.mark.django_db
def test_write_then_read_trusted_domains_roundtrip(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="domains-roundtrip", email="domains-roundtrip@example.com")
    storage.write_trusted_domains("cs101", ["docs.python.org", "nist.gov"], user)

    assert storage.read_trusted_domains("cs101", user) == ["docs.python.org", "nist.gov"]


@pytest.mark.django_db
def test_write_trusted_domains_always_overwrites(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="domains-overwrite", email="domains-overwrite@example.com")
    storage.write_trusted_domains("cs101", ["a.com"], user)
    storage.write_trusted_domains("cs101", ["b.com"], user)

    assert storage.read_trusted_domains("cs101", user) == ["b.com"]


def test_validate_trusted_domains_rejects_empty_domain_string():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com", ""]})

    assert any("domains[1]" in e for e in errors)


def test_validate_trusted_domains_rejects_missing_field():
    errors = storage.validate_trusted_domains({"course_id": "cs101"})

    assert any("domains" in e for e in errors)


def test_validate_trusted_domains_accepts_valid_data():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com"]})

    assert errors == []


@pytest.mark.django_db
def test_read_trusted_domains_rejects_malformed_on_disk_shape(isolated_courses_dir, django_user_model):
    # trusted_domains.json is hand-editable — a hand-edit like this (a bare
    # string instead of a list) must fail loudly and clearly at the storage
    # layer, not flow a truthy string into allowed_domains in ask.py.
    user = django_user_model.objects.create_user(username="domains-malformed", email="domains-malformed@example.com")
    course_dir = isolated_courses_dir / str(user.pk) / "cs101"
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "trusted_domains.json").write_text(
        json.dumps({"course_id": "cs101", "domains": "not-a-list"}), encoding="utf-8",
    )

    with pytest.raises(storage.TrustedDomainsStorageError):
        storage.read_trusted_domains("cs101", user)
