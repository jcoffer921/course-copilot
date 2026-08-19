import pytest

from agent.services import grades, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_syllabus(course_id, grading, grade_scale=None):
    data = {
        "course_id": course_id, "course_name": course_id.upper(), "dates": [],
        "grading": grading, "topics": [],
    }
    if grade_scale is not None:
        data["grade_scale"] = grade_scale
    storage.write_syllabus(course_id, data)


def _seed_items(course_id, items):
    storage.write_grades(course_id, {"course_id": course_id, "items": items})


def test_current_grade_raises_without_syllabus(isolated_courses_dir):
    with pytest.raises(storage.CourseNotFoundError):
        grades.current_grade("cs101")


def test_current_grade_null_overall_when_no_items_entered(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    result = grades.current_grade("cs101")

    assert result["overall_pct"] is None
    assert result["letter"] is None
    assert result["categories"][0]["avg_pct"] is None
    assert result["categories"][0]["entered_count"] == 0


def test_current_grade_single_category_averages_items(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ])

    result = grades.current_grade("cs101")

    assert result["overall_pct"] == 85.0
    assert result["categories"][0]["avg_pct"] == 85.0
    assert result["categories"][0]["entered_count"] == 2


def test_current_grade_excludes_and_renormalizes_ungraded_categories(isolated_courses_dir):
    _seed_syllabus("cs101", [
        {"component": "Homework", "weight_pct": 50},
        {"component": "Final", "weight_pct": 50},
    ])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
    ])

    result = grades.current_grade("cs101")

    # Final has no items yet — excluded entirely, not counted as 0. Overall
    # should equal Homework's own average (80%), not 40% (which is what
    # you'd get if the missing category were silently treated as a zero).
    assert result["overall_pct"] == 80.0
    final_cat = next(c for c in result["categories"] if c["component"] == "Final")
    assert final_cat["avg_pct"] is None


def test_current_grade_drop_lowest_excludes_worst_entered_scores(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "drop_lowest": 1}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 100, "max_points": 100},
        {"id": "3", "component": "Homework", "title": "HW3", "score": 0, "max_points": 100},
    ])

    result = grades.current_grade("cs101")

    assert result["overall_pct"] == 100.0  # the 0 gets dropped


def test_current_grade_drop_lowest_clamps_to_never_drop_every_item(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "drop_lowest": 5}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 60, "max_points": 100},
    ])

    result = grades.current_grade("cs101")

    assert result["overall_pct"] == 60.0  # the only item is never dropped


def test_current_grade_letter_uses_default_scale(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 95, "max_points": 100}])

    result = grades.current_grade("cs101")

    assert result["letter"] == "A"


def test_current_grade_letter_uses_custom_grade_scale(isolated_courses_dir):
    _seed_syllabus(
        "cs101", [{"component": "Homework", "weight_pct": 100}],
        grade_scale={"passing_pct": 50, "cutoffs": [{"letter": "P", "min_pct": 50}]},
    )
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 55, "max_points": 100}])

    result = grades.current_grade("cs101")

    assert result["letter"] == "P"
    assert result["grade_scale"]["passing_pct"] == 50


def test_current_grade_letter_f_below_lowest_cutoff(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 10, "max_points": 100}])

    result = grades.current_grade("cs101")

    assert result["letter"] == "F"
