import pytest

from agent.services import grades, storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="owner", email="owner@example.com")


def _seed_syllabus(course_id, grading, user, grade_scale=None):
    data = {
        "course_id": course_id, "course_name": course_id.upper(), "dates": [],
        "grading": grading, "topics": [],
    }
    if grade_scale is not None:
        data["grade_scale"] = grade_scale
    storage.write_syllabus(course_id, data, user)


def _seed_items(course_id, items, user):
    storage.write_grades(course_id, {"course_id": course_id, "items": items}, user=user)


def test_current_grade_raises_without_syllabus(isolated_courses_dir, user):
    with pytest.raises(storage.CourseNotFoundError):
        grades.current_grade("cs101", user=user)


def test_current_grade_null_overall_when_no_items_entered(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    result = grades.current_grade("cs101", user=user)

    assert result["overall_pct"] is None
    assert result["letter"] is None
    assert result["categories"][0]["avg_pct"] is None
    assert result["categories"][0]["entered_count"] == 0


def test_current_grade_single_category_averages_items(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ], user)

    result = grades.current_grade("cs101", user=user)

    assert result["overall_pct"] == 85.0
    assert result["categories"][0]["avg_pct"] == 85.0
    assert result["categories"][0]["entered_count"] == 2


def test_current_grade_excludes_and_renormalizes_ungraded_categories(isolated_courses_dir, user):
    _seed_syllabus("cs101", [
        {"component": "Homework", "weight_pct": 50},
        {"component": "Final", "weight_pct": 50},
    ], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
    ], user)

    result = grades.current_grade("cs101", user=user)

    # Final has no items yet — excluded entirely, not counted as 0. Overall
    # should equal Homework's own average (80%), not 40% (which is what
    # you'd get if the missing category were silently treated as a zero).
    assert result["overall_pct"] == 80.0
    final_cat = next(c for c in result["categories"] if c["component"] == "Final")
    assert final_cat["avg_pct"] is None


def test_current_grade_drop_lowest_excludes_worst_entered_scores(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "drop_lowest": 1}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 100, "max_points": 100},
        {"id": "3", "component": "Homework", "title": "HW3", "score": 0, "max_points": 100},
    ], user)

    result = grades.current_grade("cs101", user=user)

    assert result["overall_pct"] == 100.0  # the 0 gets dropped


def test_current_grade_drop_lowest_clamps_to_never_drop_every_item(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "drop_lowest": 5}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 60, "max_points": 100},
    ], user)

    result = grades.current_grade("cs101", user=user)

    assert result["overall_pct"] == 60.0  # the only item is never dropped


def test_current_grade_letter_uses_default_scale(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 95, "max_points": 100}], user)

    result = grades.current_grade("cs101", user=user)

    assert result["letter"] == "A"


def test_current_grade_letter_uses_custom_grade_scale(isolated_courses_dir, user):
    _seed_syllabus(
        "cs101", [{"component": "Homework", "weight_pct": 100}], user,
        grade_scale={"passing_pct": 50, "cutoffs": [{"letter": "P", "min_pct": 50}]},
    )
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 55, "max_points": 100}], user)

    result = grades.current_grade("cs101", user=user)

    assert result["letter"] == "P"
    assert result["grade_scale"]["passing_pct"] == 50


def test_current_grade_letter_f_below_lowest_cutoff(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 10, "max_points": 100}], user)

    result = grades.current_grade("cs101", user=user)

    assert result["letter"] == "F"


def test_add_item_appends_and_returns_item(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, "2026-01-10", user=user)

    assert item["component"] == "Homework"
    assert item["title"] == "HW 1"
    assert item["score"] == 90
    assert item["id"]  # generated
    stored = storage.read_grades("cs101", user=user)["items"]
    assert len(stored) == 1
    assert stored[0]["id"] == item["id"]


