from datetime import datetime, timedelta, timezone

import pytest

from agent.models import CourseMaterial
from agent.services import mastery, material_files, recommendations, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="owner", email="owner@example.com")


def _seed_course(course_id, topics, grading=None, dates=None, user=None):
    syllabus = {
        "course_id": course_id,
        "course_name": course_id.upper(),
        "dates": dates or [],
        "grading": grading or [],
        "topics": topics,
    }
    storage.write_syllabus(course_id, syllabus, user)
    storage_key = material_files.object_storage.save(user, course_id, ".pdf", b"%PDF-test")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename=f"{course_id}-syllabus.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS, source_key="syllabus",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_CONFIRMED,
        storage_key=storage_key, size_bytes=9, content_type="application/pdf", extracted_data=syllabus,
    )
    lecture_id = f"{course_id}-recommendation-content"
    storage.write_notes(course_id, lecture_id, {
        "lecture_id": lecture_id, "topics": topics,
        "chunks": [
            {"id": f"topic-{index}", "topic": topic, "text": f"Processed course content about {topic}."}
            for index, topic in enumerate(topics, start=1)
        ],
    }, user)
    notes_key = material_files.object_storage.save(user, course_id, ".docx", b"course-content")
    CourseMaterial.objects.create(
        user=user, course_id=course_id, original_filename="zz-course-content.docx",
        material_type=CourseMaterial.TYPE_NOTES, source_key=lecture_id,
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=notes_key, size_bytes=14,
    )


FIXED_NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_never_studied_topic_with_no_deadline_gets_moderate_gap_and_max_recency(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)

    candidates = recommendations.candidates_for_course("cs101", user, FIXED_NOW)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == mastery.NOT_STARTED
    assert candidate["gap"] == pytest.approx(recommendations.NEVER_ASSESSED_GAP)
    assert candidate["urgency"] == 0.0
    assert candidate["importance"] == 0.0
    assert candidate["recency"] == 1.0
    # 0.35*0.6 + 0.25*0 + 0.15*0 + 0.25*1.0 = 0.46
    assert candidate["rank_score"] == pytest.approx(0.46)


def test_upcoming_assessment_raises_urgency_and_importance(isolated_courses_dir, user):
    _seed_course(
        "cs101", topics=["Recursion"],
        grading=[{"component": "Midterm Exam", "weight_pct": 50}],
        dates=[{"date": "2026-03-01", "title": "Midterm", "type": "test_quiz"}],
        user=user,
    )

    candidate = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]

    assert candidate["urgency"] == 1.0  # due "today" relative to FIXED_NOW
    assert candidate["importance"] == 1.0  # 50% weight, capped at 1.0
    assert candidate["grading_component"] == "midterm exam"
    assert candidate["nearest_deadline"] == {"title": "Midterm", "date": "2026-03-01"}
    # 0.35*0.6 + 0.25*1.0 + 0.15*1.0 + 0.25*1.0 = 0.86
    assert candidate["rank_score"] == pytest.approx(0.86)
    assert "Midterm" in candidate["reason"]
    assert "midterm exam" in candidate["reason"]


def test_importance_falls_back_to_type_tier_without_a_grading_match(isolated_courses_dir, user):
    _seed_course(
        "cs101", topics=["Recursion"],
        grading=[{"component": "Homework", "weight_pct": 10}],
        dates=[{"date": "2026-03-05", "title": "Unit Test", "type": "test_quiz"}],
        user=user,
    )

    candidate = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]

    assert candidate["grading_component"] is None
    assert candidate["importance"] == recommendations.IMPORTANCE_BY_TYPE["test_quiz"]


def test_distant_deadline_contributes_little_urgency(isolated_courses_dir, user):
    _seed_course(
        "cs101", topics=["Recursion"],
        dates=[{"date": "2026-04-01", "title": "Final", "type": "test_quiz"}],  # 31 days out
        user=user,
    )

    candidate = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]

    assert candidate["urgency"] == 0.0  # beyond URGENCY_HORIZON_DAYS (14)


def test_recency_pressure_grows_with_staleness_and_caps_at_one(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)
    storage.append_quiz_attempt("cs101", {
        "topic": "Recursion", "correct": True, "timestamp": (FIXED_NOW - timedelta(days=7)).isoformat(),
    }, user=user)
    mastery.rebuild_scores("cs101", user=user, now=FIXED_NOW)

    recent = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]
    stale = recommendations.candidates_for_course("cs101", user, FIXED_NOW + timedelta(days=100))[0]

    assert recent["recency"] == pytest.approx(7 / recommendations.STALE_HORIZON_DAYS, abs=1e-4)
    assert stale["recency"] == 1.0


