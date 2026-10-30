import hashlib
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from agent.models import GoogleAccount, UserSettings


pytestmark = pytest.mark.django_db

TEST_CODE = "FACULTY-TEST-2026"
TEST_CODE_HASH = hashlib.sha256(TEST_CODE.encode()).hexdigest()


def oauth_flow():
    flow = MagicMock()
    flow.credentials = MagicMock(
        id_token="faculty-id-token",
        token="faculty-access-token",
        refresh_token="faculty-refresh-token",
        expiry=datetime(2026, 12, 31),
    )
    return flow


@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE=TEST_CODE)
def test_faculty_access_page_renders_code_form_and_local_demo_code(client):
    response = client.get(reverse("faculty-access"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Faculty access" in html
    assert 'name="access_code"' in html
    assert "Continue with Google" in html
    assert TEST_CODE in html


@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_faculty_access_rejects_invalid_code_without_creating_grant(client):
    response = client.post(reverse("faculty-access"), {"access_code": "wrong-code"})

    assert response.status_code == 400
    assert "That faculty access code is not valid" in response.content.decode()
    assert "faculty_access_granted_at" not in client.session


@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_valid_faculty_code_starts_google_flow_with_faculty_destination(client):
    response = client.post(reverse("faculty-access"), {"access_code": TEST_CODE})

    assert response.status_code == 302
    assert response.url == f'{reverse("google-login-start")}?next=%2Ffaculty%2F'
    assert client.session["faculty_access_granted_at"] > 0


@pytest.mark.django_db
@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_valid_faculty_code_promotes_authenticated_non_suspended_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="faculty-code-upgrade")
    settings_row = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_PENDING)
    client.force_login(user)

    response = client.post(reverse("faculty-access"), {"access_code": TEST_CODE})

    settings_row.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("faculty-workspace")
    assert settings_row.access_status == UserSettings.ACCESS_ACTIVE
    assert settings_row.role == UserSettings.ROLE_FACULTY


@pytest.mark.django_db
@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_faculty_code_cannot_reactivate_suspended_user(client, django_user_model):
    user = django_user_model.objects.create_user(username="suspended-faculty-code")
    settings_row = UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_SUSPENDED)
    client.force_login(user)

    response = client.post(reverse("faculty-access"), {"access_code": TEST_CODE})

    settings_row.refresh_from_db()
    assert response.status_code == 403
    assert settings_row.access_status == UserSettings.ACCESS_SUSPENDED
    assert settings_row.role == UserSettings.ROLE_STUDENT


@pytest.mark.django_db
@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_google_callback_applies_recent_faculty_grant_to_new_account(client):
    session = client.session
    session["google_oauth_state"] = "faculty-state"
    session["google_oauth_code_verifier"] = "faculty-verifier"
    session["faculty_access_granted_at"] = timezone.now().timestamp() - 100
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = oauth_flow()
        verify_id_token.return_value = {
            "sub": "faculty-code-sub",
            "email": "faculty-code@example.com",
            "email_verified": True,
            "name": "Faculty Code",
        }
        response = client.get(reverse("google-callback"), {"state": "faculty-state", "code": "abc"})

    account = GoogleAccount.objects.get(google_sub="faculty-code-sub")
    settings_row = UserSettings.objects.get(user=account.user)
    assert response.status_code == 302
    assert response.url == reverse("faculty-workspace")
    assert settings_row.access_status == UserSettings.ACCESS_ACTIVE
    assert settings_row.role == UserSettings.ROLE_FACULTY
    assert "faculty_access_granted_at" not in client.session


@pytest.mark.django_db
@override_settings(FACULTY_ACCESS_CODE_HASH=TEST_CODE_HASH, FACULTY_DEMO_ACCESS_CODE="")
def test_google_callback_does_not_apply_expired_faculty_grant(client):
    session = client.session
    session["google_oauth_state"] = "expired-state"
    session["google_oauth_code_verifier"] = "expired-verifier"
    session["faculty_access_granted_at"] = timezone.now().timestamp() - 1_000
    session.save()

    with patch("agent.auth_views.google_oauth.build_flow") as build_flow, \
         patch("agent.auth_views.google_oauth.verify_id_token") as verify_id_token:
        build_flow.return_value = oauth_flow()
        verify_id_token.return_value = {
            "sub": "expired-faculty-sub",
            "email": "expired-faculty@example.com",
            "email_verified": True,
        }
        response = client.get(reverse("google-callback"), {"state": "expired-state", "code": "abc"})

    account = GoogleAccount.objects.get(google_sub="expired-faculty-sub")
    settings_row = UserSettings.objects.get(user=account.user)
    assert response.status_code == 302
    assert settings_row.role == UserSettings.ROLE_STUDENT
    assert "faculty_access_granted_at" not in client.session


def test_signup_page_links_to_faculty_access(client):
    html = client.get(reverse("signup-page")).content.decode()

    assert reverse("faculty-access") in html
    assert "Signing up as faculty?" in html
