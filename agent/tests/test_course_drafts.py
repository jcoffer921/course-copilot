import pytest

from agent.services import reminders, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_write_course_draft_creates_course_json(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_course_draft("newclass", "New Class", user)

    path = isolated_courses_dir / str(user.pk) / "newclass" / "course.json"
    assert path.exists()


@pytest.mark.django_db
def test_write_course_draft_rejects_duplicate_draft(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_course_draft("newclass", "New Class", user)

    with pytest.raises(storage.CourseAlreadyExistsError):
        storage.write_course_draft("newclass", "New Class Again", user)


@pytest.mark.django_db
def test_write_course_draft_rejects_existing_real_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    }, user)

    with pytest.raises(storage.CourseAlreadyExistsError):
        storage.write_course_draft("cs101", "Intro to CS", user)


@pytest.mark.django_db
def test_write_course_draft_rejects_invalid_course_id(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    with pytest.raises(storage.InvalidCourseIdError):
        storage.write_course_draft("../escape", "Bad", user)


def test_list_draft_courses_empty_when_none_exist(isolated_courses_dir):
    assert reminders.list_draft_courses() == []


@pytest.mark.django_db
def test_list_draft_courses_returns_name_only_classes(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_course_draft("newclass", "New Class", user)

    drafts = reminders.list_draft_courses()

    assert len(drafts) == 1
    assert drafts[0]["course_id"] == "newclass"
    assert drafts[0]["course_name"] == "New Class"
    assert "created_at" in drafts[0]


@pytest.mark.django_db
def test_list_draft_courses_excludes_real_courses(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    }, user)

    assert reminders.list_draft_courses() == []


@pytest.mark.django_db
def test_list_draft_courses_excludes_course_once_syllabus_written(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_course_draft("newclass", "New Class", user)
    assert len(reminders.list_draft_courses()) == 1

    storage.write_syllabus("newclass", {
        "course_id": "newclass", "course_name": "New Class", "dates": [], "grading": [], "topics": [],
    }, user)

    assert reminders.list_draft_courses() == []
    assert "newclass" in reminders.list_courses()


@pytest.mark.django_db
def test_list_draft_courses_skips_corrupt_course_json(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    bad_dir = isolated_courses_dir / str(user.pk) / "badclass"
    bad_dir.mkdir(parents=True)
    (bad_dir / "course.json").write_text("{not valid json", encoding="utf-8")
    storage.write_course_draft("goodclass", "Good Class", user)

    drafts = reminders.list_draft_courses()

    assert [d["course_id"] for d in drafts] == ["goodclass"]


@pytest.mark.django_db
def test_course_exists_true_for_real_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": [],
    }, user)

    assert storage.course_exists("cs101", user) is True


@pytest.mark.django_db
def test_course_exists_false_for_missing_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    assert storage.course_exists("nope", user) is False


@pytest.mark.django_db
def test_course_exists_false_for_invalid_course_id(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    assert storage.course_exists("../escape", user) is False


@pytest.mark.django_db
def test_course_exists_false_for_draft_only_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    storage.write_course_draft("newclass", "New Class", user)

    assert storage.course_exists("newclass", user) is False


@pytest.mark.django_db
def test_delete_course_only_removes_the_owning_users_grade_items(isolated_courses_dir, django_user_model):
    from agent.models import GradeItem
    from agent.services import storage

    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    other = django_user_model.objects.create_user(username="other", email="other@example.com")

    storage.write_course_draft("cs101", "Intro to CS", owner)
    storage.write_syllabus("cs101", {"course_id": "cs101", "course_name": "Intro to CS", "dates": [], "grading": [], "topics": []}, owner, overwrite=True)
    GradeItem.objects.create(course_id="cs101", user=owner, item_id="a", component="hw", title="HW1", score=8, max_points=10)
    GradeItem.objects.create(course_id="cs101", user=other, item_id="b", component="hw", title="HW1", score=9, max_points=10)

    storage.delete_course("cs101", owner)

    assert not GradeItem.objects.filter(user=owner, course_id="cs101").exists()
    assert GradeItem.objects.filter(user=other, course_id="cs101").exists()
