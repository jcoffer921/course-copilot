from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import Throttled
from rest_framework.test import APIClient

from agent.models import LlmUsage, UserSettings
from agent.services import entitlements, llm_usage

AI_ROUTES = [
    "/api/courses/cs101/quiz/generate/",
    "/api/courses/cs101/flashcards/generate/",
]


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    from agent.services import storage
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_two_users_llm_usage_counts_never_interfere(django_user_model):
    user_a = django_user_model.objects.create_user(username="llm-user-a")
    user_b = django_user_model.objects.create_user(username="llm-user-b")

    llm_usage.check_and_increment(user_a)
    llm_usage.check_and_increment(user_a)
    llm_usage.check_and_increment(user_b)

    assert LlmUsage.objects.get(user=user_a).count == 2
    assert LlmUsage.objects.get(user=user_b).count == 1


@pytest.mark.django_db
def test_llm_usage_rolls_over_at_calendar_day_not_rolling_24h(django_user_model):
    """A user who was at the cap yesterday gets a fresh count today — the
    limit resets at the calendar-day boundary, not on a rolling 24 hours
    since their last request."""
    user = django_user_model.objects.create_user(username="llm-day-boundary-user")
    yesterday = timezone.localdate() - timedelta(days=1)
    LlmUsage.objects.create(user=user, date=yesterday, count=entitlements.DAILY_REQUEST_LIMIT)

    llm_usage.check_and_increment(user)

    assert LlmUsage.objects.get(user=user, date=yesterday).count == entitlements.DAILY_REQUEST_LIMIT
    assert LlmUsage.objects.get(user=user, date=timezone.localdate()).count == 1


@pytest.mark.django_db
def test_check_and_increment_raises_throttled_over_limit_without_incrementing(django_user_model):
    user = django_user_model.objects.create_user(username="llm-over-limit-user")
    LlmUsage.objects.create(user=user, date=timezone.localdate(), count=entitlements.DAILY_REQUEST_LIMIT)

    with pytest.raises(Throttled):
        llm_usage.check_and_increment(user)

    assert LlmUsage.objects.get(user=user).count == entitlements.DAILY_REQUEST_LIMIT


@pytest.mark.django_db
@pytest.mark.parametrize("route", AI_ROUTES)
def test_over_limit_user_gets_429_on_ai_routes(isolated_courses_dir, django_user_model, route):
    user = django_user_model.objects.create_user(username="llm-http-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    LlmUsage.objects.create(user=user, date=timezone.localdate(), count=entitlements.DAILY_REQUEST_LIMIT)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(route, {}, format="json")

    assert response.status_code == 429


@pytest.mark.django_db
def test_over_limit_user_still_gets_200_on_read_only_route(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="llm-readonly-user")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    LlmUsage.objects.create(user=user, date=timezone.localdate(), count=entitlements.DAILY_REQUEST_LIMIT)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/dashboard/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_llm_usage_command_prints_accurate_counts(django_user_model, capsys):
    from django.core.management import call_command

    user = django_user_model.objects.create_user(username="llm-command-user", email="cmd@example.com")
    LlmUsage.objects.create(user=user, date=timezone.localdate(), count=7)

    call_command("llm_usage")

    output = capsys.readouterr().out
    assert "cmd@example.com: 7" in output


@pytest.mark.django_db
def test_llm_usage_command_reports_no_usage(capsys):
    from django.core.management import call_command

    call_command("llm_usage")

    output = capsys.readouterr().out
    assert "No LLM requests recorded" in output
