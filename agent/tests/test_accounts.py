import pytest

from agent.services import accounts, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_delete_account_requires_exact_confirmation(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner")

    with pytest.raises(ValueError):
        accounts.delete_account(user, "delete")

    assert django_user_model.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_delete_account_removes_only_owners_storage(isolated_courses_dir, django_user_model):
    owner = django_user_model.objects.create_user(username="owner")
    other = django_user_model.objects.create_user(username="other")
    storage.write_course_draft("mine", "Mine", owner)
    storage.write_course_draft("theirs", "Theirs", other)

    accounts.delete_account(owner, accounts.ACCOUNT_DELETE_CONFIRMATION)

    assert not django_user_model.objects.filter(pk=owner.pk).exists()
    assert django_user_model.objects.filter(pk=other.pk).exists()
    assert not (isolated_courses_dir / str(owner.pk)).exists()
    assert (isolated_courses_dir / str(other.pk) / "theirs" / "course.json").exists()


@pytest.mark.django_db
def test_profile_delete_cannot_target_another_user(isolated_courses_dir, django_user_model):
    from rest_framework.test import APIClient

    owner = django_user_model.objects.create_user(username="owner")
    other = django_user_model.objects.create_user(username="other")
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.delete(
        "/api/profile/",
        {"confirmation": accounts.ACCOUNT_DELETE_CONFIRMATION, "user_id": other.pk},
        format="json",
    )

    assert response.status_code == 204
    assert not django_user_model.objects.filter(pk=owner.pk).exists()
    assert django_user_model.objects.filter(pk=other.pk).exists()


@pytest.mark.django_db
def test_account_export_contains_only_requesting_users_data_and_no_credentials(isolated_courses_dir, django_user_model):
    from agent.models import GoogleCalendarConnection

    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    other = django_user_model.objects.create_user(username="other", email="other@example.com")
    storage.write_course_draft("mine", "Mine", owner)
    storage.write_course_draft("theirs", "Theirs", other)
    GoogleCalendarConnection.objects.create(
        user=owner, access_token="secret-access", refresh_token="secret-refresh",
        token_expiry="2030-01-01T00:00:00Z",
    )

    payload = accounts.serialize_export(accounts.export_account_data(owner))

    assert '"course_id": "mine"' in payload
    assert "theirs" not in payload
    assert "other@example.com" not in payload
    assert "secret-access" not in payload
    assert "secret-refresh" not in payload


@pytest.mark.django_db
def test_profile_export_endpoint_is_current_user_scoped(isolated_courses_dir, django_user_model):
    from rest_framework.test import APIClient

    owner = django_user_model.objects.create_user(username="owner")
    other = django_user_model.objects.create_user(username="other")
    storage.write_course_draft("private", "Private", owner)
    client = APIClient(); client.force_authenticate(user=other)

    response = client.get("/api/profile/export/")

    assert response.status_code == 200
    assert b"private" not in response.content


@pytest.mark.django_db
def test_profile_summary_counts_only_authenticated_users_courses(isolated_courses_dir, django_user_model):
    from rest_framework.test import APIClient

    owner = django_user_model.objects.create_user(username="summary-owner")
    other = django_user_model.objects.create_user(username="summary-other")
    storage.write_course_draft("mine", "Mine", owner)
    storage.write_course_draft("theirs", "Theirs", other)
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.get("/api/profile/")

    assert response.status_code == 200
    assert response.data["courses_enrolled"] == 1
    assert response.data["quizzes_completed"] == 0
    assert response.data["material_file_count"] == 0
    assert response.data["material_storage_bytes"] == 0


@pytest.mark.django_db
def test_notification_channel_patch_is_current_user_scoped(django_user_model):
    from agent.models import UserSettings
    from rest_framework.test import APIClient

    owner = django_user_model.objects.create_user(username="notification-owner")
    other = django_user_model.objects.create_user(username="notification-other")
    UserSettings.objects.create(user=other, notifications_enabled=False, email_notifications_enabled=False)
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.patch(
        "/api/profile/",
        {"notifications_enabled": True, "email_notifications_enabled": True},
        format="json",
    )

    assert response.status_code == 200
    assert UserSettings.objects.get(user=owner).notifications_enabled is True
    assert UserSettings.objects.get(user=owner).email_notifications_enabled is True
    other_settings = UserSettings.objects.get(user=other)
    assert other_settings.notifications_enabled is False
    assert other_settings.email_notifications_enabled is False