def test_exam_ready_topics_are_excluded_from_recommendations(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)
    for i in range(1, 6):
        storage.append_quiz_attempt("cs101", {
            "topic": "Recursion", "correct": True, "timestamp": f"2026-01-0{i}T00:00:00",
        }, user=user)
    mastery.rebuild_scores("cs101", user=user, now=datetime(2026, 1, 6, tzinfo=timezone.utc))

    candidates = recommendations.candidates_for_course("cs101", user, datetime(2026, 1, 6, tzinfo=timezone.utc))

    assert candidates == []


def test_course_with_no_syllabus_or_topics_contributes_nothing(isolated_courses_dir, user):
    assert recommendations.candidates_for_course("missing-course", user, FIXED_NOW) == []

    storage.write_syllabus("empty-topics", {
        "course_id": "empty-topics", "course_name": "Empty", "dates": [], "grading": [], "topics": [],
    }, user)
    assert recommendations.candidates_for_course("empty-topics", user, FIXED_NOW) == []


def test_missing_grading_and_mastery_data_is_a_normal_state_not_a_crash(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A", "B"], user=user)  # no grading, no quiz/flashcard history at all

    candidates = recommendations.candidates_for_course("cs101", user, FIXED_NOW)

    assert len(candidates) == 2
    assert all(c["status"] == mastery.NOT_STARTED for c in candidates)


def test_rank_recommendations_orders_deterministically_across_courses(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Weak Topic"], user=user)
    storage.append_quiz_attempt("cs101", {
        "topic": "Weak Topic", "correct": False, "timestamp": "2026-01-01T00:00:00",
    }, user=user)
    mastery.rebuild_scores("cs101", user=user, now=FIXED_NOW)

    _seed_course(
        "cs202", topics=["Urgent Topic"],
        dates=[{"date": "2026-03-01", "title": "Final", "type": "test_quiz"}],
        user=user,
    )

    top = recommendations.rank_recommendations(user, now=FIXED_NOW, limit=3)

    assert [(c["course_id"], c["topic"]) for c in top] == [
        ("cs202", "Urgent Topic"),  # urgent + important deadline outranks a merely-weak topic
        ("cs101", "Weak Topic"),
    ]
    # Ordering must be reproducible from the same inputs.
    again = recommendations.rank_recommendations(user, now=FIXED_NOW, limit=3)
    assert top == again


def test_session_minutes_changes_suggested_mode_not_ranking_order(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A", "B"], user=user)

    short = recommendations.rank_recommendations(user, session_minutes=10, now=FIXED_NOW)
    long = recommendations.rank_recommendations(user, session_minutes=30, now=FIXED_NOW)

    assert [c["topic"] for c in short] == [c["topic"] for c in long]
    assert all(c["suggested_mode"] == "flashcards" for c in short)
    assert all(c["suggested_mode"] == "mixed" for c in long)


def test_dismissed_recommendation_is_excluded(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], user=user)
    recommendations.dismiss_recommendation(user, "cs101", "A")

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []


def test_deferred_recommendation_reappears_after_its_defer_window(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], user=user)
    recommendations.dismiss_recommendation(user, "cs101", "A", defer_until=FIXED_NOW + timedelta(days=2))

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []
    assert len(recommendations.candidates_for_course("cs101", user, FIXED_NOW + timedelta(days=3))) == 1


def test_dismissal_never_touches_mastery_or_quiz_data(isolated_courses_dir, user):
    _seed_course("cs101", topics=["A"], user=user)
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"}, user=user)
    mastery.rebuild_scores("cs101", user=user)

    recommendations.dismiss_recommendation(user, "cs101", "A")

    assert mastery.weak_topics("cs101", user=user)[0]["topic"] == "A"
    history = storage.read_quiz_history("cs101", user=user)
    assert len(history["attempts"]) == 1


def test_recommendations_are_owner_scoped(isolated_courses_dir, user, django_user_model):
    other = django_user_model.objects.create_user(username="other")
    _seed_course("cs101", topics=["A"], user=user)

    assert recommendations.rank_recommendations(other, now=FIXED_NOW) == []


def test_reason_mentions_the_deadline_and_component_it_was_ranked_on(isolated_courses_dir, user):
    _seed_course(
        "cs101", topics=["Recursion"],
        grading=[{"component": "Final Exam", "weight_pct": 40}],
        dates=[{"date": "2026-03-02", "title": "Final Exam", "type": "test_quiz"}],
        user=user,
    )

    candidate = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]

    assert candidate["reason"] == (
        "You haven't studied “Recursion” yet, and Final Exam is due 2026-03-02 and counts toward final exam."
    )


