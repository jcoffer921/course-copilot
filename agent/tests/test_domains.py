import json

import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_trusted_domains_empty_before_approval(isolated_courses_dir):
    assert storage.read_trusted_domains("cs101") == []


def test_write_then_read_trusted_domains_roundtrip(isolated_courses_dir):
    storage.write_trusted_domains("cs101", ["docs.python.org", "nist.gov"])

    assert storage.read_trusted_domains("cs101") == ["docs.python.org", "nist.gov"]


def test_write_trusted_domains_always_overwrites(isolated_courses_dir):
    storage.write_trusted_domains("cs101", ["a.com"])
    storage.write_trusted_domains("cs101", ["b.com"])

    assert storage.read_trusted_domains("cs101") == ["b.com"]


def test_validate_trusted_domains_rejects_empty_domain_string():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com", ""]})

    assert any("domains[1]" in e for e in errors)


def test_validate_trusted_domains_rejects_missing_field():
    errors = storage.validate_trusted_domains({"course_id": "cs101"})

    assert any("domains" in e for e in errors)


def test_validate_trusted_domains_accepts_valid_data():
    errors = storage.validate_trusted_domains({"course_id": "cs101", "domains": ["good.com"]})

    assert errors == []


def test_read_trusted_domains_rejects_malformed_on_disk_shape(isolated_courses_dir):
    # trusted_domains.json is hand-editable — a hand-edit like this (a bare
    # string instead of a list) must fail loudly and clearly at the storage
    # layer, not flow a truthy string into allowed_domains in ask.py.
    course_dir = isolated_courses_dir / "cs101"
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "trusted_domains.json").write_text(
        json.dumps({"course_id": "cs101", "domains": "not-a-list"}), encoding="utf-8",
    )

    with pytest.raises(storage.TrustedDomainsStorageError):
        storage.read_trusted_domains("cs101")
