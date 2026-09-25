import json

import pytest
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings
from agent.services import academic_planner


def activate(user, role=UserSettings.ROLE_STUDENT):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


@pytest.fixture
def faculty_client(django_user_model):
    user = django_user_model.objects.create_user(username="plan-faculty-user")
    activate(user, role=UserSettings.ROLE_FACULTY)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def student_client(django_user_model):
    user = django_user_model.objects.create_user(username="plan-student-user")
    activate(user, role=UserSettings.ROLE_STUDENT)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def program_requirement(faculty_client):
    return ProgramRequirement.objects.create(
        user=faculty_client.user,
        program_name="B.S. Computer Science",
        catalog_year="2026-2027",
        requirements={
            "program_name": "B.S. Computer Science",
            "catalog_year": "2026-2027",
            "total_credits_required": 120,
            "categories": [
                {"name": "Core", "credits_required": 3, "courses": [
                    {"code": "CS 101", "title": "Intro to Programming", "credits": 3, "prerequisites": [], "notes": ""},
                ]},
            ],
        },
    )


def _mock_reply(monkeypatch, reply, draft_plan=None, student_details=None):
    async def fake_plan_chat_async(*_args, **_kwargs):
        return {
            "reply": reply,
            "student_details": student_details or {},
            "draft_plan": draft_plan,
        }

    monkeypatch.setattr(academic_planner, "plan_chat_async", fake_plan_chat_async)


@pytest.mark.django_db
def test_chat_returns_reply_and_updates_session(faculty_client, program_requirement, monkeypatch):
    _mock_reply(monkeypatch, "What's the student's major?")

    response = faculty_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program_requirement.requirement_id), "message": "New student"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["reply"] == "What's the student's major?"
    assert response.data["draft_plan"] is None

    session = faculty_client.session
    state = session["faculty_plan_session"]
    assert state["program_requirement_id"] == str(program_requirement.requirement_id)
    assert state["conversation"] == [
        {"role": "user", "content": "New student"},
        {"role": "assistant", "content": "What's the student's major?"},
    ]


@pytest.mark.django_db
def test_chat_with_unknown_program_requirement_returns_404(faculty_client):
    response = faculty_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": "00000000-0000-0000-0000-000000000000", "message": "Hi"},
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_chat_does_not_return_program_requirement_belonging_to_another_faculty(
    faculty_client, django_user_model, monkeypatch
):
    other = django_user_model.objects.create_user(username="other-faculty")
    activate(other, role=UserSettings.ROLE_FACULTY)
    other_row = ProgramRequirement.objects.create(
        user=other, program_name="Other Program", catalog_year="2026",
        requirements={"program_name": "Other Program", "catalog_year": "2026", "total_credits_required": 0, "categories": []},
    )

    response = faculty_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(other_row.requirement_id), "message": "Hi"},
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_reset_clears_session_state(faculty_client, program_requirement, monkeypatch):
    _mock_reply(monkeypatch, "Question?")
    faculty_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program_requirement.requirement_id), "message": "New student"},
        format="json",
    )
    assert "faculty_plan_session" in faculty_client.session

    response = faculty_client.post("/api/faculty/plan/reset/")

    assert response.status_code == 204
    assert "faculty_plan_session" not in faculty_client.session


@pytest.mark.django_db
def test_student_gets_404_on_chat_and_reset(student_client, program_requirement):
    chat_response = student_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program_requirement.requirement_id), "message": "Hi"},
        format="json",
    )
    reset_response = student_client.post("/api/faculty/plan/reset/")

    assert chat_response.status_code == 404
    assert reset_response.status_code == 404


@pytest.mark.django_db
def test_session_state_never_appears_in_any_db_row(faculty_client, program_requirement, monkeypatch):
    """Student-specific chat state (student_details, conversation, draft_plan)
    must live only in the session backend's opaque blob — never as a
    readable field on any app model."""
    _mock_reply(
        monkeypatch,
        "Here's a draft plan for Jane Doe, a sophomore transfer student.",
        draft_plan={
            "student_major": "Computer Science", "semesters": [], "total_credits": 0, "notes": "Jane Doe",
        },
        student_details={"name": "Jane Doe"},
    )

    faculty_client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program_requirement.requirement_id), "message": "Jane Doe, sophomore transfer"},
        format="json",
    )

    row = ProgramRequirement.objects.get(pk=program_requirement.pk)
    assert "Jane Doe" not in json.dumps(row.requirements)
    assert row.requirements == program_requirement.requirements