def test_add_item_rejects_unknown_component(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(ValueError):
        grades.add_item("cs101", "Nonexistent", "X", 1, 1, user=user)


def test_add_item_raises_without_syllabus(isolated_courses_dir, user):
    with pytest.raises(storage.CourseNotFoundError):
        grades.add_item("cs101", "Homework", "X", 1, 1, user=user)


def test_update_item_changes_only_given_fields(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    updated = grades.update_item("cs101", item["id"], user=user, score=95)

    assert updated["score"] == 95
    assert updated["title"] == "HW 1"  # unchanged


def test_update_item_raises_for_unknown_id(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(grades.ItemNotFoundError):
        grades.update_item("cs101", "nope", user=user, score=1)


def test_update_item_rejects_unknown_component(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    with pytest.raises(ValueError):
        grades.update_item("cs101", item["id"], user=user, component="Nonexistent")


def test_find_orphaned_components_detects_renamed_category(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    orphaned = grades.find_orphaned_components("cs101", [{"component": "Assignments", "weight_pct": 100}], user=user)

    assert orphaned == ["Homework"]


def test_find_orphaned_components_empty_when_category_kept(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    orphaned = grades.find_orphaned_components("cs101", [{"component": "Homework", "weight_pct": 100}], user=user)

    assert orphaned == []


def test_delete_item_removes_it(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    grades.delete_item("cs101", item["id"], user=user)

    assert storage.read_grades("cs101", user=user)["items"] == []


def test_delete_item_raises_for_unknown_id(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(grades.ItemNotFoundError):
        grades.delete_item("cs101", "nope", user=user)


def test_add_item_rejects_invalid_score_via_validate_grades(isolated_courses_dir, user):
    # add_item's inputs are typed floats, but callers that bypass DRF's
    # serializer validation (the CLI's --add path parses raw strings with
    # float()) can still pass a negative score — storage.validate_grades()
    # is the second line of defense that catches it before anything is
    # written to disk.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(ValueError):
        grades.add_item("cs101", "Homework", "HW 1", -5, 100, user=user)

    assert storage.read_grades("cs101", user=user)["items"] == []  # nothing written


def test_update_item_rejects_invalid_update(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    item = grades.add_item("cs101", "Homework", "HW 1", 90, 100, user=user)

    with pytest.raises(ValueError):
        grades.update_item("cs101", item["id"], user=user, max_points=0)

    assert storage.read_grades("cs101", user=user)["items"][0]["max_points"] == 100  # unchanged


def test_project_grade_substitutes_hypothetical_score_on_existing_item(isolated_courses_dir, user):
    _seed_syllabus("cs101", [
        {"component": "Homework", "weight_pct": 50},
        {"component": "Midterm", "weight_pct": 50},
    ], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
        {"id": "2", "component": "Midterm", "title": "Midterm", "score": 70, "max_points": 100},
    ], user)

    result = grades.project_grade("cs101", 90, 100, item_id="2", user=user)

    assert result["baseline_pct"] == 80.0  # (90+70)/2
    assert result["projected_pct"] == 90.0  # (90+90)/2
    assert result["delta_pct"] == pytest.approx(10.0)
    # the real stored item is untouched — this is read-only
    assert storage.read_grades("cs101", user=user)["items"][1]["score"] == 70


def test_project_grade_appends_hypothetical_item_for_upcoming_assignment(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100}], user)

    result = grades.project_grade("cs101", 100, 100, component="Homework", title="HW2", user=user)

    assert result["baseline_pct"] == 80.0
    assert result["projected_pct"] == 90.0  # (80+100)/2
    stored = storage.read_grades("cs101", user=user)["items"]
    assert len(stored) == 1 and stored[0]["id"] == "1" and stored[0]["score"] == 80  # nothing written


def test_project_grade_raises_for_unknown_item_id(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(grades.ItemNotFoundError):
        grades.project_grade("cs101", 90, 100, item_id="nope", user=user)


def test_project_grade_rejects_unknown_component(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100}], user)

    with pytest.raises(ValueError):
        grades.project_grade("cs101", 90, 100, component="Nonexistent", user=user)


def test_project_grade_raises_without_syllabus(isolated_courses_dir, user):
    with pytest.raises(storage.CourseNotFoundError):
        grades.project_grade("cs101", 90, 100, component="Homework", user=user)


def test_grade_needed_solves_flat_score_for_remaining_items(isolated_courses_dir, user):
    # One category, 100% weight, 4 total items, 2 entered averaging 80%.
    # To reach 90% overall: (80*2 + p*2)/4 = 90 -> p = 100.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 90, user=user)

    assert result["locked"] is False
    assert result["p_needed"] == pytest.approx(100.0)
    assert result["achievable"] is True
    assert result["ceiling_pct"] is None


def test_grade_needed_reports_impossible_target_with_ceiling(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 10, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 10, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 99, user=user)

    assert result["achievable"] is False
    assert result["p_needed"] > 100
    assert result["ceiling_pct"] == pytest.approx(55.0)  # (10+10+100+100)/4


def test_grade_needed_already_guaranteed_reports_zero(isolated_courses_dir, user):
    # 2 entered @ 100/100, 2 remaining of 4 total: even scoring 0 on both
    # remaining items, the category floors at (100+100+0+0)/4 = 50%. So a
    # target at or below that floor (40) is already guaranteed; the brief's
    # plain formula gives p_needed = max((40-50)/0.5, 0) = 0 for this case.
    # (A target of 60 here is NOT already guaranteed — p_needed would
    # correctly be 20, not 0 — so 60 was the wrong choice for this test.)
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 100, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 40, user=user)

    assert result["p_needed"] == 0
    assert result["achievable"] is True


def test_grade_needed_locked_when_nothing_left(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 2}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 90, user=user)

    assert result["locked"] is True
    assert result["p_needed"] is None
    assert result["ceiling_pct"] == pytest.approx(80.0)
    assert result["achievable"] is False


def test_grade_needed_category_without_total_items_is_treated_as_closed(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Participation", "weight_pct": 100}], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Participation", "title": "P1", "score": 70, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 90, user=user)

    assert result["locked"] is True
    assert result["ceiling_pct"] == pytest.approx(70.0)


def test_grade_needed_notes_empty_category_with_no_total_items(isolated_courses_dir, user):
    _seed_syllabus("cs101", [
        {"component": "Homework", "weight_pct": 50, "total_items": 2},
        {"component": "Extra Credit", "weight_pct": 50},  # no items, no total_items
    ], user)
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
    ], user)

    result = grades.grade_needed("cs101", 90, user=user)

    assert any("Extra Credit" in note for note in result["notes"])


def test_grade_needed_raises_without_syllabus(isolated_courses_dir, user):
    with pytest.raises(storage.CourseNotFoundError):
        grades.grade_needed("cs101", 90, user=user)


def test_missable_by_category_computes_max_missable(isolated_courses_dir, user):
    # 4 total, 0 entered, target 75%: missing k of 4 while acing the rest
    # must keep (4-k)*100/4 >= 75 -> k <= 1.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)

    result = grades.missable_by_category("cs101", 75, user=user)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["remaining"] == 4
    assert hw["missable"] == 1
    assert hw["omitted_reason"] is None


def test_missable_by_category_zero_when_must_ace_everything(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)

    result = grades.missable_by_category("cs101", 100, user=user)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["missable"] == 0


def test_missable_by_category_omits_when_target_unreachable_even_at_best_case(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 50, "max_points": 100}], user)

    result = grades.missable_by_category("cs101", 90, user=user)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["missable"] is None
    assert "not reachable" in hw["omitted_reason"]


