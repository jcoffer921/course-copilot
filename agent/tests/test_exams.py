import uuid
from datetime import datetime, timezone

import pytest

from agent.models import CourseMaterial
from agent.services import calendar_events, exams, mastery, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="exam-owner", email="exam-owner@example.com")


def _seed_syllabus(course_id, topics, dates, user, overwrite=False):
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(), "dates": dates, "grading": [], "topics": topics,
    }, user, overwrite=overwrite)


def _seed_notes(course_id, lecture_id, chunks, user):
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "source": "notes", "topics": list({c["topic"] for c in chunks}), "chunks": chunks,
    }, user)


def _material(user, course_id="cs101", *, material_type=CourseMaterial.TYPE_NOTES, source_key="lecture01", status=CourseMaterial.STATUS_READY, review=CourseMaterial.REVIEW_NOT_REQUIRED):
    return CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename=f"{source_key}.txt",
        material_type=material_type, source_key=source_key,
        storage_key=f"key-{uuid.uuid4().hex}", size_bytes=10, content_type="text/plain",
        processing_status=status, review_status=review,
    )


def _exam_event_id(course_id, user):
    return next(e["id"] for e in calendar_events.all_events(user, course_ids=[course_id]) if e["type"] == "test_quiz")


def test_find_exam_event_resolves_confirmed_test_quiz_event(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)

    event_id = _exam_event_id("cs101", user)
    event = exams.find_exam_event(user, "cs101", event_id)

    assert event["title"] == "Midterm"
    assert event["type"] == "test_quiz"


