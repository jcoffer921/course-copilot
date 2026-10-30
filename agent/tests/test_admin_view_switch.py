import pytest
from django.test import override_settings
from django.urls import reverse

from agent.models import UserSettings


def make(django_user_model, name, role=UserSettings.ROLE_STUDENT, **kw):
    user = django_user_model.objects.create_user(username=name, **kw)
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=role)
    return user


@override_settings(ONTRACK_PILOT_OWNER_EMAIL="me@example.com")
@pytest.mark.django_db
def test_admin_can_switch_between_views(client, django_user_model):
    admin = make(django_user_model, "adm", email="me@example.com")
    client.force_login(admin)
    assert client.get(reverse("faculty-workspace")).status_code == 404

    response = client.post(reverse("switch-view"), {"view": "faculty"})
    assert response.status_code == 302
    assert client.get(reverse("faculty-workspace")).status_code == 200
    assert client.get(reverse("dashboard-page")).status_code == 302

    client.post(reverse("switch-view"), {"view": "student"})
    assert client.get(reverse("faculty-workspace")).status_code == 404
    assert client.get(reverse("dashboard-page")).status_code == 200


@override_settings(ONTRACK_PILOT_OWNER_EMAIL="me@example.com")
@pytest.mark.django_db
def test_staff_superuser_is_not_enough(client, django_user_model):
    user = make(django_user_model, "su", is_staff=True, is_superuser=True, email="other@example.com")
    client.force_login(user)
    assert client.post(reverse("switch-view"), {"view": "faculty"}).status_code == 404


@override_settings(ONTRACK_PILOT_OWNER_EMAIL="me@example.com")
@pytest.mark.django_db
def test_non_admin_cannot_switch(client, django_user_model):
    user = make(django_user_model, "stu")
    client.force_login(user)
    assert client.post(reverse("switch-view"), {"view": "faculty"}).status_code == 404
    assert client.get(reverse("faculty-workspace")).status_code == 404


@override_settings(ONTRACK_PILOT_OWNER_EMAIL="me@example.com")
@pytest.mark.django_db
def test_switch_button_only_shown_to_admin(client, django_user_model):
    client.force_login(make(django_user_model, "stu2"))
    assert b"Switch to" not in client.get(reverse("dashboard-page")).content
    client.force_login(make(django_user_model, "adm2", email="me@example.com"))
    assert b"Switch to faculty view" in client.get(reverse("dashboard-page")).content
