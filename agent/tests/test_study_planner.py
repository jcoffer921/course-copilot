import json

import pytest
from asgiref.sync import sync_to_async

from agent.models import CourseMaterial
from agent.services import material_files, storage, study_planner

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
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


def _seed_course(course_id, topics, user):
    # Mirrors test_recommendations.py's seeding: a course needs a confirmed
    # syllabus AND a grounded (CourseMaterial-backed) note chunk per topic
    # before recommendations.rank_recommendations() will surface it —
    # study_planner.build_context() is a thin composition over that same
    # deterministic ranking, so it needs the same fixture shape.
    syllabus = {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": [], "grading": [], "topics": topics,
    }
    storage.write_syllabus(course_id, syllabus, user)
    storage_key = material_files.object_storage.save(user, course_id, ".pdf", b"%PDF-test")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename=f"{course_id}-syllabus.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS, source_key="syllabus",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_CONFIRMED,
        storage_key=storage_key, size_bytes=9, content_type="application/pdf", extracted_data=syllabus,
    )
    lecture_id = f"{course_id}-content"
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "topics": topics,
        "chunks": [
            {"id": f"topic-{i}", "topic": topic, "text": f"Processed content about {topic}."}
            for i, topic in enumerate(topics, start=1)
        ],
    }, user)
    notes_key = material_files.object_storage.save(user, course_id, ".docx", b"course-content")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="content.docx",
        material_type=CourseMaterial.TYPE_NOTES, source_key=lecture_id,
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=notes_key, size_bytes=14,
    )


async def test_build_context_is_pure_and_composes_existing_services(django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="planner-context-owner")
    await sync_to_async(_seed_course)("cs101", ["Recursion"], user)

    context = await sync_to_async(study_planner.build_context)(user, available_minutes=90)

    assert context["available_minutes"] == 90
    assert {"course_id": "cs101", "course_name": "CS101"} in context["courses"]
    assert any(r["topic"] == "Recursion" for r in context["recommendations"])
    assert "current_streak_days" in context


async def test_generate_plan_raises_when_no_courses_exist(django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="no-courses-owner")

    with pytest.raises(study_planner.NoStudyContextError):
        await study_planner.generate_plan(user)


async def test_generate_plan_drops_items_referencing_a_course_not_in_context(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="grounding-owner")
    await sync_to_async(_seed_course)("cs101", ["Recursion"], user)
    payload = json.dumps({
        "plan": [
            {"course_id": "cs101", "topic": "Recursion", "activity": "Practice quiz", "minutes": 30, "reason": "Weakest topic.", "priority": 1},
            {"course_id": "math999", "topic": "Made Up Topic", "activity": "Review", "minutes": 20, "reason": "Invented.", "priority": 2},
        ],
        "summary": "Focus on recursion tonight.",
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(study_planner, "get_client", lambda: fake)

    result = await study_planner.generate_plan(user, available_minutes=60)

    assert len(result["plan"]) == 1
    assert result["plan"][0]["course_id"] == "cs101"
    assert result["plan"][0]["course_name"] == "CS101"
    assert result["summary"] == "Focus on recursion tonight."


async def test_generate_plan_drops_items_with_an_unrecommended_topic_for_a_valid_course(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="topic-grounding-owner")
    await sync_to_async(_seed_course)("cs101", ["Recursion"], user)
    payload = json.dumps({
        "plan": [{"course_id": "cs101", "topic": "Quantum Computing", "activity": "Study", "minutes": 20, "reason": "invented", "priority": 1}],
        "summary": "s",
    })
    fake = _FakeClient(_FakeResponse(payload))
    monkeypatch.setattr(study_planner, "get_client", lambda: fake)

    result = await study_planner.generate_plan(user)

    assert result["plan"] == []


async def test_generate_plan_uses_the_reasoning_model(monkeypatch, django_user_model, isolated_courses_dir):
    user = await sync_to_async(django_user_model.objects.create_user)(username="model-check-owner")
    await sync_to_async(_seed_course)("cs101", ["Recursion"], user)
    fake = _FakeClient(_FakeResponse(json.dumps({"plan": [], "summary": "s"})))
    monkeypatch.setattr(study_planner, "get_client", lambda: fake)

    await study_planner.generate_plan(user)

    assert fake.messages.calls[0]["model"] == study_planner.CORA_MODELS["reasoning"]
