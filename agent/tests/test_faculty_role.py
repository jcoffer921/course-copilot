import pytest
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory, force_authenticate

from agent.authentication import FacultyPermission, is_faculty
from agent.models import UserSettings

factory = APIRequestFactory()


def _authed_request(user):
    request = factory.get("/")
    force_authenticate(request, user=user)
    request.user = user
    return request


@pytest.mark.django_db
def test_is_faculty_false_for_default_role(django_user_model):
    user = django_user_model.objects.create_user(username="student-role")
    UserSettings.objects.create(user=user)

    assert is_faculty(user) is False


@pytest.mark.django_db
def test_is_faculty_true_for_faculty_role(django_user_model):
    user = django_user_model.objects.create_user(username="faculty-role")
    UserSettings.objects.create(user=user, role=UserSettings.ROLE_FACULTY)

    assert is_faculty(user) is True


@pytest.mark.django_db
def test_faculty_permission_rejects_student_as_not_found(django_user_model):
    user = django_user_model.objects.create_user(username="student-permission")
    UserSettings.objects.create(user=user, role=UserSettings.ROLE_STUDENT)

    with pytest.raises(NotFound):
        FacultyPermission().has_permission(_authed_request(user), view=None)


@pytest.mark.django_db
def test_faculty_permission_allows_faculty(django_user_model):
    user = django_user_model.objects.create_user(username="faculty-permission")
    UserSettings.objects.create(user=user, role=UserSettings.ROLE_FACULTY)

    assert FacultyPermission().has_permission(_authed_request(user), view=None) is True


@pytest.mark.django_db
def test_role_flip_mid_session_is_rejected_on_next_request(django_user_model):
    """A faculty user demoted to student mid-session loses FacultyPermission
    on their very next request, using the same authenticated session."""
    user = django_user_model.objects.create_user(username="flip-role")
    settings_row = UserSettings.objects.create(user=user, role=UserSettings.ROLE_FACULTY)

    assert FacultyPermission().has_permission(_authed_request(user), view=None) is True

    settings_row.role = UserSettings.ROLE_STUDENT
    settings_row.save(update_fields=["role"])

    with pytest.raises(NotFound):
        FacultyPermission().has_permission(_authed_request(user), view=None)