def test_missable_by_category_omits_category_without_total_items(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Participation", "weight_pct": 100}], user)

    result = grades.missable_by_category("cs101", 75, user=user)

    p = next(r for r in result if r["component"] == "Participation")
    assert p["missable"] is None
    assert p["omitted_reason"] is not None


def test_missable_by_category_omits_category_with_nothing_remaining(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 1}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100}], user)

    result = grades.missable_by_category("cs101", 75, user=user)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["remaining"] == 0
    assert hw["missable"] is None
    assert hw["omitted_reason"] is not None


def test_missable_by_category_accounts_for_entered_scores(isolated_courses_dir, user):
    # 1 entered at 100%, 3 remaining, target 75%: (100 + (3-k)*100)/4 >= 75 -> k <= 1.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}], user)
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100}], user)

    result = grades.missable_by_category("cs101", 75, user=user)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["missable"] == 1


def test_all_courses_summary_averages_only_graded_courses(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}], user)
    _seed_items("cs101", [{"id": "1", "component": "HW", "title": "HW1", "score": 80, "max_points": 100}], user)
    _seed_syllabus("psyc201", [{"component": "HW", "weight_pct": 100}], user)  # no items entered

    result = grades.all_courses_summary(user=user)

    assert result["average_pct"] == 80.0
    assert result["excluded_count"] == 1
    cs101 = next(c for c in result["courses"] if c["course_id"] == "cs101")
    assert cs101["current_pct"] == 80.0
    psyc201 = next(c for c in result["courses"] if c["course_id"] == "psyc201")
    assert psyc201["current_pct"] is None


def test_all_courses_summary_null_average_when_nothing_graded(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}], user)

    result = grades.all_courses_summary(user=user)

    assert result["average_pct"] is None
    assert result["excluded_count"] == 1


def test_all_courses_summary_no_courses_at_all(isolated_courses_dir, user):
    result = grades.all_courses_summary(user=user)

    assert result["average_pct"] is None
    assert result["courses"] == []
    assert result["excluded_count"] == 0


def test_all_courses_summary_ignores_legacy_corrupt_grades_json(isolated_courses_dir, user):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}], user)
    _seed_items("cs101", [{"id": "1", "component": "HW", "title": "HW1", "score": 80, "max_points": 100}], user)

    bad_dir = isolated_courses_dir / str(user.pk) / "badcourse"
    bad_dir.mkdir(parents=True)
    (bad_dir / "syllabus.json").write_text('{"course_id": "badcourse", "course_name": "Bad", "dates": [], "grading": [], "topics": []}', encoding="utf-8")
    (bad_dir / "grades.json").write_text("{not valid json", encoding="utf-8")

    result = grades.all_courses_summary(user=user)

    bad = next(c for c in result["courses"] if c["course_id"] == "badcourse")
    assert bad["current_pct"] is None
    assert bad["letter"] is None
    cs101 = next(c for c in result["courses"] if c["course_id"] == "cs101")
    assert cs101["current_pct"] == 80.0
