"""New tests for storage.py's user-scoped path resolution (Task 1 of the
user-scoped-course-storage plan)."""
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_course_dir_nests_under_user_pk(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    course_dir = storage._course_dir("cs101", user)
    assert course_dir == isolated_courses_dir / str(user.pk) / "cs101"


def test_course_dir_requires_a_user(isolated_courses_dir):
    with pytest.raises(ValueError):
        storage._course_dir("cs101", None)


@pytest.mark.django_db
def test_course_dir_rejects_invalid_course_id(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    with pytest.raises(storage.InvalidCourseIdError):
        storage._course_dir("../../etc", user)


@pytest.mark.django_db
def test_lecture_path_nests_under_user_and_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    path = storage._lecture_path("cs101", "lec1", user)
    assert path == isolated_courses_dir / str(user.pk) / "cs101" / "notes" / "lec1.json"


@pytest.mark.django_db
def test_reference_path_nests_under_user_and_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    path = storage._reference_path("cs101", "ref1", user)
    assert path == isolated_courses_dir / str(user.pk) / "cs101" / "references" / "ref1.json"


def test_validate_course_id_has_no_user_requirement():
    storage._validate_course_id("cs101")
    with pytest.raises(storage.InvalidCourseIdError):
        storage._validate_course_id("../../etc")


@pytest.mark.django_db
def test_two_users_same_course_id_have_fully_isolated_syllabi(isolated_courses_dir, django_user_model):
    user_a = django_user_model.objects.create_user(username="iso-user-a", email="iso-user-a@example.com")
    user_b = django_user_model.objects.create_user(username="iso-user-b", email="iso-user-b@example.com")

    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "A's CS101", "dates": [], "grading": [], "topics": ["Recursion"],
    }, user_a)
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "B's CS101", "dates": [], "grading": [], "topics": ["Sorting"],
    }, user_b)

    assert storage.read_syllabus("cs101", user_a)["topics"] == ["Recursion"]
    assert storage.read_syllabus("cs101", user_b)["topics"] == ["Sorting"]
    assert (isolated_courses_dir / str(user_a.pk) / "cs101" / "syllabus.json").exists()
    assert (isolated_courses_dir / str(user_b.pk) / "cs101" / "syllabus.json").exists()
