"""Tests for the `ask` management command's CLI rendering of resolved
citations — in particular that it prints linked figure file paths instead of
describing them in prose, and that it no longer crashes trying to
str.join() the structured citation dicts ask_async actually returns
(result["sources"] is a list of dicts by the time ask_async returns, not the
model's raw string labels)."""
from io import StringIO

import pytest
from django.core.management import call_command


@pytest.fixture
def owner_env(monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="ask-cmd-owner", email="ask-cmd-owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "ask-cmd-owner@example.com")
    return owner


async def _fake_ask_async_with_images(course_id, question, session_id=None, user=None, **kwargs):
    return {
        "answer": "A base case stops recursion.",
        "grounded": True,
        "sources": [
            {
                "material_id": "abc123", "material_type": "notes", "title": "lecture-01.pdf",
                "lecture_id": "lecture-01", "chunk_id": "recursion-base", "page": 1, "url": None,
                "excerpt": "...",
                "images": [{"image_id": "p001-01", "path": "/courses/1/cs101/images/lecture-01/p001-01.png"}],
            },
        ],
    }


async def _fake_ask_async_ungrounded(course_id, question, session_id=None, user=None, **kwargs):
    return {"answer": "This isn't covered in the course materials.", "grounded": False, "sources": []}


@pytest.mark.django_db
def test_ask_command_prints_figure_path_for_grounded_answer_with_images(owner_env, monkeypatch):
    monkeypatch.setattr("agent.management.commands.ask.ask_async", _fake_ask_async_with_images)
    out = StringIO()

    call_command("ask", "cs101", "what stops recursion?", stdout=out)

    output = out.getvalue()
    assert "A base case stops recursion." in output
    assert "grounded: true" in output
    assert "lecture-01.pdf" in output
    assert "figure: /courses/1/cs101/images/lecture-01/p001-01.png" in output


@pytest.mark.django_db
def test_ask_command_does_not_crash_when_no_sources_have_images(owner_env, monkeypatch):
    async def fake_ask_async(course_id, question, session_id=None, user=None, **kwargs):
        return {
            "answer": "The syllabus lists three exams.",
            "grounded": True,
            "sources": [{
                "material_id": "syllabus", "material_type": "syllabus", "title": "Course syllabus",
                "lecture_id": None, "chunk_id": None, "page": None, "url": None, "excerpt": "...",
            }],
        }
    monkeypatch.setattr("agent.management.commands.ask.ask_async", fake_ask_async)
    out = StringIO()

    call_command("ask", "cs101", "how many exams?", stdout=out)

    output = out.getvalue()
    assert "grounded: true (sources: Course syllabus)" in output
    assert "figure:" not in output


@pytest.mark.django_db
def test_ask_command_ungrounded_answer_still_renders(owner_env, monkeypatch):
    monkeypatch.setattr("agent.management.commands.ask.ask_async", _fake_ask_async_ungrounded)
    out = StringIO()

    call_command("ask", "cs101", "what's the meaning of life?", stdout=out)

    output = out.getvalue()
    assert "grounded: false" in output
