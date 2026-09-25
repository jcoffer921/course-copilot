import io

import pytest
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings
from agent.services import requirements_extraction


def activate(user, role=UserSettings.ROLE_STUDENT):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


@pytest.fixture
def faculty_client(django_user_model):
    user = django_user_model.objects.create_user(username="faculty-endpoint-user")
    activate(user, role=UserSettings.ROLE_FACULTY)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def student_client(django_user_model):
    user = django_user_model.objects.create_user(username="student-endpoint-user")
    activate(user, role=UserSettings.ROLE_STUDENT)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


def _upload(name="requirements.xlsx", content=b"fake-xlsx-bytes"):
    value = io.BytesIO(content)
    value.name = name
    return value


def _requirements_payload(program_name="B.S. Test", catalog_year="2026-2027"):
    return {
        "program_name": program_name,
        "catalog_year": catalog_year,
        "total_credits_required": 120,
        "categories": [
            {"name": "Core", "credits_required": 30, "courses": [
                {"code": "CS 101", "title": "Intro", "credits": 3, "prerequisites": [], "notes": ""},
            ]},
        ],
    }


@pytest.mark.django_db
def test_import_returns_unsaved_json_without_writing_to_db(faculty_client, monkeypatch):
    async def fake_extract(*_args, **_kwargs):
        return _requirements_payload()

    monkeypatch.setattr(requirements_extraction, "extract_requirements_async", fake_extract)

    response = faculty_client.post(
        "/api/faculty/requirements/import/", {"file": _upload()}, format="multipart",
    )

    assert response.status_code == 200
    assert response.data["requirements"]["program_name"] == "B.S. Test"
    assert not ProgramRequirement.objects.exists()


@pytest.mark.django_db
def test_confirm_creates_row(faculty_client):
    response = faculty_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": _requirements_payload()},
        format="json",
    )

    assert response.status_code == 201
    row = ProgramRequirement.objects.get()
    assert row.program_name == "B.S. Test"
    assert row.user == faculty_client.user


@pytest.mark.django_db
def test_confirm_without_overwrite_on_collision_returns_409_and_does_not_touch_existing(faculty_client):
    faculty_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": _requirements_payload()},
        format="json",
    )
    original_updated_at = ProgramRequirement.objects.get().updated_at

    colliding_payload = _requirements_payload()
    colliding_payload["total_credits_required"] = 999

    response = faculty_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": colliding_payload},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["existing"]["program_name"] == "B.S. Test"
    row = ProgramRequirement.objects.get()
    assert row.program_name == "B.S. Test"
    assert row.updated_at == original_updated_at


@pytest.mark.django_db
def test_confirm_with_overwrite_updates_existing_row(faculty_client):
    faculty_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": _requirements_payload()},
        format="json",
    )

    updated_payload = _requirements_payload()
    updated_payload["total_credits_required"] = 121

    response = faculty_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": updated_payload, "overwrite": True},
        format="json",
    )

    assert response.status_code == 200
    assert ProgramRequirement.objects.count() == 1
    row = ProgramRequirement.objects.get()
    assert row.requirements["total_credits_required"] == 121


@pytest.mark.django_db
def test_student_gets_404_on_both_faculty_requirements_endpoints(student_client, monkeypatch):
    async def fake_extract(*_args, **_kwargs):
        return _requirements_payload()

    monkeypatch.setattr(requirements_extraction, "extract_requirements_async", fake_extract)

    import_response = student_client.post(
        "/api/faculty/requirements/import/", {"file": _upload()}, format="multipart",
    )
    confirm_response = student_client.post(
        "/api/faculty/requirements/confirm/",
        {"confirm": True, "requirements": _requirements_payload()},
        format="json",
    )

    assert import_response.status_code == 404
    assert confirm_response.status_code == 404
