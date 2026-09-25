import io
import zipfile

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings


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


@pytest.mark.django_db
def test_faculty_planner_page_is_gated_and_loads_owned_program_library(
    client, faculty_user, student_user, django_user_model
):
    owned = create_requirement(faculty_user)
    other = django_user_model.objects.create_user(username="other-faculty-planner")
    activate(other, UserSettings.ROLE_FACULTY)
    create_requirement(other, "B.S. Biology")

    client.force_login(student_user)
    assert client.get(reverse("faculty-planner")).status_code == 404

    client.force_login(faculty_user)
    response = client.get(reverse("faculty-planner"))

    assert response.status_code == 200
    assert response.context["program_requirements"][0]["requirement_id"] == str(owned.requirement_id)
    content = response.content.decode()
    assert "B.S. Computer Science" in content
    assert "B.S. Biology" not in content
    assert "/api/faculty/requirements/import/" in content
    assert "/api/faculty/plan/export/" in content


@pytest.mark.django_db
def test_anonymous_faculty_planner_page_redirects_to_login(client):
    response = client.get(reverse("faculty-planner"))
    assert response.status_code == 302


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('route_name', 'expected_heading'),
    [
        ('faculty-dashboard', 'Good'),
        ('faculty-import', 'Import Data'),
    ],
)
def test_faculty_workflow_pages_are_gated(client, faculty_user, student_user, route_name, expected_heading):
    client.force_login(student_user)
    assert client.get(reverse(route_name)).status_code == 404

    client.force_login(faculty_user)
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert expected_heading in response.content.decode()


@pytest.mark.django_db
def test_faculty_dashboard_uses_faculty_navigation_and_privacy_language(client, faculty_user):
    client.force_login(faculty_user)

    content = client.get(reverse('faculty-dashboard')).content.decode()

    assert reverse('faculty-dashboard') in content
    assert reverse('faculty-import') in content
    assert reverse('faculty-planner') in content
    assert 'Templates' in content
    assert 'No student data stored' in content
    assert 'FERPA-conscious workflow' in content
    assert '>Calendar<' not in content
    assert '>Courses<' not in content
    assert '>Study<' not in content


@pytest.mark.django_db
def test_faculty_import_is_an_empty_state(client, faculty_user):
    client.force_login(faculty_user)

    content = client.get(reverse('faculty-import')).content.decode()

    assert 'Upload Excel / CSV' in content
    assert 'Column mapping will appear here' in content
    assert 'Preview will appear here after upload' in content
    assert 'No student data is stored' in content
    assert 'Temporary ID' not in content
    assert 'Student ID' not in content


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
    session = client.session
    session["faculty_plan_session"] = {
        "program_requirement_id": "00000000-0000-0000-0000-000000000000",
        "student_details": {"name": "Not exported"},
        "conversation": [{"role": "user", "content": "private conversation"}],
        "draft_plan": _draft_plan(),
    }
    session.save()

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
    session = client.session
    session["faculty_plan_session"] = {"draft_plan": _draft_plan()}
    session.save()

    assert client.post("/api/faculty/plan/export/").status_code == 404
