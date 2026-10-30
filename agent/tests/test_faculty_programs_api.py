import uuid

import pytest
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings

LIST_URL = "/api/faculty/requirements/"


def detail_url(requirement_id):
    return f"/api/faculty/requirements/{requirement_id}/"


def activate(user, role):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


def make_client(django_user_model, username, role=UserSettings.ROLE_FACULTY):
    user = django_user_model.objects.create_user(username=username)
    activate(user, role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def faculty_client(django_user_model):
    return make_client(django_user_model, "programs-faculty")


@pytest.fixture
def other_faculty_client(django_user_model):
    return make_client(django_user_model, "programs-other-faculty")


@pytest.fixture
def student_client(django_user_model):
    return make_client(django_user_model, "programs-student", UserSettings.ROLE_STUDENT)


def make_program(user, name="B.S. Test", year="2026-2027", categories=None):
    if categories is None:
        categories = [
            {"name": "Core", "credits_required": 7, "courses": [
                {"code": "CS 101", "title": "Intro", "credits": 3, "prerequisites": [], "notes": ""},
                {"code": "CS 201", "title": "Data Structures", "credits": 4, "prerequisites": ["CS 101", "CS 150"], "notes": ""},
            ]},
            {"name": "Math", "credits_required": 3, "courses": [
                {"code": "MATH 230", "title": "Discrete", "credits": 3, "prerequisites": ["CS 101"], "notes": ""},
            ]},
        ]
    return ProgramRequirement.objects.create(
        user=user, program_name=name, catalog_year=year,
        requirements={"program_name": name, "catalog_year": year, "total_credits_required": 120, "categories": categories},
    )


@pytest.mark.django_db
def test_list_returns_only_own_programs_sorted(faculty_client, other_faculty_client):
    make_program(faculty_client.user, "B.S. Zoology", "2025-2026")
    make_program(faculty_client.user, "B.S. Biology", "2026-2027")
    make_program(faculty_client.user, "B.S. Biology", "2025-2026")
    make_program(other_faculty_client.user, "B.S. Hidden")

    response = faculty_client.get(LIST_URL)

    assert response.status_code == 200
    rows = response.data["programs"]
    assert [(r["program_name"], r["catalog_year"]) for r in rows] == [
        ("B.S. Biology", "2025-2026"), ("B.S. Biology", "2026-2027"), ("B.S. Zoology", "2025-2026"),
    ]
    assert rows[0]["total_credits_required"] == 120
    assert "requirements" not in rows[0]


@pytest.mark.django_db
def test_detail_returns_structure_and_prerequisite_checks(faculty_client):
    row = make_program(faculty_client.user)

    response = faculty_client.get(detail_url(row.requirement_id))

    assert response.status_code == 200
    program = response.data["program"]
    assert program["requirement_id"] == str(row.requirement_id)
    assert program["categories"] == [
        {"name": "Core", "credits_required": 7, "course_count": 2},
        {"name": "Math", "credits_required": 3, "course_count": 1},
    ]
    # CS 101, CS 150, CS 101 referenced; CS 150 is not a course in this program.
    assert program["checks"] == {"prerequisites_total": 3, "prerequisites_resolved": 2}


@pytest.mark.django_db
def test_detail_and_delete_foreign_id_match_missing_id_404(faculty_client, other_faculty_client):
    foreign = make_program(other_faculty_client.user)
    missing = uuid.uuid4()

    for method in ("get", "delete"):
        foreign_response = getattr(faculty_client, method)(detail_url(foreign.requirement_id), {"confirm": True}, format="json")
        missing_response = getattr(faculty_client, method)(detail_url(missing), {"confirm": True}, format="json")
        assert foreign_response.status_code == missing_response.status_code == 404
        assert foreign_response.data == missing_response.data


@pytest.mark.django_db
def test_two_faculty_cannot_delete_each_others_program(faculty_client, other_faculty_client):
    row = make_program(other_faculty_client.user)

    faculty_client.delete(detail_url(row.requirement_id), {"confirm": True}, format="json")

    assert ProgramRequirement.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_delete_requires_explicit_confirm(faculty_client):
    row = make_program(faculty_client.user)

    for body in (None, {}, {"confirm": False}):
        response = faculty_client.delete(detail_url(row.requirement_id), body, format="json")
        assert response.status_code == 400

    assert ProgramRequirement.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_delete_removes_exactly_one_row(faculty_client):
    keep = make_program(faculty_client.user, "B.S. Keep")
    gone = make_program(faculty_client.user, "B.S. Gone")

    response = faculty_client.delete(detail_url(gone.requirement_id), {"confirm": True}, format="json")

    assert response.status_code == 204
    assert list(ProgramRequirement.objects.values_list("pk", flat=True)) == [keep.pk]


@pytest.mark.django_db
def test_delete_clears_matching_plan_session_only(faculty_client):
    gone = make_program(faculty_client.user, "B.S. Gone")
    keep = make_program(faculty_client.user, "B.S. Keep")

    def seed(program):
        session = faculty_client.session
        session["faculty_plan_session"] = {
            "program_requirement_id": str(program.requirement_id),
            "student_details": {}, "conversation": [], "draft_plan": None,
        }
        session.save()

    seed(keep)
    faculty_client.delete(detail_url(gone.requirement_id), {"confirm": True}, format="json")
    assert faculty_client.session.get("faculty_plan_session") is not None

    seed(gone)
    gone_again = make_program(faculty_client.user, "B.S. Gone Two")
    seed(gone_again)
    faculty_client.delete(detail_url(gone_again.requirement_id), {"confirm": True}, format="json")
    assert faculty_client.session.get("faculty_plan_session") is None


@pytest.mark.django_db
def test_empty_program_detail_and_list_do_not_error(faculty_client):
    row = make_program(faculty_client.user, "B.S. Empty", categories=[])

    detail = faculty_client.get(detail_url(row.requirement_id))
    listing = faculty_client.get(LIST_URL)

    assert detail.status_code == 200
    assert detail.data["program"]["categories"] == []
    assert detail.data["program"]["checks"] == {"prerequisites_total": 0, "prerequisites_resolved": 0}
    assert listing.status_code == 200
    assert listing.data["programs"][0]["category_count"] == 0


@pytest.mark.django_db
def test_student_gets_404_on_all_three(student_client, faculty_client):
    row = make_program(faculty_client.user)

    assert student_client.get(LIST_URL).status_code == 404
    assert student_client.get(detail_url(row.requirement_id)).status_code == 404
    assert student_client.delete(detail_url(row.requirement_id), {"confirm": True}, format="json").status_code == 404
    assert ProgramRequirement.objects.filter(pk=row.pk).exists()
