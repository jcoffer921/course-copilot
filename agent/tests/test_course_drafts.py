import pytest

from agent.services import reminders, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_write_course_draft_creates_course_json(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")

    path = isolated_courses_dir / "newclass" / "course.json"
    assert path.exists()


def test_write_course_draft_rejects_duplicate_draft(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")

    with pytest.raises(storage.CourseAlreadyExistsError):
        storage.write_course_draft("newclass", "New Class Again")


def test_write_course_draft_rejects_existing_real_course(isolated_courses_dir):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    })

    with pytest.raises(storage.CourseAlreadyExistsError):
        storage.write_course_draft("cs101", "Intro to CS")


def test_write_course_draft_rejects_invalid_course_id(isolated_courses_dir):
    with pytest.raises(storage.InvalidCourseIdError):
        storage.write_course_draft("../escape", "Bad")


def test_list_draft_courses_empty_when_none_exist(isolated_courses_dir):
    assert reminders.list_draft_courses() == []


def test_list_draft_courses_returns_name_only_classes(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")

    drafts = reminders.list_draft_courses()

    assert len(drafts) == 1
    assert drafts[0]["course_id"] == "newclass"
    assert drafts[0]["course_name"] == "New Class"
    assert "created_at" in drafts[0]


def test_list_draft_courses_excludes_real_courses(isolated_courses_dir):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    })

    assert reminders.list_draft_courses() == []


def test_list_draft_courses_excludes_course_once_syllabus_written(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")
    assert len(reminders.list_draft_courses()) == 1

    storage.write_syllabus("newclass", {
        "course_id": "newclass", "course_name": "New Class", "dates": [], "grading": [], "topics": [],
    })

    assert reminders.list_draft_courses() == []
    assert "newclass" in reminders.list_courses()


def test_list_draft_courses_skips_corrupt_course_json(isolated_courses_dir):
    bad_dir = isolated_courses_dir / "badclass"
    bad_dir.mkdir()
    (bad_dir / "course.json").write_text("{not valid json", encoding="utf-8")
    storage.write_course_draft("goodclass", "Good Class")

    drafts = reminders.list_draft_courses()

    assert [d["course_id"] for d in drafts] == ["goodclass"]


def test_course_exists_true_for_real_course(isolated_courses_dir):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    })

    assert storage.course_exists("cs101") is True


def test_course_exists_false_for_missing_course(isolated_courses_dir):
    assert storage.course_exists("nope") is False


def test_course_exists_false_for_invalid_course_id(isolated_courses_dir):
    assert storage.course_exists("../escape") is False


def test_course_exists_false_for_draft_only_course(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")

    assert storage.course_exists("newclass") is False
