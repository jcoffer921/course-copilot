import json
import time

import pytest
from django.contrib.sessions.models import Session
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from agent.models import ProgramRequirement, UserSettings
from agent.services import plan_state


@pytest.fixture
def faculty_user(django_user_model):
    user = django_user_model.objects.create_user(username="plan-state-faculty")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE, role=UserSettings.ROLE_FACULTY)
    return user


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="plan-state-other")


STATE = {"program_requirement_id": "p1", "student_details": {"name": "x"}, "conversation": [], "draft_plan": None}


@pytest.mark.django_db
def test_read_is_none_when_nothing_was_written(faculty_user):
    assert plan_state.read(faculty_user) is None


@pytest.mark.django_db
def test_write_then_read_round_trips(faculty_user):
    plan_state.write(faculty_user, STATE)

    assert plan_state.read(faculty_user) == STATE


@pytest.mark.django_db
def test_state_is_per_user(faculty_user, other_user):
    plan_state.write(faculty_user, STATE)

    assert plan_state.read(other_user) is None


@pytest.mark.django_db
def test_clear_removes_the_state(faculty_user):
    plan_state.write(faculty_user, STATE)

    plan_state.clear(faculty_user)

    assert plan_state.read(faculty_user) is None


def test_default_ttl_is_thirty_minutes():
    assert plan_state.DEFAULT_TTL_SECONDS == 1800
    assert plan_state.ttl_seconds() == 1800


@override_settings(FACULTY_PLAN_STATE_TTL_SECONDS=120)
def test_ttl_can_be_overridden_in_settings():
    assert plan_state.ttl_seconds() == 120


@pytest.mark.django_db
def test_state_expires_after_the_idle_ttl(faculty_user, monkeypatch):
    start = time.time()
    plan_state.write(faculty_user, STATE)

    monkeypatch.setattr(time, "time", lambda: start + plan_state.ttl_seconds() - 5)
    assert plan_state.read(faculty_user) == STATE

    monkeypatch.setattr(time, "time", lambda: start + plan_state.ttl_seconds() + 5)
    assert plan_state.read(faculty_user) is None


@pytest.mark.django_db
def test_a_new_write_extends_the_idle_window(faculty_user, monkeypatch):
    start = time.time()
    plan_state.write(faculty_user, STATE)
    ttl = plan_state.ttl_seconds()

    monkeypatch.setattr(time, "time", lambda: start + ttl - 60)
    plan_state.write(faculty_user, {**STATE, "conversation": [{"role": "user", "content": "hi"}]})

    monkeypatch.setattr(time, "time", lambda: start + ttl + 60)
    assert plan_state.read(faculty_user) is not None


# ---- the whole point: student state never reaches django_session ----


def _program(user):
    return ProgramRequirement.objects.create(
        user=user, program_name="B.S. Test", catalog_year="2026",
        requirements={"program_name": "B.S. Test", "catalog_year": "2026", "total_credits_required": 0, "categories": []},
    )


def _session_dump():
    return json.dumps([row.get_decoded() for row in Session.objects.all()])


@pytest.mark.django_db
def test_chat_keeps_student_state_in_the_cache_not_the_session_table(faculty_user, monkeypatch):
    secret = "SECRET-STUDENT-PELICAN-5512"
    program = _program(faculty_user)

    async def fake_plan_chat(requirements, student_details, conversation, message, user):
        return {"reply": "ok", "student_details": {"name": secret}, "draft_plan": None}

    from agent import views

    monkeypatch.setattr(views.academic_planner, "plan_chat_async", fake_plan_chat)
    client = APIClient()
    client.force_authenticate(user=faculty_user)

    response = client.post(
        "/api/faculty/plan/chat/",
        {"program_requirement_id": str(program.requirement_id), "message": f"about {secret}"},
        format="json",
    )

    assert response.status_code == 200
    assert secret in json.dumps(plan_state.read(faculty_user))
    assert secret not in _session_dump()
    assert "faculty_plan_session" not in _session_dump()


@pytest.mark.django_db
def test_logout_clears_the_plan_state(client, faculty_user):
    plan_state.write(faculty_user, STATE)
    client.force_login(faculty_user)

    response = client.post(reverse("google-logout"))

    assert response.status_code == 302
    assert plan_state.read(faculty_user) is None


@pytest.mark.django_db
def test_workspace_tells_the_browser_how_long_state_lives(client, faculty_user):
    client.force_login(faculty_user)

    html = client.get(reverse("faculty-workspace")).content.decode()

    assert 'data-state-ttl="1800"' in html
