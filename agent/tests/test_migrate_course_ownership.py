"""Tests for the one-time migrate_course_ownership command that moves
existing flat courses/<course_id>/ directories into the new
courses/<owner.pk>/<course_id>/ layout."""
import json

import pytest
from django.core.management import call_command

from agent.services import cli_owner, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_migrate_moves_flat_course_dir_under_owner(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text(
        json.dumps({"course_id": "cs101", "course_name": "Intro to CS", "dates": [], "grading": [], "topics": []}),
        encoding="utf-8",
    )

    call_command("migrate_course_ownership", "--apply")

    new_path = isolated_courses_dir / str(owner.pk) / "cs101" / "syllabus.json"
    assert new_path.exists()
    assert not old_course_dir.exists()


@pytest.mark.django_db
def test_migrate_is_a_dry_run_by_default(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership")

    assert old_course_dir.exists()
    assert not (isolated_courses_dir / str(owner.pk)).exists()


@pytest.mark.django_db
def test_migrate_skips_a_non_course_top_level_file(isolated_courses_dir, monkeypatch, django_user_model):
    django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    (isolated_courses_dir / "custom_events.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership", "--apply")

    assert (isolated_courses_dir / "custom_events.json").exists()


@pytest.mark.django_db
def test_migrate_is_idempotent(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership", "--apply")
    call_command("migrate_course_ownership", "--apply")  # should no-op the second time, not error

    assert (isolated_courses_dir / str(owner.pk) / "cs101" / "syllabus.json").exists()