def test_topic_without_an_actual_uploaded_file_is_not_recommended(isolated_courses_dir, user):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": ["Recursion"],
    }, user)

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_text_only_uploads_do_not_ground_recommendations(isolated_courses_dir, user, suffix):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": ["Recursion"],
    }, user)
    key = material_files.object_storage.save(user, "cs101", suffix, b"Recursion")
    CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename=f"notes{suffix}",
        material_type=CourseMaterial.TYPE_NOTES, source_key="lecture-1",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=key, size_bytes=9,
    )

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []


@pytest.mark.parametrize(
    ("suffix", "material_type"),
    [(".docx", CourseMaterial.TYPE_NOTES), (".pptx", CourseMaterial.TYPE_SLIDES)],
)
def test_notes_and_slides_attach_matching_course_evidence(isolated_courses_dir, user, suffix, material_type):
    _seed_course("cs101", topics=["Recursion"], user=user)
    storage.write_notes("cs101", "lecture-1", {
        "lecture_id": "lecture-1", "topics": ["Recursion"],
        "chunks": [{"id": "chunk-1", "topic": "Recursion", "text": "Recursion uses a base case and a recursive step.", "page": 4}],
    }, user)
    key = material_files.object_storage.save(user, "cs101", suffix, b"office-test")
    material = CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename=f"week-3{suffix}", material_type=material_type,
        source_key="lecture-1", processing_status=CourseMaterial.STATUS_READY,
        review_status=CourseMaterial.REVIEW_NOT_REQUIRED, storage_key=key, size_bytes=11,
    )

    sources = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]["sources"]

    assert sources[0] == {
        "material_id": str(material.material_id), "material_type": material_type,
        "filename": f"week-3{suffix}", "file_type": suffix[1:].upper(),
        "excerpt": "Recursion uses a base case and a recursive step.", "page": 4,
        "chunk_id": "chunk-1",
        "download_url": f"/api/courses/cs101/materials/{material.material_id}/download/",
    }


def test_missing_or_superseded_upload_cannot_be_used_as_evidence(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)
    CourseMaterial.objects.filter(course_id="cs101").update(review_status=CourseMaterial.REVIEW_SUPERSEDED)
    CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename="missing.pdf",
        material_type=CourseMaterial.TYPE_SYLLABUS, source_key="syllabus",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_CONFIRMED,
        storage_key="0" * 32 + ".pdf", size_bytes=10,
        extracted_data={"topics": ["Recursion"]},
    )

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []


def test_reference_pdf_attaches_the_matching_passage(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)
    storage.write_reference("cs101", "chapter-4", {
        "reference_id": "chapter-4", "title": "Algorithms Chapter 4",
        "source_filename": "chapter-4.pdf",
        "text": "Iteration repeats a block. Recursion solves a problem using a base case and smaller self-calls.",
    }, user)
    key = material_files.object_storage.save(user, "cs101", ".pdf", b"%PDF-reference")
    material = CourseMaterial.objects.create(
        user=user, course_id="cs101", original_filename="chapter-4.pdf",
        material_type=CourseMaterial.TYPE_REFERENCE, source_key="chapter-4",
        processing_status=CourseMaterial.STATUS_READY, review_status=CourseMaterial.REVIEW_NOT_REQUIRED,
        storage_key=key, size_bytes=14, content_type="application/pdf",
    )

    sources = recommendations.candidates_for_course("cs101", user, FIXED_NOW)[0]["sources"]
    source = next(source for source in sources if source["material_id"] == str(material.material_id))

    assert source["material_id"] == str(material.material_id)
    assert source["filename"] == "chapter-4.pdf"
    assert source["file_type"] == "PDF"
    assert "Recursion solves a problem" in source["excerpt"]


def test_syllabus_or_reference_without_a_topic_chunk_cannot_qualify_a_recommendation(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Recursion"], user=user)
    CourseMaterial.objects.filter(course_id="cs101", material_type=CourseMaterial.TYPE_NOTES).delete()
    storage.delete_lecture("cs101", "cs101-recommendation-content", user)

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []


def test_fuzzy_text_overlap_does_not_qualify_without_an_exact_topic_chunk(isolated_courses_dir, user):
    _seed_course("cs101", topics=["Hierarchical Objects"], user=user)
    lecture = storage.read_lecture("cs101", "cs101-recommendation-content", user)
    lecture["chunks"][0]["topic"] = "Scene Graphs"
    lecture["chunks"][0]["text"] = "Scene graphs contain hierarchical objects."
    storage.write_notes("cs101", "cs101-recommendation-content", lecture, user, overwrite=True)

    assert recommendations.candidates_for_course("cs101", user, FIXED_NOW) == []