def test_find_exam_event_rejects_non_exam_event_types(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-01", "title": "Reading", "type": "class"}], user)
    non_exam_id = next(e["id"] for e in calendar_events.all_events(user, course_ids=["cs101"]))

    with pytest.raises(exams.ExamNotFoundError):
        exams.find_exam_event(user, "cs101", non_exam_id)


def test_find_exam_event_is_owner_scoped(isolated_courses_dir, user, django_user_model):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    event_id = _exam_event_id("cs101", user)

    other = django_user_model.objects.create_user(username="exam-other")
    with pytest.raises(exams.ExamNotFoundError):
        exams.find_exam_event(other, "cs101", event_id)


def test_find_exam_event_raises_after_event_is_rescheduled(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    old_event_id = _exam_event_id("cs101", user)
    exams.get_or_create_plan(user, "cs101", old_event_id)  # a plan exists for the old occurrence

    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-08", "title": "Midterm", "type": "test_quiz"}], user, overwrite=True)

    with pytest.raises(exams.ExamNotFoundError):
        exams.find_exam_event(user, "cs101", old_event_id)
    # The rescheduled occurrence gets its own (different, resolvable) id.
    new_event_id = _exam_event_id("cs101", user)
    assert new_event_id != old_event_id
    assert exams.find_exam_event(user, "cs101", new_event_id)["date"] == "2026-03-08"


def test_find_exam_event_raises_after_event_is_deleted(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    event_id = _exam_event_id("cs101", user)

    _seed_syllabus("cs101", ["Recursion"], [], user, overwrite=True)  # deadline removed entirely

    with pytest.raises(exams.ExamNotFoundError):
        exams.find_exam_event(user, "cs101", event_id)


def test_list_exams_orders_by_date_and_computes_days_until(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["A"], [
        {"date": "2026-03-10", "title": "Final", "type": "test_quiz"},
        {"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"},
        {"date": "2026-03-05", "title": "Reading", "type": "class"},
    ], user)

    result = exams.list_exams(user, "cs101", now=datetime(2026, 2, 25, tzinfo=timezone.utc))

    assert [e["title"] for e in result] == ["Midterm", "Final"]
    assert result[0]["days_until"] == 4
    assert result[1]["days_until"] == 13


def test_get_or_create_plan_defaults_to_all_topics_and_ready_owned_materials(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["A", "B"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    ready = _material(user, source_key="lecture01")
    _material(user, source_key="lecture02", status=CourseMaterial.STATUS_PROCESSING)  # not ready: excluded
    _material(user, source_key="lecture03", review=CourseMaterial.REVIEW_SUPERSEDED)  # superseded: excluded
    event_id = _exam_event_id("cs101", user)

    plan = exams.get_or_create_plan(user, "cs101", event_id)

    assert plan["included_topics"] == ["A", "B"]
    assert plan["included_material_ids"] == [str(ready.material_id)]
    assert plan["study_guide"] is None


def test_update_plan_drops_unowned_topics_and_materials(isolated_courses_dir, user, django_user_model):
    _seed_syllabus("cs101", ["A", "B"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    owned = _material(user, source_key="lecture01")
    other = django_user_model.objects.create_user(username="material-other")
    unowned = _material(other, course_id="cs101", source_key="lecture02")
    event_id = _exam_event_id("cs101", user)

    plan = exams.update_plan(
        user, "cs101", event_id,
        included_topics=["A", "Not A Real Topic"],
        included_material_ids=[str(owned.material_id), str(unowned.material_id)],
    )

    assert plan["included_topics"] == ["A"]
    assert plan["included_material_ids"] == [str(owned.material_id)]


def test_update_plan_raises_for_a_stale_or_missing_event(isolated_courses_dir, user):
    with pytest.raises(exams.ExamNotFoundError):
        exams.update_plan(user, "cs101", "not-a-real-event", included_topics=[])


def test_build_workspace_reports_countdown_and_default_readiness(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-05", "title": "Midterm", "type": "test_quiz"}], user)
    event_id = _exam_event_id("cs101", user)

    workspace = exams.build_workspace(user, "cs101", event_id, now=datetime(2026, 3, 1, tzinfo=timezone.utc))

    assert workspace["event"]["title"] == "Midterm"
    assert workspace["days_until"] == 4
    assert workspace["topics"] == [{
        "topic": "Recursion", "included": True, "status": "not_started", "score": None, "reason": "Not started yet.",
    }]
    assert workspace["weak_topics"] == workspace["topics"]  # not_started counts as needing attention
    assert workspace["readiness"]["score"] == 0
    assert workspace["readiness"]["label"] == "Just getting started"
    assert workspace["recommendation"]["topic"] == "Recursion"
    assert workspace["preparation"]["total_minutes"] > 0


def test_build_workspace_reflects_a_mastery_rebuild(isolated_courses_dir, user):
    _seed_syllabus("cs101", ["Recursion"], [{"date": "2026-03-05", "title": "Midterm", "type": "test_quiz"}], user)
    event_id = _exam_event_id("cs101", user)
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)

    before = exams.build_workspace(user, "cs101", event_id, now=now)
    assert before["topics"][0]["status"] == "not_started"

    for i in range(1, 6):
        storage.append_quiz_attempt("cs101", {"topic": "Recursion", "correct": True, "timestamp": f"2026-02-2{i}T00:00:00"}, user=user)
    mastery.rebuild_scores("cs101", user=user, now=now)

    after = exams.build_workspace(user, "cs101", event_id, now=now)
    assert after["topics"][0]["status"] == mastery.EXAM_READY
    assert after["weak_topics"] == []  # exam-ready topics don't need more practice


def test_build_workspace_is_owner_scoped(isolated_courses_dir, user, django_user_model):
    _seed_syllabus("cs101", ["A"], [{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}], user)
    event_id = _exam_event_id("cs101", user)

    other = django_user_model.objects.create_user(username="workspace-other")
    with pytest.raises(exams.ExamNotFoundError):
        exams.build_workspace(other, "cs101", event_id)


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _seed_course_material(user, course_id, lecture_id):
    return _material(user, course_id=course_id, source_key=lecture_id, status=CourseMaterial.STATUS_READY, review=CourseMaterial.REVIEW_NOT_REQUIRED)


async def test_generate_study_guide_uses_only_included_material_and_returns_citations(isolated_courses_dir, monkeypatch, django_user_model):
    from asgiref.sync import sync_to_async

    user = await sync_to_async(django_user_model.objects.create_user)(username="guide-owner", email="guide-owner@example.com")
    await sync_to_async(_seed_syllabus)("cs101", ["Recursion", "Sorting"], [
        {"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"},
    ], user)
    await sync_to_async(_seed_notes)("cs101", "lecture01", [
        {"id": "chunk1", "topic": "Recursion", "text": "A base case stops recursion."},
        {"id": "chunk2", "topic": "Sorting", "text": "Merge sort divides and conquers."},
    ], user)
    material = await sync_to_async(_seed_course_material)(user, "cs101", "lecture01")
    event_id = await sync_to_async(_exam_event_id)("cs101", user)
    await sync_to_async(exams.update_plan)(
        user, "cs101", event_id, included_topics=["Recursion"], included_material_ids=[str(material.material_id)],
    )

    response = _FakeResponse(
        '{"sections": ['
        '{"topic": "Recursion", "key_points": ["Base case stops the recursion.", "Recursive step shrinks the problem."]},'
        '{"topic": "Sorting", "key_points": ["Should never appear — Sorting was not included."]}'
        ']}'
    )
    monkeypatch.setattr(exams, "get_client", lambda: _FakeClient(response))

    guide = await exams.generate_study_guide(user, "cs101", event_id)

    assert [s["topic"] for s in guide["sections"]] == ["Recursion"]  # excluded topic's section is dropped
    assert guide["sections"][0]["key_points"] == ["Base case stops the recursion.", "Recursive step shrinks the problem."]
    citation = guide["sections"][0]["citation"]
    assert citation["material_id"] == str(material.material_id)
    assert citation["lecture_id"] == "lecture01"

    saved_plan = await sync_to_async(exams.get_or_create_plan)(user, "cs101", event_id)
    assert saved_plan["study_guide"] == guide


async def test_generate_study_guide_raises_when_no_topics_selected(isolated_courses_dir, monkeypatch, django_user_model):
    from asgiref.sync import sync_to_async

    user = await sync_to_async(django_user_model.objects.create_user)(username="empty-plan-owner")
    await sync_to_async(_seed_syllabus)("cs101", ["Recursion"], [
        {"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"},
    ], user)
    event_id = await sync_to_async(_exam_event_id)("cs101", user)
    await sync_to_async(exams.update_plan)(user, "cs101", event_id, included_topics=[])

    with pytest.raises(exams.NoStudyMaterialSelectedError):
        await exams.generate_study_guide(user, "cs101", event_id)


async def test_generate_study_guide_raises_when_included_topics_have_no_included_material(isolated_courses_dir, monkeypatch, django_user_model):
    from asgiref.sync import sync_to_async

    user = await sync_to_async(django_user_model.objects.create_user)(username="no-material-owner")
    await sync_to_async(_seed_syllabus)("cs101", ["Recursion"], [
        {"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"},
    ], user)
    await sync_to_async(_seed_notes)("cs101", "lecture01", [
        {"id": "chunk1", "topic": "Recursion", "text": "A base case stops recursion."},
    ], user)
    # Material exists but is never included in the plan.
    await sync_to_async(_seed_course_material)(user, "cs101", "lecture01")
    event_id = await sync_to_async(_exam_event_id)("cs101", user)
    await sync_to_async(exams.update_plan)(user, "cs101", event_id, included_topics=["Recursion"], included_material_ids=[])

    with pytest.raises(exams.NoStudyMaterialSelectedError):
        await exams.generate_study_guide(user, "cs101", event_id)
