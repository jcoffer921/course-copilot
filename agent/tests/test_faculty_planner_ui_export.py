import io
import zipfile

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings
from agent.services import plan_state


def activate(user, role=UserSettings.ROLE_STUDENT):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


def create_requirement(user, program_name="B.S. Computer Science"):
    return ProgramRequirement.objects.create(
        user=user,
        program_name=program_name,
        catalog_year="2026-2027",
        requirements={
            "program_name": program_name,
            "catalog_year": "2026-2027",
            "total_credits_required": 120,
            "categories": [
                {
                    "name": "Core",
                    "credits_required": 3,
                    "courses": [
                        {
                            "code": "CS 101",
                            "title": "Intro to Programming",
                            "credits": 3,
                            "prerequisites": [],
                            "notes": "",
                        }
                    ],
                }
            ],
        },
    )


@pytest.fixture
def faculty_user(django_user_model):
    user = django_user_model.objects.create_user(username="faculty-planner-ui")
    activate(user, UserSettings.ROLE_FACULTY)
    return user


@pytest.fixture
def student_user(django_user_model):
    user = django_user_model.objects.create_user(username="student-planner-ui")
    activate(user)
    return user


def _draft_plan():
    return {
        "student_major": "Computer Science",
        "semesters": [
            {
                "label": "Fall 2026",
                "courses": [
                    {"code": "CS 101", "title": "Intro to Programming", "credits": 3}
                ],
            }
        ],
        "total_credits": 3,
        "notes": "Confirm elective availability with the department.",
    }


def _authenticated_api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_export_requires_a_session_draft(faculty_user):
    response = _authenticated_api_client(faculty_user).post("/api/faculty/plan/export/")
    assert response.status_code == 400
    assert response.data["detail"] == "Create a draft plan before downloading it."


@pytest.mark.django_db
def test_export_streams_current_session_draft_as_docx(faculty_user):
    client = _authenticated_api_client(faculty_user)
    plan_state.write(faculty_user, {
        "program_requirement_id": "00000000-0000-0000-0000-000000000000",
        "student_details": {"name": "Not exported"},
        "conversation": [{"role": "user", "content": "private conversation"}],
        "draft_plan": _draft_plan(),
    })

    response = client.post("/api/faculty/plan/export/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response["Content-Disposition"].startswith('attachment; filename="academic-plan-')
    payload = b"".join(response.streaming_content)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode()
    assert "Computer Science" in document_xml
    assert "CS 101" in document_xml
    assert "private conversation" not in document_xml
    assert "Not exported" not in document_xml


@pytest.mark.django_db
def test_student_gets_404_on_export(student_user):
    client = _authenticated_api_client(student_user)
    plan_state.write(student_user, {"draft_plan": _draft_plan()})

    assert client.post("/api/faculty/plan/export/").status_code == 404
