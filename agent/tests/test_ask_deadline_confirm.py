"""
ask.confirm_deadline_actions is the only path that lets a Cora conversation
actually write to the calendar — these are plain service-layer tests (no
live API key needed) covering the create/update/delete orchestration and,
critically, that event_id ownership is re-resolved server-side rather than
trusted from the caller.
"""

import pytest
from django.contrib.auth.models import User

from agent.serializers import ConfirmDeadlineActionsRequestSerializer
from agent.services import ask, calendar_events, custom_events, sessions, storage

pytestmark = pytest.mark.django_db


def _create_action(n):
    return {"action": "create", "title": f"Class {n}", "date": "2026-09-14"}


def test_confirm_serializer_accepts_a_full_semester_mwf_schedule():
    # Regression: a real MWF schedule across ask.py's CLASS_SCHEDULE_WEEKS (15
    # weeks x 3 meetings) proposes ~45 items in one confirmation — an earlier,
    # arbitrarily low cap (20) rejected this exact legitimate case, confirmed
    # via manual repro in a live session (43 items).
    serializer = ConfirmDeadlineActionsRequestSerializer(data={"actions": [_create_action(n) for n in range(45)]})
    assert serializer.is_valid(), serializer.errors


def test_confirm_serializer_rejects_absurd_batch_size():
    serializer = ConfirmDeadlineActionsRequestSerializer(data={"actions": [_create_action(n) for n in range(151)]})
    assert not serializer.is_valid()
    assert "actions" in serializer.errors


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user():
    return User.objects.create_user(username="cora-calendar-user")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other-calendar-user")


def _seed_syllabus(course_id, user, dates=None):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(), "dates": dates or [], "topics": [],
    }, user)


def _seed_session(course_id, user):
    return sessions.create_session(course_id, user=user)["session_id"]


def test_confirm_create_writes_event_and_appends_message(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)

    updated = ask.confirm_deadline_actions("cs101", session_id, [
        {"action": "create", "title": "Project 1", "date": "2026-09-14", "type": "project"},
    ], user=user)

    events = custom_events.list_events(user=user)
    assert len(events) == 1
    assert events[0]["title"] == "Project 1"
    assert events[0]["date"] == "2026-09-14"
    assert updated["messages"][-1]["role"] == "assistant"
    assert "Project 1" in updated["messages"][-1]["content"]


def test_confirm_create_requires_title_and_date(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)

    with pytest.raises(ValueError):
        ask.confirm_deadline_actions("cs101", session_id, [{"action": "create", "title": "", "date": "2026-09-14"}], user=user)


def test_confirm_update_manual_event(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)
    event = custom_events.create_event("cs101", "2026-09-14", None, "Project 1", "project", user=user)

    updated = ask.confirm_deadline_actions("cs101", session_id, [
        {"action": "update", "event_id": event["id"], "date": "2026-09-20"},
    ], user=user)

    events = custom_events.list_events(user=user)
    assert len(events) == 1
    assert events[0]["date"] == "2026-09-20"
    assert events[0]["title"] == "Project 1"  # unchanged field preserved
    assert "Updated" in updated["messages"][-1]["content"]


def test_confirm_delete_manual_event(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)
    event = custom_events.create_event("cs101", "2026-09-14", None, "Project 1", "project", user=user)

    updated = ask.confirm_deadline_actions("cs101", session_id, [
        {"action": "delete", "event_id": event["id"]},
    ], user=user)

    assert custom_events.list_events(user=user) == []
    assert "Removed" in updated["messages"][-1]["content"]


def test_confirm_delete_syllabus_event_is_blocked(isolated_courses_dir, user):
    _seed_syllabus("cs101", user, dates=[{"date": "2026-09-14", "title": "Project 1", "type": "project"}])
    session_id = _seed_session("cs101", user)
    syllabus_event = calendar_events.all_events(user, course_ids=["cs101"])[0]

    with pytest.raises(ValueError, match="can't be deleted"):
        ask.confirm_deadline_actions("cs101", session_id, [
            {"action": "delete", "event_id": syllabus_event["id"]},
        ], user=user)
    assert custom_events.list_events(user=user) == []  # nothing written


def test_confirm_update_syllabus_event_creates_override(isolated_courses_dir, user):
    _seed_syllabus("cs101", user, dates=[{"date": "2026-09-14", "title": "Project 1", "type": "project"}])
    session_id = _seed_session("cs101", user)
    syllabus_event = calendar_events.all_events(user, course_ids=["cs101"])[0]

    ask.confirm_deadline_actions("cs101", session_id, [
        {"action": "update", "event_id": syllabus_event["id"], "date": "2026-09-21"},
    ], user=user)

    events = custom_events.list_events(user=user)
    assert len(events) == 1
    assert events[0]["date"] == "2026-09-21"
    assert events[0]["title"] == "Project 1"
    assert events[0]["replaces_syllabus_key"] == syllabus_event["key"]


def test_confirm_update_unknown_event_raises_not_found(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)

    with pytest.raises(custom_events.EventNotFoundError):
        ask.confirm_deadline_actions("cs101", session_id, [
            {"action": "update", "event_id": "nope", "date": "2026-09-21"},
        ], user=user)


def test_confirm_cannot_touch_another_users_event(isolated_courses_dir, user, other_user):
    _seed_syllabus("cs101", user)
    _seed_syllabus("cs101", other_user)
    session_id = _seed_session("cs101", user)
    other_event = custom_events.create_event("cs101", "2026-09-14", None, "Someone else's project", "project", user=other_user)

    with pytest.raises(custom_events.EventNotFoundError):
        ask.confirm_deadline_actions("cs101", session_id, [
            {"action": "delete", "event_id": other_event["id"]},
        ], user=user)
    # the other user's event is untouched
    assert len(custom_events.list_events(user=other_user)) == 1


def test_confirm_missing_session_raises(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)

    with pytest.raises(sessions.SessionNotFoundError):
        ask.confirm_deadline_actions("cs101", "nope", [
            {"action": "create", "title": "X", "date": "2026-09-14"},
        ], user=user)


def test_normalize_pending_deadline_defaults_action_to_create():
    normalized = ask._normalize_pending_deadline({"title": "HW1", "date": "2026-09-14"}, "cs101")

    assert normalized["action"] == "create"
    assert normalized["event_id"] is None
    assert normalized["course_id"] == "cs101"


def test_normalize_pending_deadline_preserves_action_and_event_id():
    normalized = ask._normalize_pending_deadline(
        {"action": "delete", "event_id": "abc123", "title": "Quiz 2", "date": "2026-09-14"}, "cs101",
    )

    assert normalized["action"] == "delete"
    assert normalized["event_id"] == "abc123"


def test_normalize_pending_deadline_rejects_unknown_action():
    normalized = ask._normalize_pending_deadline({"action": "explode", "title": "X", "date": "2026-09-14"}, "cs101")

    assert normalized["action"] == "create"  # falls back safely rather than propagating garbage


def test_confirm_batch_multiple_creates(isolated_courses_dir, user):
    _seed_syllabus("cs101", user)
    session_id = _seed_session("cs101", user)

    updated = ask.confirm_deadline_actions("cs101", session_id, [
        {"action": "create", "title": "Mon class", "date": "2026-09-14", "type": "class"},
        {"action": "create", "title": "Wed class", "date": "2026-09-16", "type": "class"},
    ], user=user)

    events = custom_events.list_events(user=user)
    assert len(events) == 2
    content = updated["messages"][-1]["content"]
    assert "Mon class" in content and "Wed class" in content
