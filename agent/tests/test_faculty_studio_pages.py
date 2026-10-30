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
