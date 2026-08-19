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


def test_add_item_appends_and_returns_item(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, "2026-01-10")

    assert item["component"] == "Homework"
    assert item["title"] == "HW 1"
    assert item["score"] == 90
    assert item["id"]  # generated
    stored = storage.read_grades("cs101")["items"]
    assert len(stored) == 1
    assert stored[0]["id"] == item["id"]


def test_add_item_rejects_unknown_component(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    with pytest.raises(ValueError):
        grades.add_item("cs101", "Nonexistent", "X", 1, 1)


def test_add_item_raises_without_syllabus(isolated_courses_dir):
    with pytest.raises(storage.CourseNotFoundError):
        grades.add_item("cs101", "Homework", "X", 1, 1)


def test_update_item_changes_only_given_fields(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100)

    updated = grades.update_item("cs101", item["id"], score=95)

    assert updated["score"] == 95
    assert updated["title"] == "HW 1"  # unchanged


def test_update_item_raises_for_unknown_id(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    with pytest.raises(grades.ItemNotFoundError):
        grades.update_item("cs101", "nope", score=1)


def test_delete_item_removes_it(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100)

    grades.delete_item("cs101", item["id"])

    assert storage.read_grades("cs101")["items"] == []


def test_delete_item_raises_for_unknown_id(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    with pytest.raises(grades.ItemNotFoundError):
        grades.delete_item("cs101", "nope")


def test_add_item_rejects_invalid_score_via_validate_grades(isolated_courses_dir):
    # add_item's inputs are typed floats, but callers that bypass DRF's
    # serializer validation (the CLI's --add path parses raw strings with
    # float()) can still pass a negative score — storage.validate_grades()
    # is the second line of defense that catches it before anything is
    # written to disk.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])

    with pytest.raises(ValueError):
        grades.add_item("cs101", "Homework", "HW 1", -5, 100)

    assert storage.read_grades("cs101")["items"] == []  # nothing written


def test_update_item_rejects_invalid_update(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}])
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100)

    with pytest.raises(ValueError):
        grades.update_item("cs101", item["id"], max_points=0)

    assert storage.read_grades("cs101")["items"][0]["max_points"] == 100  # unchanged
