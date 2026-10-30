import re

import pytest
from django.urls import reverse

from agent.models import UserSettings

FACULTY_ROUTES = ("faculty-workspace", "faculty-programs", "faculty-templates")


def activate(user, role=UserSettings.ROLE_STUDENT):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


@pytest.fixture
def faculty_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="faculty-studio", first_name="Priya", last_name="Williamson", email="pw@university.edu",
    )
    activate(user, UserSettings.ROLE_FACULTY)
    return user


@pytest.fixture
def student_user(django_user_model):
    user = django_user_model.objects.create_user(username="student-studio")
    activate(user)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", FACULTY_ROUTES)
def test_workspace_programs_templates_are_faculty_only(client, faculty_user, student_user, route_name):
    assert client.get(reverse(route_name)).status_code == 302

    client.force_login(student_user)
    assert client.get(reverse(route_name)).status_code == 404

    client.force_login(faculty_user)
    assert client.get(reverse(route_name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", FACULTY_ROUTES)
def test_faculty_shell_has_faculty_identity(client, faculty_user, route_name):
    client.force_login(faculty_user)

    html = client.get(reverse(route_name)).content.decode()

    assert 'data-area="faculty"' in html
    assert ">FACULTY<" in html
    assert "faculty_studio.css" in html
    for absent in ("app-sidebar", ">Courses<", ">Calendar<", ">Study<", "faculty-notification"):
        assert absent not in html


@pytest.mark.django_db
def test_rail_lists_exactly_three_tabs_and_marks_active(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-programs")).content.decode()

    for label in ("Workspace", "Programs", "Templates"):
        assert f">{label}<" in html
    current = re.findall(r'aria-current="page"[^>]*>', html)
    assert len(current) == 1
    programs_link = re.search(r'<a[^>]*href="%s"[^>]*>' % re.escape(reverse("faculty-programs")), html).group(0)
    assert 'aria-current="page"' in programs_link


@pytest.mark.django_db
def test_old_urls_redirect(client, faculty_user):
    client.force_login(faculty_user)

    assert client.get("/faculty/import/").headers["Location"] == reverse("faculty-programs")
    assert client.get("/faculty/cora/").headers["Location"] == reverse("faculty-workspace")
    assert reverse("faculty-workspace") == "/faculty/"


@pytest.mark.django_db
def test_avatar_menu_has_help_privacy_and_sign_out(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace")).content.decode()

    assert reverse("privacy-page") in html
    assert reverse("contact-page") in html
    assert reverse("google-logout") in html
    assert "PW" in html


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", FACULTY_ROUTES)
def test_no_emoji_in_faculty_pages(client, faculty_user, route_name):
    client.force_login(faculty_user)

    html = client.get(reverse(route_name)).content.decode()

    assert not [c for c in html if ord(c) >= 0x1F000]


# ---- Task 3: Workspace page ----

from agent.models import ProgramRequirement


def make_program(user, name="B.S. Computer Science", year="2026-2027"):
    return ProgramRequirement.objects.create(
        user=user,
        program_name=name,
        catalog_year=year,
        requirements={
            "program_name": name,
            "catalog_year": year,
            "total_credits_required": 120,
            "categories": [
                {"name": "Core", "credits_required": 7, "courses": [
                    {"code": "CS 101", "title": "Intro", "credits": 3, "prerequisites": [], "notes": ""},
                    {"code": "CS 201", "title": "Data Structures", "credits": 4, "prerequisites": ["CS 101"], "notes": ""},
                ]},
            ],
        },
    )


@pytest.fixture
def other_faculty(django_user_model):
    user = django_user_model.objects.create_user(username="other-faculty-studio")
    activate(user, UserSettings.ROLE_FACULTY)
    return user


@pytest.mark.django_db
def test_workspace_context_lists_only_own_programs(client, faculty_user, other_faculty):
    mine = make_program(faculty_user)
    make_program(other_faculty, "B.S. Biology")
    client.force_login(faculty_user)

    response = client.get(reverse("faculty-workspace"))

    ids = [p["requirement_id"] for p in response.context["programs"]]
    assert ids == [str(mine.requirement_id)]
    assert "B.S. Biology" not in response.content.decode()


@pytest.mark.django_db
def test_active_program_resolves_when_owned(client, faculty_user):
    mine = make_program(faculty_user)
    client.force_login(faculty_user)

    response = client.get(reverse("faculty-workspace"), {"program": str(mine.requirement_id)})

    assert response.context["active_program"]["requirement_id"] == str(mine.requirement_id)
    assert response.context["active_program"]["requirements"]["categories"][0]["name"] == "Core"


@pytest.mark.django_db
@pytest.mark.parametrize("bad_id", ["not-a-uuid", "11111111-1111-1111-1111-111111111111", ""])
def test_active_program_ignores_foreign_and_malformed_ids(client, faculty_user, other_faculty, bad_id):
    make_program(faculty_user)
    foreign = make_program(other_faculty, "B.S. Biology")
    client.force_login(faculty_user)

    for value in (bad_id, str(foreign.requirement_id)):
        response = client.get(reverse("faculty-workspace"), {"program": value})
        assert response.status_code == 200
        assert response.context["active_program"] is None
        assert "B.S. Biology" not in response.content.decode()


@pytest.mark.django_db
def test_workspace_home_state_when_no_program(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace")).content.decode()

    assert 'data-fw="home"' in html
    assert "Drop a requirements file" in html


@pytest.mark.django_db
def test_workspace_renders_three_panels_when_program_active(client, faculty_user):
    mine = make_program(faculty_user)
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace"), {"program": str(mine.requirement_id)}).content.decode()

    for region in ('data-fw="sources"', 'data-fw="plan"', 'data-fw="cora"'):
        assert region in html
    assert 'data-fw="home"' not in html
    assert "B.S. Computer Science" in html
    assert 'id="fw-active-program"' in html


@pytest.mark.django_db
def test_workspace_exposes_api_urls_and_privacy_note(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace")).content.decode()

    for url in ("/api/faculty/plan/chat/", "/api/faculty/plan/reset/", "/api/faculty/plan/export/",
                "/api/faculty/requirements/import/", "/api/faculty/requirements/confirm/"):
        assert url in html
    assert "Student details stay in this session only" in html


# ---- Task 4: draft plan view, Cora panel, reset and export ----

from pathlib import Path

STATIC_JS = Path(__file__).resolve().parents[1] / "static/agent/js"


@pytest.mark.django_db
def test_workspace_exposes_plan_and_cora_hooks(client, faculty_user):
    mine = make_program(faculty_user)
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace"), {"program": str(mine.requirement_id)}).content.decode()

    for hook in ("data-fw-summary", "data-fw-term-list", "data-fw-issues", "data-fw-chat-form",
                 "data-fw-export", "data-fw-reset", "data-fw-template-banner", "ontrack.facultySession"):
        assert hook in html


def test_workspace_script_uses_module_exports():
    source = (STATIC_JS / "faculty_workspace.js").read_text(encoding="utf-8")

    assert "./faculty_plan_model.js" in source
    # Student state never touches localStorage; only the export-layout preference may.
    assert all("EXPORT_FORMAT_KEY" in line for line in source.splitlines() if "localStorage" in line)
    assert "innerHTML" not in source


# ---- Task 5: shared import flow ----


@pytest.mark.django_db
@pytest.mark.parametrize("with_program", [False, True])
def test_workspace_wires_import_flow(client, faculty_user, with_program):
    params = {}
    if with_program:
        params["program"] = str(make_program(faculty_user).requirement_id)
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace"), params).content.decode()

    assert "data-fw-import-input" in html
    assert 'accept=".xlsx,.xlsm"' in html
    assert ".csv" not in html
    source = (STATIC_JS / "faculty_workspace.js").read_text(encoding="utf-8")
    assert "./faculty_import_flow.js" in source


def test_import_flow_module_contract():
    source = (STATIC_JS / "faculty_import_flow.js").read_text(encoding="utf-8")

    assert "export async function runImportFlow" in source
    assert "showModal" in source
    assert "overwrite: true" in source
    assert "innerHTML" not in source


# ---- Task 7: Programs page ----


@pytest.mark.django_db
def test_programs_page_lists_only_own_programs(client, faculty_user, other_faculty):
    mine = make_program(faculty_user)
    make_program(other_faculty, "B.S. Biology")
    client.force_login(faculty_user)

    response = client.get(reverse("faculty-programs"))

    assert [p["requirement_id"] for p in response.context["programs"]] == [str(mine.requirement_id)]
    html = response.content.decode()
    assert "B.S. Computer Science" in html
    assert "B.S. Biology" not in html


@pytest.mark.django_db
def test_programs_page_empty_state(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-programs")).content.decode()

    assert "No programs yet" in html
    assert "data-fp-import" in html
    assert "data-fp-row" not in html


@pytest.mark.django_db
def test_programs_plan_link_targets_workspace(client, faculty_user):
    mine = make_program(faculty_user)
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-programs")).content.decode()

    assert f'href="{reverse("faculty-workspace")}?program={mine.requirement_id}"' in html


@pytest.mark.django_db
def test_programs_page_exposes_hooks(client, faculty_user):
    make_program(faculty_user)
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-programs")).content.decode()

    for hook in ("data-fp-row", "data-fp-detail", "data-fp-import", "data-fp-delete", "data-fp-reimport",
                 "data-fp-plan", "data-fp-import-input"):
        assert hook in html
    assert 'accept=".xlsx,.xlsm"' in html
    source = (STATIC_JS / "faculty_programs.js").read_text(encoding="utf-8")
    assert "./faculty_import_flow.js" in source
    assert "innerHTML" not in source


# ---- Task 12: privacy regression and retired pages ----

import json

from django.apps import apps
from django.contrib.sessions.models import Session
from django.core import serializers
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_chat_and_export_persist_no_student_state_to_application_tables(faculty_user, monkeypatch):
    secret = "SECRET-STUDENT-ZEBRA-4471"
    program = make_program(faculty_user)

    async def fake_plan_chat(requirements, student_details, conversation, message, user):
        return {
            "reply": f"Noted: {message}",
            "student_details": {"name": secret},
            "draft_plan": {
                "student_major": "Computer Science",
                "semesters": [{"label": "Fall", "courses": [{"code": "CS 101", "title": "Intro", "credits": 3}]}],
                "total_credits": 3,
                "notes": secret,
            },
        }

    from agent import views

    monkeypatch.setattr(views.academic_planner, "plan_chat_async", fake_plan_chat)
    client = APIClient()
    client.force_authenticate(user=faculty_user)

    chat = client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program.requirement_id), "message": f"Student {secret} finished CS 101"},
        format="json",
    )
    export = client.post("/api/faculty/plan/export/", {"format": "plan_notes"}, format="json")
    assert chat.status_code == 200 and export.status_code == 200

    leaks = []
    for model in apps.get_models():
        if model is Session:
            continue  # session_data is encoded, so this scan cannot see it; see the reset test below
        dumped = serializers.serialize("json", model.objects.all())
        if secret in dumped:
            leaks.append(model.__name__)
    assert leaks == []


def test_removed_pages_have_no_template_or_script_references():
    root = Path(__file__).resolve().parents[1]
    retired = ("faculty_dashboard.html", "faculty_import.html", "faculty_planner.html",
               "faculty_planner.js", "faculty.css", "faculty.js")
    offenders = []
    for path in root.rglob("*"):
        if (not path.is_file() or "tests" in path.relative_to(root).parts or "__pycache__" in path.parts
                or path.suffix not in {".py", ".html", ".js", ".css"}):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in retired:
            # "faculty.js" / "faculty.css" must match as whole file names, not as a suffix of faculty_templates.js etc.
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name), text):
                offenders.append((str(path.relative_to(root)), name))
    assert offenders == []
    for name in retired:
        assert not list(root.rglob(name)), name


@pytest.mark.django_db
def test_new_session_purges_student_state_from_the_session_store(faculty_user, monkeypatch):
    secret = "SECRET-STUDENT-OTTER-9920"
    program = make_program(faculty_user)

    async def fake_plan_chat(requirements, student_details, conversation, message, user):
        return {"reply": "ok", "student_details": {"name": secret}, "draft_plan": None}

    from agent import views

    monkeypatch.setattr(views.academic_planner, "plan_chat_async", fake_plan_chat)
    client = APIClient()
    client.force_authenticate(user=faculty_user)
    client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program.requirement_id), "message": "hello"},
        format="json",
    )
    assert secret in json.dumps([s.get_decoded() for s in Session.objects.all()])

    assert client.post("/api/faculty/plan/reset/").status_code == 204

    assert secret not in json.dumps([s.get_decoded() for s in Session.objects.all()])
