import pytest

from agent.services import storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_read_grades_returns_empty_skeleton_for_new_course(isolated_courses_dir):
    data = storage.read_grades("cs101")
    assert data == {"course_id": "cs101", "items": []}


def test_write_then_read_grades_round_trips(isolated_courses_dir):
    data = {"course_id": "cs101", "items": [
        {"id": "abc123", "component": "Homework", "title": "HW 1", "score": 90, "max_points": 100, "date": "2026-01-15"},
    ]}
    storage.write_grades("cs101", data)

    assert storage.read_grades("cs101") == data


def test_read_grades_ignores_legacy_corrupt_json(isolated_courses_dir):
    course_dir = isolated_courses_dir / "cs101"
    course_dir.mkdir()
    (course_dir / "grades.json").write_text("{not valid json", encoding="utf-8")

    assert storage.read_grades("cs101") == {"course_id": "cs101", "items": []}


def test_validate_grades_valid_data_returns_no_errors():
    data = {"course_id": "cs101", "items": [
        {"id": "abc123", "component": "Homework", "title": "HW 1", "score": 90, "max_points": 100, "date": "2026-01-15"},
    ]}
    assert storage.validate_grades(data) == []


def test_validate_grades_rejects_missing_top_level_fields():
    errors = storage.validate_grades({"items": []})
    assert any("course_id" in e for e in errors)


def test_validate_grades_rejects_duplicate_item_ids():
    data = {"course_id": "cs101", "items": [
        {"id": "dup", "component": "HW", "title": "A", "score": 1, "max_points": 1},
        {"id": "dup", "component": "HW", "title": "B", "score": 1, "max_points": 1},
    ]}
    errors = storage.validate_grades(data)
    assert any("duplicate" in e for e in errors)


def test_validate_grades_rejects_negative_score():
    data = {"course_id": "cs101", "items": [
        {"id": "a", "component": "HW", "title": "A", "score": -1, "max_points": 100},
    ]}
    errors = storage.validate_grades(data)
    assert any("score" in e for e in errors)


def test_validate_grades_rejects_zero_max_points():
    data = {"course_id": "cs101", "items": [
        {"id": "a", "component": "HW", "title": "A", "score": 0, "max_points": 0},
    ]}
    errors = storage.validate_grades(data)
    assert any("max_points" in e for e in errors)


def test_validate_grades_rejects_bad_date_format():
    data = {"course_id": "cs101", "items": [
        {"id": "a", "component": "HW", "title": "A", "score": 1, "max_points": 1, "date": "Jan 1"},
    ]}
    errors = storage.validate_grades(data)
    assert any("date" in e for e in errors)


def test_validate_grades_allows_missing_date():
    data = {"course_id": "cs101", "items": [
        {"id": "a", "component": "HW", "title": "A", "score": 1, "max_points": 1},
    ]}
    assert storage.validate_grades(data) == []


def test_validate_grading_config_valid_returns_no_errors():
    grading = [{"component": "Homework", "weight_pct": 100, "total_items": 8, "drop_lowest": 1}]
    assert storage.validate_grading_config(grading) == []


def test_validate_grading_config_rejects_non_positive_total_items():
    grading = [{"component": "Homework", "weight_pct": 20, "total_items": 0}]
    errors = storage.validate_grading_config(grading)
    assert any("total_items" in e for e in errors)


def test_validate_grading_config_rejects_negative_drop_lowest():
    grading = [{"component": "Homework", "weight_pct": 20, "drop_lowest": -1}]
    errors = storage.validate_grading_config(grading)
    assert any("drop_lowest" in e for e in errors)


def test_validate_grading_config_warns_when_drop_lowest_would_drop_everything():
    grading = [{"component": "Homework", "weight_pct": 20, "total_items": 2, "drop_lowest": 2}]
    errors = storage.validate_grading_config(grading)
    assert any(e.startswith("WARNING") and "drop_lowest" in e for e in errors)


def test_validate_grading_config_warns_when_weights_dont_sum_to_100():
    grading = [{"component": "Homework", "weight_pct": 50}]
    errors = storage.validate_grading_config(grading)
    assert any(e.startswith("WARNING") and "sum to" in e for e in errors)


def test_validate_grading_config_validates_grade_scale_cutoffs():
    grade_scale = {"passing_pct": 60, "cutoffs": [{"letter": "A"}]}
    errors = storage.validate_grading_config([], grade_scale)
    assert any("min_pct" in e for e in errors)


def test_write_grading_config_merges_into_existing_syllabus(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="grading-merge", email="grading-merge@example.com")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": ["A"],
    }, user)

    grading = [{"component": "Homework", "weight_pct": 100, "total_items": 5}]
    storage.write_grading_config("cs101", grading, user, {"passing_pct": 65, "cutoffs": []})

    syllabus = storage.read_syllabus("cs101", user)
    assert syllabus["grading"] == grading
    assert syllabus["grade_scale"] == {"passing_pct": 65, "cutoffs": []}
    assert syllabus["course_name"] == "CS101"  # untouched


def test_write_grading_config_leaves_grade_scale_untouched_when_omitted(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="grading-omitted", email="grading-omitted@example.com")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [],
        "topics": [], "grade_scale": {"passing_pct": 70, "cutoffs": []},
    }, user)

    storage.write_grading_config("cs101", [{"component": "HW", "weight_pct": 100}], user)

    syllabus = storage.read_syllabus("cs101", user)
    assert syllabus["grade_scale"] == {"passing_pct": 70, "cutoffs": []}


def test_write_grading_config_raises_when_no_syllabus_exists(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="grading-no-syllabus", email="grading-no-syllabus@example.com")
    with pytest.raises(storage.CourseNotFoundError):
        storage.write_grading_config("cs101", [{"component": "HW", "weight_pct": 100}], user)


def test_validate_grading_config_rejects_invalid_component_name():
    grading = [{"component": "Attendance", "weight_pct": 100}]

    errors = storage.validate_grading_config(grading)

    assert any("component" in e and "must be one of" in e for e in errors)
    assert not any(e.startswith("WARNING") for e in errors)  # blocking, not a warning


def test_validate_grading_config_accepts_every_fixed_category_name():
    grading = [
        {"component": name, "weight_pct": 100 / len(storage.GRADING_CATEGORY_CHOICES)}
        for name in storage.GRADING_CATEGORY_CHOICES
    ]

    errors = storage.validate_grading_config(grading)

    blocking = [e for e in errors if not e.startswith("WARNING")]
    assert blocking == []
    assert {"Lab and Demo", "Final Project", "Class Participation"}.issubset(storage.GRADING_CATEGORY_CHOICES)


def test_validate_grading_config_rejects_duplicate_component_names():
    grading = [
        {"component": "Homework", "weight_pct": 50},
        {"component": "Homework", "weight_pct": 50},
    ]

    errors = storage.validate_grading_config(grading)

    blocking = [e for e in errors if not e.startswith("WARNING")]
    assert any("duplicate" in e.lower() and "Homework" in e for e in blocking)
