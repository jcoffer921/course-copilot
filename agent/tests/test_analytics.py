import csv
import io
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agent.models import LlmUsage, QuizAttempt, StudyActivity, StudySession, UserSettings


def activate(user, status=UserSettings.ACCESS_ACTIVE):
    UserSettings.objects.create(user=user, access_status=status, tier=UserSettings.TIER_PILOT)


@pytest.fixture
def analytics_users(django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    student_a = django_user_model.objects.create_user(username="student-a", email="a@example.com")
    student_b = django_user_model.objects.create_user(username="student-b", email="b@example.com")
    activate(owner)
    activate(student_a)
    activate(student_b, UserSettings.ACCESS_PENDING)
    return owner, student_a, student_b


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="owner@example.com")
def test_analytics_is_owner_only_at_page_api_export_and_navigation(client, analytics_users):
    owner, student_a, student_b = analytics_users

    client.force_login(owner)
    assert client.get(reverse("analytics-page")).status_code == 200
    assert client.get(reverse("analytics-summary")).status_code == 200
    assert client.get(reverse("analytics-export")).status_code == 200
    assert "Analytics" in client.get(reverse("dashboard-page")).content.decode()

    for student in (student_a, student_b):
        UserSettings.objects.filter(user=student).update(access_status=UserSettings.ACCESS_ACTIVE)
        client.force_login(student)
        assert client.get(reverse("analytics-page")).status_code == 404
        assert client.get(reverse("analytics-summary")).status_code == 404
        assert client.get(reverse("analytics-export")).status_code == 404
        assert "Analytics" not in client.get(reverse("dashboard-page")).content.decode()

    client.logout()
    assert client.get(reverse("analytics-page")).status_code == 302
    assert client.get(reverse("analytics-summary")).status_code == 401
    assert client.get(reverse("analytics-export")).status_code == 401


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="owner@example.com")
def test_summary_uses_real_student_activity_and_excludes_owner(analytics_users):
    owner, student, pending = analytics_users
    now = timezone.now()
    owner_session = StudySession.objects.create(user=owner, course_id="owner-course", mode="mixed")
    student_session = StudySession.objects.create(user=student, course_id="cs101", mode="mixed")
    StudyActivity.objects.create(session=student_session, kind=StudyActivity.KIND_FLASHCARD_REVIEWED, position=0)
    QuizAttempt.objects.create(
        user=student, course_id="cs101", lecture_id="l1", chunk_id="c1", topic="Recursion",
        question="q", correct_answer="a", user_answer="a", correct=True, timestamp=now.isoformat(),
    )
    QuizAttempt.objects.create(
        user=owner, course_id="owner-course", lecture_id="l1", chunk_id="c1", topic="Owner",
        question="q", correct_answer="a", user_answer="a", correct=True, timestamp=now.isoformat(),
    )
    LlmUsage.objects.create(user=student, date=timezone.localdate(), count=3)
    LlmUsage.objects.create(user=owner, date=timezone.localdate(), count=99)

    api = APIClient()
    api.force_authenticate(owner)
    response = api.get(reverse("analytics-summary"), {"range": "7d"})

    assert response.status_code == 200
    data = response.json()
    assert data["access_status"] == {"pending": 1, "active": 1, "suspended": 0, "total": 2}
    assert data["metrics"]["active_students"] == 1
    assert data["metrics"]["study_sessions"] == 1
    assert data["metrics"]["questions_answered"] == 1
    assert data["metrics"]["llm_requests"] == 3
    assert data["engagement"]["flashcards"] == 1
    assert all(row["course_id"] != "owner-course" for row in data["courses"])


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="owner@example.com")
def test_export_is_per_student_private_and_date_scoped(analytics_users):
    owner, student, pending = analytics_users
    now = timezone.now()
    QuizAttempt.objects.create(
        user=student, course_id="cs101", lecture_id="l1", chunk_id="c1", topic="Recursion",
        question="private question", correct_answer="private answer", user_answer="private response",
        correct=True, timestamp=now.isoformat(),
    )
    QuizAttempt.objects.create(
        user=student, course_id="cs101", lecture_id="l1", chunk_id="c2", topic="Old",
        question="old", correct_answer="old", user_answer="old", correct=False,
        timestamp=(now - timedelta(days=40)).isoformat(),
    )
    api = APIClient()
    api.force_authenticate(owner)

    response = api.get(reverse("analytics-export"), {"range": "30d"})
    rows = list(csv.DictReader(io.StringIO(response.content.decode())))

    assert response.status_code == 200
    assert len(rows) == 2
    student_row = next(row for row in rows if row["student_id"] == str(student.pk))
    assert student_row["questions_answered"] == "1"
    output = response.content.decode()
    assert "private question" not in output
    assert "private answer" not in output
    assert "private response" not in output
    assert owner.email not in output


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="owner@example.com")
def test_invalid_analytics_range_is_rejected(analytics_users):
    owner, *_ = analytics_users
    api = APIClient()
    api.force_authenticate(owner)
    assert api.get(reverse("analytics-summary"), {"range": "custom"}).status_code == 400
    assert api.get(reverse("analytics-export"), {"range": "custom"}).status_code == 400


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="")
def test_empty_owner_configuration_exposes_no_analytics_navigation(client, django_user_model):
    user = django_user_model.objects.create_user(username="email-less-owner", email="")
    activate(user)
    client.force_login(user)

    assert client.get(reverse("analytics-page")).status_code == 404
    assert "Analytics" not in client.get(reverse("dashboard-page")).content.decode()


@pytest.mark.django_db
@override_settings(ONTRACK_PILOT_OWNER_EMAIL="duplicate@example.com")
def test_duplicate_owner_email_configuration_fails_closed(client, django_user_model):
    first = django_user_model.objects.create_user(username="first-owner", email="duplicate@example.com")
    second = django_user_model.objects.create_user(username="second-owner", email="DUPLICATE@example.com")
    activate(first)
    activate(second)

    for user in (first, second):
        client.force_login(user)
        assert client.get(reverse("analytics-page")).status_code == 404
        assert client.get(reverse("analytics-summary")).status_code == 404
