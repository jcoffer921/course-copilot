from pathlib import Path

import pytest
from django.urls import reverse

from agent.models import UserSettings


def activate(user, role=UserSettings.ROLE_STUDENT):
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)


@pytest.fixture
def faculty_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="faculty-templates-ui",
        first_name="Priya",
        last_name="Williamson",
        email="pwilliamson@university.edu",
    )
    activate(user, UserSettings.ROLE_FACULTY)
    return user


@pytest.fixture
def student_user(django_user_model):
    user = django_user_model.objects.create_user(username="student-templates-ui")
    activate(user)
    return user


@pytest.mark.django_db
def test_faculty_templates_page_is_faculty_only(client, faculty_user, student_user):
    client.force_login(student_user)
    assert client.get(reverse("faculty-templates")).status_code == 404

    client.force_login(faculty_user)
    response = client.get(reverse("faculty-templates"))

    assert response.status_code == 200
    assert response.context["page_name"] == "faculty-templates"


@pytest.mark.django_db
def test_anonymous_faculty_templates_page_redirects_to_login(client):
    response = client.get(reverse("faculty-templates"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_faculty_templates_page_renders_library_detail_and_builder(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-templates")).content.decode()

    for copy in (
        "Plan Templates",
        "Start faster with reusable academic planning templates for advising sessions.",
        "Templates store reusable structure only",
        "4-Year Plan Template",
        "Transfer Student Template",
        "Major Exploration Template",
        "Graduation Check Template",
        "Semester Advising Notes",
        "Template structure",
        "About this template",
        "Use this template",
        "Preview template",
    ):
        assert copy in html
    for hook in (
        'id="template-search"',
        'id="template-library"',
        'id="template-detail"',
        'id="template-empty"',
        'id="template-builder" class="faculty-template-modal" hidden',
        'id="template-form"',
    ):
        assert hook in html
    assert 'placeholder="Search templates by name, description, or tag..."' in html
    assert 'src="/static/agent/js/faculty_templates.js?v=faculty-templates-20261030-1"' in html
    assert 'role="dialog" aria-modal="true"' in html
    assert 'class="faculty-notification"' not in html


@pytest.mark.django_db
def test_faculty_templates_uses_faculty_rail_navigation(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-templates")).content.decode()

    for label in ("Workspace", "Programs", "Templates"):
        assert f">{label}<" in html
    assert f'href="{reverse("faculty-templates")}" class="fs-rail-link is-active" aria-current="page">' in html
    for student_label in ("Calendar", "Courses", "Study", "Analytics"):
        assert f">{student_label}</a>" not in html
    assert "PW" in html
    assert "pwilliamson@university.edu" in html


def test_faculty_templates_runtime_supports_search_filters_selection_and_safe_builder():
    root = Path(__file__).resolve().parents[2]
    controller = (root / "agent/static/agent/js/faculty_templates.js").read_text(encoding="utf-8")

    for contract in (
        "renderLibrary",
        "selectTemplate",
        "renderDetail",
        "openBuilder",
        "saveFacultyTemplates",
        "sessionStorage.setItem",
        "studentName",
        "studentId",
        "studentGPA",
    ):
        assert contract in controller


@pytest.mark.django_db
def test_templates_page_has_structure_only_chip_and_single_h1(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-templates")).content.decode()

    assert "Structure only" in html
    assert html.count("<h1") == 1


@pytest.mark.django_db
def test_templates_page_has_two_tabs_and_panels(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-templates")).content.decode()

    for tab in ("skeletons", "formats"):
        assert f'data-ft-tab="{tab}"' in html
        assert f'data-ft-panel="{tab}"' in html
    assert 'role="tablist"' in html
    assert "faculty.css" not in html


def test_use_in_workspace_links_to_workspace():
    root = Path(__file__).resolve().parents[2]
    controller = (root / "agent/static/agent/js/faculty_templates.js").read_text(encoding="utf-8")

    assert 'window.location.assign("/faculty/")' in controller
    assert "faculty/cora" not in controller
    assert "data-ft-tab" in controller


# ---- Task 11: export formats UI ----


@pytest.mark.django_db
def test_formats_panel_lists_three_layouts(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-templates")).content.decode()

    for layout in ("term_table", "year_grid", "plan_notes"):
        assert f'data-format="{layout}"' in html
    assert html.count("data-set-default-format") >= 3
    assert "Term-by-term table" in html
    assert "Year-at-a-glance grid" in html
    assert "Plan with advising notes" in html


def test_workspace_export_sends_format():
    root = Path(__file__).resolve().parents[2]
    workspace = (root / "agent/static/agent/js/faculty_workspace.js").read_text(encoding="utf-8")

    assert "ontrack.facultyExportFormat" in workspace
    assert "JSON.stringify({ format:" in workspace
    storage_lines = [line for line in workspace.splitlines() if "localStorage" in line]
    assert storage_lines and all(("EXPORT_FORMAT_KEY" in line or "CHAT_WIDE_KEY" in line) for line in storage_lines)


def test_export_format_preference_is_not_student_data():
    root = Path(__file__).resolve().parents[2]
    templates = (root / "agent/static/agent/js/faculty_templates.js").read_text(encoding="utf-8")

    assert "localStorage.setItem(EXPORT_FORMAT_KEY" in templates
    assert "EXPORT_LAYOUTS.includes" in templates
    forbidden = next(line for line in templates.splitlines() if line.startswith("const forbiddenStudentFields"))
    assert "facultyExportFormat" not in forbidden


@pytest.mark.django_db
def test_tab_panels_are_siblings_not_nested(client, faculty_user):
    from html.parser import HTMLParser

    client.force_login(faculty_user)
    html = client.get(reverse("faculty-templates")).content.decode()

    class Tree(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.ancestors = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "div":
                if "data-ft-panel" in attrs:
                    self.ancestors[attrs["data-ft-panel"]] = [d.get("data-ft-panel") for d in self.stack if d.get("data-ft-panel")]
                self.stack.append(attrs)

        def handle_endtag(self, tag):
            if tag == "div" and self.stack:
                self.stack.pop()

    tree = Tree()
    tree.feed(html)

    assert tree.ancestors == {"skeletons": [], "formats": []}
    assert tree.stack == [], "unbalanced <div> tags in the templates page"
