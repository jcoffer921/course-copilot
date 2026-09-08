"""Tests for the extract_figures management command's CLI plumbing: the
plan-then-pause confirmation gate on a re-run (only when a manifest already
exists — a first-time extraction never prompts), --force skipping it, and
that the command surfaces the service layer's failure modes as CommandError
rather than a raw traceback."""
from io import StringIO

import pymupdf
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def owner_env(monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="ef-cmd-owner", email="ef-cmd-owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "ef-cmd-owner@example.com")
    return owner


def _seed_lecture(owner, course_id="cs101", lecture_id="lecture01"):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": "CS101", "dates": [], "grading": [], "topics": ["Recursion"],
    }, owner)
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "source": "notes", "date": "2026-08-25", "topics": ["Recursion"],
        "chunks": [{"id": "recursion-base", "topic": "Recursion", "text": "Recursion base case stops the recursive calls immediately."}],
    }, owner)


def _build_pdf_with_one_real_image(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Recursion base case stops the recursive calls immediately.")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (200, 50, 50))
    page.insert_image(pymupdf.Rect(300, 300, 500, 500), pixmap=pix)
    path = tmp_path / "lecture.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.mark.django_db
def test_first_time_extraction_writes_without_prompting(isolated_courses_dir, owner_env, tmp_path):
    _seed_lecture(owner_env)
    pdf_path = _build_pdf_with_one_real_image(tmp_path)
    out = StringIO()

    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=out)

    assert "Wrote 1 figure(s)" in out.getvalue()
    manifest = storage.read_image_manifest("cs101", "lecture01", owner_env)
    assert len(manifest) == 1


@pytest.mark.django_db
def test_rerun_without_force_prompts_and_aborts_on_no(isolated_courses_dir, owner_env, tmp_path, monkeypatch):
    _seed_lecture(owner_env)
    pdf_path = _build_pdf_with_one_real_image(tmp_path)
    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=StringIO())

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    out = StringIO()
    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=out)

    assert "Aborted" in out.getvalue()


@pytest.mark.django_db
def test_rerun_without_force_confirms_yes_and_overwrites(isolated_courses_dir, owner_env, tmp_path, monkeypatch):
    _seed_lecture(owner_env)
    pdf_path = _build_pdf_with_one_real_image(tmp_path)
    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=StringIO())

    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    out = StringIO()
    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=out)

    assert "Wrote 1 figure(s)" in out.getvalue()


@pytest.mark.django_db
def test_rerun_with_force_skips_confirmation_prompt(isolated_courses_dir, owner_env, tmp_path, monkeypatch):
    _seed_lecture(owner_env)
    pdf_path = _build_pdf_with_one_real_image(tmp_path)
    call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=StringIO())

    def _fail_if_called(prompt=""):
        raise AssertionError("--force must not prompt for confirmation")
    monkeypatch.setattr("builtins.input", _fail_if_called)

    out = StringIO()
    call_command("extract_figures", "--force", str(pdf_path), "cs101", "lecture01", stdout=out)

    assert "Wrote 1 figure(s)" in out.getvalue()


@pytest.mark.django_db
def test_command_raises_command_error_on_missing_source_file(isolated_courses_dir, owner_env):
    _seed_lecture(owner_env)

    with pytest.raises(CommandError):
        call_command("extract_figures", str(isolated_courses_dir / "nope.pdf"), "cs101", "lecture01", stdout=StringIO())


@pytest.mark.django_db
def test_command_raises_command_error_when_notes_do_not_exist_yet(isolated_courses_dir, owner_env, tmp_path):
    storage.write_syllabus("cs101", {"course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": []}, owner_env)
    pdf_path = _build_pdf_with_one_real_image(tmp_path)

    with pytest.raises(CommandError):
        call_command("extract_figures", str(pdf_path), "cs101", "lecture01", stdout=StringIO())
