from unittest.mock import AsyncMock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from agent.services import storage
from agent.throttles import AIUserBurstThrottle


pytestmark = pytest.mark.django_db


def test_ai_endpoint_returns_429_after_per_user_burst_limit(
    tmp_path, monkeypatch, django_user_model,
):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    user = django_user_model.objects.create_user(username="limited")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [], "topics": ["A"],
    }, user)
    client = APIClient()
    client.force_authenticate(user=user)
    monkeypatch.setattr(
        "agent.views.domain_suggestions.suggest_domains",
        AsyncMock(return_value=["example.edu"]),
    )
    cache.clear()
    monkeypatch.setattr(AIUserBurstThrottle, "THROTTLE_RATES", {"ai_burst": "1/min"})

    first = client.post("/api/courses/cs101/domains/suggest/", {}, format="json")
    second = client.post("/api/courses/cs101/domains/suggest/", {}, format="json")

    assert first.status_code == 200
    assert second.status_code == 429
    assert "throttled" in second.data["detail"].code
