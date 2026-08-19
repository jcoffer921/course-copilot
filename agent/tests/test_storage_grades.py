import pytest

from agent.services import storage


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


def test_read_grades_raises_on_corrupt_json(isolated_courses_dir):
    course_dir = isolated_courses_dir / "cs101"
    course_dir.mkdir()
    (course_dir / "grades.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(storage.GradesStorageError):
        storage.read_grades("cs101")


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
