# Grade Calculator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Grade Calculator tab to OnTrack that tracks real entered scores against a course's syllabus grading categories, shows a current grade per course and averaged across all courses, and answers "what do I need on what's left" and "how many can I miss" what-if questions.

**Architecture:** New `courses/<id>/grades.json` per-course file for entered scores, plus two new optional fields on the existing `syllabus.json` (`total_items`/`drop_lowest` per grading category, and a top-level `grade_scale`). A new `agent/services/grades.py` does all calculation (mirrors `mastery.py`'s pure-computation style). New DRF async views expose it, a new management command mirrors the API for the CLI, and a new tab in `ontrack.html` follows the existing card/stat-tile visual language and course-selector mechanism already used by the Progress tab — except this tab does not bounce to Dashboard when "All Courses" is selected.

**Tech Stack:** Django + DRF (adrf async views), pytest + pytest-django, flat JSON file storage, vanilla JS component (`ontrack.html`'s hand-rolled `sc-if`/`sc-for` template DSL) — no new dependencies.

## Global Constraints

- Never fabricate or infer scores — every number the UI shows must trace back to either a real entered `grades.json` item or an explicit user-set config value (`total_items`, `drop_lowest`, `grade_scale`). No silent defaults presented as if they were real data.
- `agent/services/grades.py` has no async/API calls and no `import anthropic` — pure computation over `storage.py` reads/writes, same boundary as `mastery.py`.
- Every new JSON write goes through a `validate_*` check before being written, per this project's "fails loudly, validated before write" convention (see `CLAUDE.md`'s "Definition of working").
- `course_id` path segments continue to go through the slug converter already used everywhere else in `agent/urls.py`; `item_id` is a plain UUID used only as a dict key inside `grades.json`, never a filesystem path segment, so it does not need `storage.py`'s path-traversal-guard regex treatment.
- Follow the existing CLI-mirrors-API convention: every capability reachable from the API must also be reachable from `manage.py grades`.
- No new Python dependencies, no new JS libraries — extend the existing hand-rolled component and DRF view patterns exactly as the Quiz/Progress tabs already do.

---

## File Structure

**Backend — new:**
- `agent/services/grades.py` — calculation engine + CRUD (`current_grade`, `add_item`, `update_item`, `delete_item`, `grade_needed`, `missable_by_category`, `all_courses_summary`)
- `agent/management/commands/grades.py` — CLI wrapper
- `agent/tests/test_storage_grades.py` — tests for the new `storage.py` grades functions
- `agent/tests/test_grades.py` — tests for `grades.py`

**Backend — modified:**
- `agent/services/storage.py` — add `read_grades`/`write_grades`/`validate_grades`, `validate_grading_config`/`write_grading_config`, `GradesStorageError`
- `agent/serializers.py` — add `GradingCategorySerializer`, `GradingConfigRequestSerializer`, `AddGradeItemRequestSerializer`, `UpdateGradeItemRequestSerializer`
- `agent/views.py` — add `GradingConfigView`, `GradesView`, `GradeItemsView`, `GradeItemDetailView`, `GradesWhatIfView`, `GradesSummaryView`
- `agent/urls.py` — wire the six new routes
- `agent/tests/test_views.py` — API tests for the six new views

**Frontend — modified:**
- `agent/templates/agent/ontrack.html` — new nav button, new `tab: 'grades'` state/rendering branch, new fetch methods, new "Add grade" modal, per-course and all-courses view markup

No new files needed on the frontend — this project keeps the whole app in one template, and the plan follows that existing structure rather than splitting it.

---

## Task 1: `storage.py` — `grades.json` read/write/validate

**Files:**
- Modify: `agent/services/storage.py`
- Test: `agent/tests/test_storage_grades.py` (new)

**Interfaces:**
- Produces: `storage.GradesStorageError` (Exception), `storage.read_grades(course_id: str) -> dict`, `storage.write_grades(course_id: str, data: dict) -> Path`, `storage.validate_grades(data: dict) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_storage_grades.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_storage_grades.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.storage' has no attribute 'read_grades'` (and similar for the other new names)

- [ ] **Step 3: Implement in `agent/services/storage.py`**

Add near the other `*StorageError` classes (after `class QuizStorageError`):

```python
class GradesStorageError(Exception):
    """Raised when grades.json on disk is corrupt/unreadable."""
```

Add a `validate_grades` function near the other `validate_*` functions (after `validate_trusted_domains`):

```python
def validate_grades(data: dict) -> list:
    """Returns a list of error strings. An empty list means the data is
    valid. No non-blocking WARNING entries here — a grade item either has a
    usable score or it doesn't."""
    errors = []

    def require(key, expected_type):
        if key not in data:
            errors.append(f"missing required field: '{key}'")
        elif not isinstance(data[key], expected_type):
            errors.append(f"field '{key}' must be {expected_type.__name__}, got {type(data[key]).__name__}")

    require("course_id", str)
    require("items", list)
    if errors:
        return errors

    seen_ids = set()
    for i, item in enumerate(data["items"]):
        if not isinstance(item, dict):
            errors.append(f"items[{i}] is not an object")
            continue

        for key in ("id", "component", "title"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                errors.append(f"items[{i}].{key} must be a non-empty string")
        item_id = item.get("id")
        if item_id in seen_ids:
            errors.append(f"items[{i}].id is a duplicate: {item_id!r}")
        seen_ids.add(item_id)

        for key in ("score", "max_points"):
            value = item.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"items[{i}].{key} must be numeric")
            elif value < 0:
                errors.append(f"items[{i}].{key} must be non-negative")
        max_points = item.get("max_points")
        if isinstance(max_points, (int, float)) and not isinstance(max_points, bool) and max_points <= 0:
            errors.append(f"items[{i}].max_points must be greater than 0")

        if item.get("date"):
            try:
                datetime.strptime(item["date"], "%Y-%m-%d")
            except ValueError:
                errors.append(f"items[{i}].date is not YYYY-MM-DD: {item['date']!r}")

    return errors
```

Add `read_grades`/`write_grades` near the other read/write pairs (after `write_mastery_scores`):

```python
def read_grades(course_id: str) -> dict:
    """Returns the parsed grades.json dict ({"course_id", "items"}). Returns
    an empty skeleton if it doesn't exist yet — a course with no grades
    entered yet is a normal state, not an error, same convention as
    read_quiz_history."""
    path = _course_dir(course_id) / "grades.json"
    if not path.exists():
        return {"course_id": course_id, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GradesStorageError(f"grades.json for '{course_id}' is corrupt: {e}")


def write_grades(course_id: str, data: dict) -> Path:
    """Writes grades.json. Always overwrites — grade items are directly
    user-editable (add/edit/delete), not an append-only log like
    quiz_history.json, so there's no destructive-conflict case to guard
    against the way write_syllabus/write_notes do."""
    out_dir = _course_dir(course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "grades.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_storage_grades.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/storage.py agent/tests/test_storage_grades.py
git commit -m "feat: add grades.json read/write/validate to storage.py"
```

---

## Task 2: `storage.py` — grading config validation + write

**Files:**
- Modify: `agent/services/storage.py`
- Test: `agent/tests/test_storage_grades.py`

**Interfaces:**
- Consumes: `storage.read_syllabus`, `storage.write_syllabus`, `storage.CourseNotFoundError` (all already exist)
- Produces: `storage.validate_grading_config(grading: list, grade_scale: dict = None) -> list[str]`, `storage.write_grading_config(course_id: str, grading: list, grade_scale: dict = None) -> Path`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_storage_grades.py`:

```python
def test_validate_grading_config_valid_returns_no_errors():
    grading = [{"component": "Homework", "weight_pct": 20, "total_items": 8, "drop_lowest": 1}]
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


def test_write_grading_config_merges_into_existing_syllabus(isolated_courses_dir):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [], "topics": ["A"],
    })

    grading = [{"component": "Homework", "weight_pct": 100, "total_items": 5}]
    storage.write_grading_config("cs101", grading, {"passing_pct": 65, "cutoffs": []})

    syllabus = storage.read_syllabus("cs101")
    assert syllabus["grading"] == grading
    assert syllabus["grade_scale"] == {"passing_pct": 65, "cutoffs": []}
    assert syllabus["course_name"] == "CS101"  # untouched


def test_write_grading_config_leaves_grade_scale_untouched_when_omitted(isolated_courses_dir):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [], "grading": [],
        "topics": [], "grade_scale": {"passing_pct": 70, "cutoffs": []},
    })

    storage.write_grading_config("cs101", [{"component": "HW", "weight_pct": 100}])

    syllabus = storage.read_syllabus("cs101")
    assert syllabus["grade_scale"] == {"passing_pct": 70, "cutoffs": []}


def test_write_grading_config_raises_when_no_syllabus_exists(isolated_courses_dir):
    with pytest.raises(storage.CourseNotFoundError):
        storage.write_grading_config("cs101", [{"component": "HW", "weight_pct": 100}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_storage_grades.py -v`
Expected: FAIL — `AttributeError: module 'agent.services.storage' has no attribute 'validate_grading_config'`

- [ ] **Step 3: Implement in `agent/services/storage.py`**

Add after `validate_grades` (from Task 1):

```python
def validate_grading_config(grading: list, grade_scale: dict = None) -> list:
    """Returns a list of error strings. Entries starting with 'WARNING' are
    non-blocking. An empty list means the data is valid."""
    errors = []
    if not isinstance(grading, list):
        return ["'grading' must be a list"]

    for i, g in enumerate(grading):
        if not isinstance(g, dict) or "component" not in g or "weight_pct" not in g:
            errors.append(f"grading[{i}] missing 'component' or 'weight_pct': {g}")
            continue
        if not isinstance(g["weight_pct"], (int, float)):
            errors.append(f"grading[{i}].weight_pct must be numeric: {g['weight_pct']!r}")

        total_items = g.get("total_items")
        if total_items is not None and (not isinstance(total_items, int) or isinstance(total_items, bool) or total_items < 1):
            errors.append(f"grading[{i}].total_items must be a positive integer: {total_items!r}")

        drop_lowest = g.get("drop_lowest")
        if drop_lowest is not None:
            if not isinstance(drop_lowest, int) or isinstance(drop_lowest, bool) or drop_lowest < 0:
                errors.append(f"grading[{i}].drop_lowest must be a non-negative integer: {drop_lowest!r}")
            elif isinstance(total_items, int) and drop_lowest >= total_items:
                errors.append(
                    f"WARNING: grading[{i}].drop_lowest ({drop_lowest}) >= total_items ({total_items}) "
                    f"— would drop every item in this category"
                )

    total_weight = sum(
        g.get("weight_pct", 0) for g in grading
        if isinstance(g, dict) and isinstance(g.get("weight_pct"), (int, float))
    )
    if grading and abs(total_weight - 100) > 0.5:
        errors.append(f"WARNING: grading weights sum to {total_weight}, not 100 (not blocking, but check the source)")

    if grade_scale is not None:
        if not isinstance(grade_scale, dict):
            errors.append("'grade_scale' must be an object")
        else:
            passing_pct = grade_scale.get("passing_pct")
            if passing_pct is not None and not isinstance(passing_pct, (int, float)):
                errors.append(f"grade_scale.passing_pct must be numeric: {passing_pct!r}")
            cutoffs = grade_scale.get("cutoffs", [])
            if not isinstance(cutoffs, list):
                errors.append("'grade_scale.cutoffs' must be a list")
            else:
                for i, c in enumerate(cutoffs):
                    if not isinstance(c, dict) or "letter" not in c or "min_pct" not in c:
                        errors.append(f"grade_scale.cutoffs[{i}] missing 'letter' or 'min_pct': {c}")
                    elif not isinstance(c["min_pct"], (int, float)):
                        errors.append(f"grade_scale.cutoffs[{i}].min_pct must be numeric: {c['min_pct']!r}")

    return errors


def write_grading_config(course_id: str, grading: list, grade_scale: dict = None) -> Path:
    """Merges 'grading' and (if provided) 'grade_scale' into the course's
    existing syllabus.json. Raises CourseNotFoundError if no syllabus exists
    yet — grading categories can only be edited on a real course, not a
    draft. grade_scale is left untouched when omitted from the call, so
    editing categories doesn't require re-specifying the scale every time."""
    syllabus = read_syllabus(course_id)
    if syllabus is None:
        raise CourseNotFoundError(f"no syllabus found for '{course_id}'")
    syllabus["grading"] = grading
    if grade_scale is not None:
        syllabus["grade_scale"] = grade_scale
    return write_syllabus(course_id, syllabus, overwrite=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_storage_grades.py -v`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/storage.py agent/tests/test_storage_grades.py
git commit -m "feat: add grading config validation and write to storage.py"
```

---

## Task 3: `grades.py` — `current_grade()`

**Files:**
- Create: `agent/services/grades.py`
- Test: `agent/tests/test_grades.py` (new)

**Interfaces:**
- Consumes: `storage.read_syllabus`, `storage.read_grades`, `storage.CourseNotFoundError` (all exist)
- Produces: `grades.DEFAULT_GRADE_SCALE: dict`, `grades.current_grade(course_id: str) -> dict` returning
  `{"course_id": str, "overall_pct": float|None, "letter": str|None, "grade_scale": dict, "categories": [{"component": str, "weight_pct": float, "avg_pct": float|None, "entered_count": int, "total_items": int|None, "drop_lowest": int}]}`

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_grades.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_grades.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.services.grades'`

- [ ] **Step 3: Implement `agent/services/grades.py`**

```python
"""
Grade calculation and CRUD. Pure computation over storage.py's syllabus.json
(grading categories/weights) and grades.json (entered scores) — no
async/API calls here, same boundary as mastery.py.
"""

import uuid

from . import reminders, storage

DEFAULT_GRADE_SCALE = {
    "passing_pct": 60,
    "cutoffs": [
        {"letter": "A", "min_pct": 93}, {"letter": "A-", "min_pct": 90},
        {"letter": "B+", "min_pct": 87}, {"letter": "B", "min_pct": 83}, {"letter": "B-", "min_pct": 80},
        {"letter": "C+", "min_pct": 77}, {"letter": "C", "min_pct": 73}, {"letter": "C-", "min_pct": 70},
        {"letter": "D+", "min_pct": 67}, {"letter": "D", "min_pct": 63}, {"letter": "D-", "min_pct": 60},
    ],
}


class ItemNotFoundError(Exception):
    """Raised when item_id doesn't match any entry in a course's grades.json."""


def _require_syllabus(course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id)
    if syllabus is None:
        raise storage.CourseNotFoundError(f"no syllabus found for '{course_id}'")
    return syllabus


def _letter_for(pct: float, grade_scale: dict) -> str:
    cutoffs = sorted(grade_scale.get("cutoffs") or [], key=lambda c: -c["min_pct"])
    for c in cutoffs:
        if pct >= c["min_pct"]:
            return c["letter"]
    return "F"


def _category_pcts(items: list, component: str) -> list:
    return sorted(i["score"] / i["max_points"] * 100 for i in items if i["component"] == component)


def current_grade(course_id: str) -> dict:
    """"My grade right now" — categories with zero entered items are
    excluded entirely (not treated as 0%), and the overall percentage is a
    weighted average renormalized across only the categories that have
    data, so an ungraded Final Exam doesn't crater today's number."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id)["items"]
    grade_scale = syllabus.get("grade_scale") or DEFAULT_GRADE_SCALE

    categories = []
    graded_weight = 0.0
    weighted_sum = 0.0

    for g in grading:
        component = g["component"]
        weight = g.get("weight_pct", 0)
        pcts = _category_pcts(items, component)
        entered_count = len(pcts)
        drop_lowest = g.get("drop_lowest") or 0

        avg_pct = None
        if entered_count > 0:
            d = min(drop_lowest, entered_count - 1)
            kept = pcts[d:]
            avg_pct = round(sum(kept) / len(kept), 2)
            graded_weight += weight
            weighted_sum += weight * avg_pct

        categories.append({
            "component": component, "weight_pct": weight, "avg_pct": avg_pct,
            "entered_count": entered_count, "total_items": g.get("total_items"), "drop_lowest": drop_lowest,
        })

    overall_pct = round(weighted_sum / graded_weight, 2) if graded_weight > 0 else None
    letter = _letter_for(overall_pct, grade_scale) if overall_pct is not None else None

    return {
        "course_id": course_id, "overall_pct": overall_pct, "letter": letter,
        "grade_scale": grade_scale, "categories": categories,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_grades.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/grades.py agent/tests/test_grades.py
git commit -m "feat: add grades.py with current_grade()"
```

---

## Task 4: `grades.py` — item CRUD

**Files:**
- Modify: `agent/services/grades.py`
- Test: `agent/tests/test_grades.py`

**Interfaces:**
- Consumes: `storage.read_grades`, `storage.write_grades` (Task 1), `_require_syllabus` (Task 3)
- Produces: `grades.add_item(course_id, component, title, score, max_points, date=None) -> dict`, `grades.update_item(course_id, item_id, **fields) -> dict`, `grades.delete_item(course_id, item_id) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_grades.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_grades.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.grades' has no attribute 'add_item'`

- [ ] **Step 3: Implement in `agent/services/grades.py`**

Add at the end of the file:

```python
def add_item(course_id: str, component: str, title: str, score: float, max_points: float, date: str = None) -> dict:
    syllabus = _require_syllabus(course_id)
    valid_components = {g["component"] for g in syllabus.get("grading", [])}
    if component not in valid_components:
        raise ValueError(f"'{component}' isn't a grading category for '{course_id}' (valid: {sorted(valid_components)})")

    data = storage.read_grades(course_id)
    item = {
        "id": uuid.uuid4().hex, "component": component, "title": title,
        "score": score, "max_points": max_points, "date": date,
    }
    data["items"].append(item)
    storage.write_grades(course_id, data)
    return item


def update_item(course_id: str, item_id: str, **fields) -> dict:
    data = storage.read_grades(course_id)
    for item in data["items"]:
        if item["id"] == item_id:
            for key, value in fields.items():
                if value is not None:
                    item[key] = value
            storage.write_grades(course_id, data)
            return item
    raise ItemNotFoundError(f"no grade item '{item_id}' for '{course_id}'")


def delete_item(course_id: str, item_id: str) -> None:
    data = storage.read_grades(course_id)
    remaining = [i for i in data["items"] if i["id"] != item_id]
    if len(remaining) == len(data["items"]):
        raise ItemNotFoundError(f"no grade item '{item_id}' for '{course_id}'")
    data["items"] = remaining
    storage.write_grades(course_id, data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_grades.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/grades.py agent/tests/test_grades.py
git commit -m "feat: add grade item CRUD to grades.py"
```

---

## Task 5: `grades.py` — `grade_needed()`

**Files:**
- Modify: `agent/services/grades.py`
- Test: `agent/tests/test_grades.py`

**Interfaces:**
- Produces: `grades.grade_needed(course_id: str, target_pct: float) -> dict` returning
  `{"target_pct": float, "locked": bool, "p_needed": float|None, "achievable": bool, "ceiling_pct": float|None, "notes": [str]}`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_grades.py`:

```python
def test_grade_needed_solves_flat_score_for_remaining_items(isolated_courses_dir):
    # One category, 100% weight, 4 total items, 2 entered averaging 80%.
    # To reach 90% overall: (80*2 + p*2)/4 = 90 -> p = 100.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 90)

    assert result["locked"] is False
    assert result["p_needed"] == pytest.approx(100.0)
    assert result["achievable"] is True
    assert result["ceiling_pct"] is None


def test_grade_needed_reports_impossible_target_with_ceiling(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 10, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 10, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 99)

    assert result["achievable"] is False
    assert result["p_needed"] > 100
    assert result["ceiling_pct"] == pytest.approx(55.0)  # (10+10+100+100)/4


def test_grade_needed_already_guaranteed_reports_zero(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 100, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 60)

    assert result["p_needed"] == 0
    assert result["achievable"] is True


def test_grade_needed_locked_when_nothing_left(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 2}])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
        {"id": "2", "component": "Homework", "title": "HW2", "score": 80, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 90)

    assert result["locked"] is True
    assert result["p_needed"] is None
    assert result["ceiling_pct"] == pytest.approx(80.0)
    assert result["achievable"] is False


def test_grade_needed_category_without_total_items_is_treated_as_closed(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Participation", "weight_pct": 100}])
    _seed_items("cs101", [
        {"id": "1", "component": "Participation", "title": "P1", "score": 70, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 90)

    assert result["locked"] is True
    assert result["ceiling_pct"] == pytest.approx(70.0)


def test_grade_needed_notes_empty_category_with_no_total_items(isolated_courses_dir):
    _seed_syllabus("cs101", [
        {"component": "Homework", "weight_pct": 50, "total_items": 2},
        {"component": "Extra Credit", "weight_pct": 50},  # no items, no total_items
    ])
    _seed_items("cs101", [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100},
    ])

    result = grades.grade_needed("cs101", 90)

    assert any("Extra Credit" in note for note in result["notes"])


def test_grade_needed_raises_without_syllabus(isolated_courses_dir):
    with pytest.raises(storage.CourseNotFoundError):
        grades.grade_needed("cs101", 90)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_grades.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.grades' has no attribute 'grade_needed'`

- [ ] **Step 3: Implement in `agent/services/grades.py`**

Add at the end of the file:

```python
def grade_needed(course_id: str, target_pct: float) -> dict:
    """Solves the flat score 'p' needed on every remaining ungraded item
    (across every category that has total_items set) to hit target_pct
    overall. A category without total_items is treated as closed — its
    current average (or 0 with no entries at all) is locked in as final,
    and that's flagged in 'notes' since it silently caps the achievable
    grade."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id)["items"]

    total_weight = sum(g.get("weight_pct", 0) for g in grading) or 100.0
    locked_contribution = 0.0  # A: pct points already locked in, on a 0-100 scale
    remaining_slope = 0.0  # B: pct points contributed per unit of p
    notes = []

    for g in grading:
        component = g["component"]
        weight = g.get("weight_pct", 0)
        total_items = g.get("total_items")
        drop_lowest = g.get("drop_lowest") or 0

        pcts = _category_pcts(items, component)
        entered_count = len(pcts)
        d = min(drop_lowest, max(entered_count - 1, 0))
        kept = pcts[d:]
        kept_sum = sum(kept)
        kept_count = len(kept)

        if total_items is None:
            remaining = 0
            if entered_count == 0:
                notes.append(
                    f"{component} has no items entered and no total_items set — "
                    f"its 0% is currently capping your achievable grade"
                )
        else:
            remaining = max(total_items - entered_count, 0)

        denom = kept_count + remaining
        if denom == 0:
            continue

        locked_contribution += weight * (kept_sum / denom) / total_weight
        remaining_slope += weight * (remaining / denom) / total_weight

    if remaining_slope == 0:
        return {
            "target_pct": target_pct, "locked": True, "p_needed": None,
            "achievable": locked_contribution >= target_pct,
            "ceiling_pct": round(locked_contribution, 2), "notes": notes,
        }

    p_needed = max((target_pct - locked_contribution) / remaining_slope, 0)
    achievable = p_needed <= 100
    ceiling = locked_contribution + remaining_slope * 100

    return {
        "target_pct": target_pct, "locked": False,
        "p_needed": round(p_needed, 2), "achievable": achievable,
        "ceiling_pct": None if achievable else round(ceiling, 2), "notes": notes,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_grades.py -v`
Expected: PASS (23 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/grades.py agent/tests/test_grades.py
git commit -m "feat: add grade_needed() what-if solver to grades.py"
```

---

## Task 6: `grades.py` — `missable_by_category()`

**Files:**
- Modify: `agent/services/grades.py`
- Test: `agent/tests/test_grades.py`

**Interfaces:**
- Produces: `grades.missable_by_category(course_id: str, target_pct: float) -> list[dict]` — each entry:
  `{"component": str, "remaining": int|None, "missable": int|None, "omitted_reason": str|None}`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_grades.py`:

```python
def test_missable_by_category_computes_max_missable(isolated_courses_dir):
    # 4 total, 0 entered, target 75%: missing k of 4 while acing the rest
    # must keep (4-k)*100/4 >= 75 -> k <= 1.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])

    result = grades.missable_by_category("cs101", 75)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["remaining"] == 4
    assert hw["missable"] == 1
    assert hw["omitted_reason"] is None


def test_missable_by_category_zero_when_must_ace_everything(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])

    result = grades.missable_by_category("cs101", 100)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["missable"] == 0


def test_missable_by_category_omits_category_without_total_items(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Participation", "weight_pct": 100}])

    result = grades.missable_by_category("cs101", 75)

    p = next(r for r in result if r["component"] == "Participation")
    assert p["missable"] is None
    assert p["omitted_reason"] is not None


def test_missable_by_category_omits_category_with_nothing_remaining(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 1}])
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 80, "max_points": 100}])

    result = grades.missable_by_category("cs101", 75)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["remaining"] == 0
    assert hw["missable"] is None
    assert hw["omitted_reason"] is not None


def test_missable_by_category_accounts_for_entered_scores(isolated_courses_dir):
    # 1 entered at 100%, 3 remaining, target 75%: (100 + (3-k)*100)/4 >= 75 -> k <= 1.
    _seed_syllabus("cs101", [{"component": "Homework", "weight_pct": 100, "total_items": 4}])
    _seed_items("cs101", [{"id": "1", "component": "Homework", "title": "HW1", "score": 100, "max_points": 100}])

    result = grades.missable_by_category("cs101", 75)

    hw = next(r for r in result if r["component"] == "Homework")
    assert hw["missable"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_grades.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.grades' has no attribute 'missable_by_category'`

- [ ] **Step 3: Implement in `agent/services/grades.py`**

Add at the end of the file:

```python
def missable_by_category(course_id: str, target_pct: float) -> list:
    """Per category (never blended across categories — a missed final exam
    and a missed homework aren't comparable): assuming every other
    remaining item in this category scores 100%, the largest number of
    remaining items that can score 0% while this category's own average
    still meets target_pct."""
    syllabus = _require_syllabus(course_id)
    grading = syllabus.get("grading", [])
    items = storage.read_grades(course_id)["items"]

    results = []
    for g in grading:
        component = g["component"]
        total_items = g.get("total_items")
        drop_lowest = g.get("drop_lowest") or 0

        pcts = _category_pcts(items, component)
        entered_count = len(pcts)

        if total_items is None:
            results.append({
                "component": component, "remaining": None, "missable": None,
                "omitted_reason": "total_items not set for this category",
            })
            continue

        remaining = max(total_items - entered_count, 0)
        if remaining == 0:
            results.append({
                "component": component, "remaining": 0, "missable": None,
                "omitted_reason": "no remaining items in this category",
            })
            continue

        d = min(drop_lowest, max(entered_count - 1, 0))
        kept = pcts[d:]
        kept_sum = sum(kept)
        denom = len(kept) + remaining

        missable = 0
        for k in range(remaining, -1, -1):
            projected = (kept_sum + (remaining - k) * 100) / denom
            if projected >= target_pct:
                missable = k
                break

        results.append({"component": component, "remaining": remaining, "missable": missable, "omitted_reason": None})

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_grades.py -v`
Expected: PASS (28 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/grades.py agent/tests/test_grades.py
git commit -m "feat: add missable_by_category() to grades.py"
```

---

## Task 7: `grades.py` — `all_courses_summary()`

**Files:**
- Modify: `agent/services/grades.py`
- Test: `agent/tests/test_grades.py`

**Interfaces:**
- Consumes: `reminders.list_courses()` (exists, used by `dashboard.py` the same way)
- Produces: `grades.all_courses_summary() -> dict` returning
  `{"average_pct": float|None, "excluded_count": int, "courses": [{"course_id": str, "course_name": str, "current_pct": float|None, "letter": str|None} | {"course_id": str, "error": str}]}`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_grades.py`:

```python
def test_all_courses_summary_averages_only_graded_courses(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}])
    _seed_items("cs101", [{"id": "1", "component": "HW", "title": "HW1", "score": 80, "max_points": 100}])
    _seed_syllabus("psyc201", [{"component": "HW", "weight_pct": 100}])  # no items entered

    result = grades.all_courses_summary()

    assert result["average_pct"] == 80.0
    assert result["excluded_count"] == 1
    cs101 = next(c for c in result["courses"] if c["course_id"] == "cs101")
    assert cs101["current_pct"] == 80.0
    psyc201 = next(c for c in result["courses"] if c["course_id"] == "psyc201")
    assert psyc201["current_pct"] is None


def test_all_courses_summary_null_average_when_nothing_graded(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}])

    result = grades.all_courses_summary()

    assert result["average_pct"] is None
    assert result["excluded_count"] == 1


def test_all_courses_summary_no_courses_at_all(isolated_courses_dir):
    result = grades.all_courses_summary()

    assert result["average_pct"] is None
    assert result["courses"] == []
    assert result["excluded_count"] == 0


def test_all_courses_summary_isolates_corrupt_course(isolated_courses_dir):
    _seed_syllabus("cs101", [{"component": "HW", "weight_pct": 100}])
    _seed_items("cs101", [{"id": "1", "component": "HW", "title": "HW1", "score": 80, "max_points": 100}])

    bad_dir = isolated_courses_dir / "badcourse"
    bad_dir.mkdir()
    (bad_dir / "syllabus.json").write_text('{"course_id": "badcourse", "course_name": "Bad", "dates": [], "grading": [], "topics": []}', encoding="utf-8")
    (bad_dir / "grades.json").write_text("{not valid json", encoding="utf-8")

    result = grades.all_courses_summary()

    bad = next(c for c in result["courses"] if c["course_id"] == "badcourse")
    assert "error" in bad
    cs101 = next(c for c in result["courses"] if c["course_id"] == "cs101")
    assert cs101["current_pct"] == 80.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_grades.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.grades' has no attribute 'all_courses_summary'`

- [ ] **Step 3: Implement in `agent/services/grades.py`**

Change the import line at the top from `from . import reminders, storage` (it already reads `from . import storage` only — update it) to:

```python
from . import reminders, storage
```

Add at the end of the file:

```python
def all_courses_summary() -> dict:
    """Plain average of current_grade() across courses that have at least
    one graded item, following dashboard.build_dashboard()'s per-course
    try/except isolation — one corrupt course doesn't break the rollup for
    the rest."""
    courses = []
    grades_total = 0.0
    graded_count = 0

    for course_id in reminders.list_courses():
        try:
            g = current_grade(course_id)
            syllabus = storage.read_syllabus(course_id)
            entry = {
                "course_id": course_id, "course_name": syllabus.get("course_name", course_id),
                "current_pct": g["overall_pct"], "letter": g["letter"],
            }
            if g["overall_pct"] is not None:
                grades_total += g["overall_pct"]
                graded_count += 1
        except (storage.SyllabusStorageError, storage.GradesStorageError) as e:
            entry = {"course_id": course_id, "error": str(e)}
        courses.append(entry)

    average_pct = round(grades_total / graded_count, 2) if graded_count > 0 else None
    return {"average_pct": average_pct, "excluded_count": len(courses) - graded_count, "courses": courses}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_grades.py -v`
Expected: PASS (32 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/services/grades.py agent/tests/test_grades.py
git commit -m "feat: add all_courses_summary() to grades.py"
```

---

## Task 8: API — `GradingConfigView`

**Files:**
- Modify: `agent/serializers.py`, `agent/views.py`, `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `storage.validate_grading_config`, `storage.write_grading_config` (Task 2), `grades.DEFAULT_GRADE_SCALE` (Task 3)
- Produces: `GET/PUT /api/courses/<course_id>/grading/`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`:

```python
def test_grading_config_get_returns_default_scale_when_unset(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["grading"] == [{"component": "Homework", "weight_pct": 100}]
    assert response.data["grade_scale"]["passing_pct"] == 60


def test_grading_config_get_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grading/")
    assert response.status_code == 404


def test_grading_config_put_updates_categories(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 5}]},
        format="json",
    )

    assert response.status_code == 200
    updated = storage.read_syllabus("cs101")
    assert updated["grading"] == [{"component": "Homework", "weight_pct": 100, "total_items": 5, "drop_lowest": None}]


def test_grading_config_put_rejects_invalid_total_items(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Homework", "weight_pct": 100, "total_items": 0}]},
        format="json",
    )

    assert response.status_code == 422


def test_grading_config_put_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.put(
        "/api/courses/cs101/grading/", {"grading": []}, format="json",
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_views.py -k grading_config -v`
Expected: FAIL with 404 "No GradingConfigView" / `NoReverseMatch`-style routing failure (no `/grading/` route registered yet)

- [ ] **Step 3: Implement**

In `agent/serializers.py`, add:

```python
class GradingCategorySerializer(serializers.Serializer):
    component = serializers.CharField(allow_blank=False)
    weight_pct = serializers.FloatField()
    total_items = serializers.IntegerField(required=False, allow_null=True, default=None)
    drop_lowest = serializers.IntegerField(required=False, allow_null=True, default=None)


class GradingConfigRequestSerializer(serializers.Serializer):
    grading = GradingCategorySerializer(many=True)
    grade_scale = serializers.DictField(required=False, allow_null=True, default=None)
```

In `agent/views.py`, add `grades` to the services import (change `from .services import chunk_notes, dashboard, domain_suggestions, mastery, quiz, references, reminders, sessions, storage` to include `grades`) and add `GradingConfigRequestSerializer` to the serializers import block. Then add the view (after `DomainsView`, before `MasteryView`):

```python
class GradingConfigView(APIView):
    """
    GET /api/courses/<course_id>/grading/ — the grading array plus the
    effective grade scale (the course's own, or the default one if it
    hasn't set one).

    PUT /api/courses/<course_id>/grading/
    body: {"grading": [{"component", "weight_pct", "total_items"?, "drop_lowest"?}, ...], "grade_scale"?: {...}}
    """

    async def get(self, request, course_id):
        syllabus = await sync_to_async(storage.read_syllabus)(course_id)
        if syllabus is None:
            return Response({"detail": f"no syllabus found for '{course_id}'"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "grading": syllabus.get("grading", []),
            "grade_scale": syllabus.get("grade_scale") or grades.DEFAULT_GRADE_SCALE,
        }, status=status.HTTP_200_OK)

    async def put(self, request, course_id):
        serializer = GradingConfigRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        grading = serializer.validated_data["grading"]
        grade_scale = serializer.validated_data.get("grade_scale")
        errors = storage.validate_grading_config(grading, grade_scale)
        if errors:
            return Response({"detail": "invalid grading config", "errors": errors}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            await sync_to_async(storage.write_grading_config)(course_id, grading, grade_scale)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"grading": grading, "grade_scale": grade_scale or grades.DEFAULT_GRADE_SCALE}, status=status.HTTP_200_OK)
```

In `agent/urls.py`, add (after the `domains/` lines, before `mastery/`):

```python
    path("courses/<slug:course_id>/grading/", views.GradingConfigView.as_view(), name="grading-config"),
```

In `agent/tests/test_views.py`, add the `_seed_syllabus` used by these tests if not already matching — it already exists (`_seed_syllabus(course_id)` at the top of the file with `grading: []`), so no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_views.py -k grading_config -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add GET/PUT /api/courses/<id>/grading/ endpoint"
```

---

## Task 9: API — grade items (`GradesView`, `GradeItemsView`, `GradeItemDetailView`)

**Files:**
- Modify: `agent/serializers.py`, `agent/views.py`, `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `grades.current_grade`, `grades.add_item`, `grades.update_item`, `grades.delete_item`, `grades.ItemNotFoundError` (Tasks 3-4), `storage.read_grades` (Task 1)
- Produces: `GET /api/courses/<course_id>/grades/`, `POST /api/courses/<course_id>/grades/items/`, `PATCH/DELETE /api/courses/<course_id>/grades/items/<item_id>/`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`:

```python
def test_grades_get_returns_items_and_breakdown(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
    ]})

    response = api_client.get("/api/courses/cs101/grades/")

    assert response.status_code == 200
    assert len(response.data["items"]) == 1
    assert response.data["grade"]["overall_pct"] == 90.0


def test_grades_get_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grades/")
    assert response.status_code == 404


def test_grade_items_post_adds_item(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })

    response = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["component"] == "Homework"
    assert len(storage.read_grades("cs101")["items"]) == 1


def test_grade_items_post_422s_for_unknown_component(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })

    response = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Nonexistent", "title": "X", "score": 1, "max_points": 1},
        format="json",
    )

    assert response.status_code == 422


def test_grade_item_detail_patch_updates(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    add = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )
    item_id = add.data["id"]

    response = api_client.patch(f"/api/courses/cs101/grades/items/{item_id}/", {"score": 95}, format="json")

    assert response.status_code == 200
    assert response.data["score"] == 95


def test_grade_item_detail_patch_404s_for_unknown_item(isolated_courses_dir, api_client):
    response = api_client.patch("/api/courses/cs101/grades/items/nope/", {"score": 1}, format="json")
    assert response.status_code == 404


def test_grade_item_detail_delete_removes_item(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    add = api_client.post(
        "/api/courses/cs101/grades/items/",
        {"component": "Homework", "title": "HW 1", "score": 90, "max_points": 100},
        format="json",
    )
    item_id = add.data["id"]

    response = api_client.delete(f"/api/courses/cs101/grades/items/{item_id}/")

    assert response.status_code == 204
    assert storage.read_grades("cs101")["items"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_views.py -k "grades_get or grade_items or grade_item_detail" -v`
Expected: FAIL — routes don't exist yet

- [ ] **Step 3: Implement**

In `agent/serializers.py`, add:

```python
class AddGradeItemRequestSerializer(serializers.Serializer):
    component = serializers.CharField(allow_blank=False)
    title = serializers.CharField(allow_blank=False)
    score = serializers.FloatField(min_value=0)
    max_points = serializers.FloatField(min_value=0.01)
    date = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class UpdateGradeItemRequestSerializer(serializers.Serializer):
    component = serializers.CharField(required=False, allow_blank=False, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    score = serializers.FloatField(required=False, min_value=0, default=None)
    max_points = serializers.FloatField(required=False, min_value=0.01, default=None)
    date = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
```

In `agent/views.py`, add `AddGradeItemRequestSerializer` and `UpdateGradeItemRequestSerializer` to the serializers import, then add (after `GradingConfigView`):

```python
class GradesView(APIView):
    """GET /api/courses/<course_id>/grades/ — every entered item plus the
    current grade breakdown (grades.current_grade()), which itself includes
    the effective grade_scale."""

    async def get(self, request, course_id):
        try:
            grade = await sync_to_async(grades.current_grade)(course_id)
            items = (await sync_to_async(storage.read_grades)(course_id))["items"]
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.GradesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"items": items, "grade": grade}, status=status.HTTP_200_OK)


class GradeItemsView(APIView):
    """POST /api/courses/<course_id>/grades/items/
    body: {"component", "title", "score", "max_points", "date"?}"""

    async def post(self, request, course_id):
        serializer = AddGradeItemRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data

        try:
            item = await sync_to_async(grades.add_item)(
                course_id, d["component"], d["title"], d["score"], d["max_points"], d.get("date"),
            )
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(item, status=status.HTTP_201_CREATED)


class GradeItemDetailView(APIView):
    """PATCH /api/courses/<course_id>/grades/items/<item_id>/ — partial update.
    DELETE /api/courses/<course_id>/grades/items/<item_id>/"""

    async def patch(self, request, course_id, item_id):
        serializer = UpdateGradeItemRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        fields = {k: v for k, v in serializer.validated_data.items() if v is not None}

        try:
            item = await sync_to_async(grades.update_item)(course_id, item_id, **fields)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(item, status=status.HTTP_200_OK)

    async def delete(self, request, course_id, item_id):
        try:
            await sync_to_async(grades.delete_item)(course_id, item_id)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)
```

In `agent/urls.py`, add (after the new `grading/` line):

```python
    path("courses/<slug:course_id>/grades/", views.GradesView.as_view(), name="grades-detail"),
    path("courses/<slug:course_id>/grades/items/", views.GradeItemsView.as_view(), name="grade-items"),
    path("courses/<slug:course_id>/grades/items/<str:item_id>/", views.GradeItemDetailView.as_view(), name="grade-item-detail"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_views.py -k "grades_get or grade_items or grade_item_detail" -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add grade items CRUD endpoints"
```

---

## Task 10: API — `GradesWhatIfView` and `GradesSummaryView`

**Files:**
- Modify: `agent/views.py`, `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `grades.grade_needed`, `grades.missable_by_category` (Tasks 5-6), `grades.all_courses_summary` (Task 7)
- Produces: `GET /api/courses/<course_id>/grades/whatif/?target=<pct>`, `GET /api/grades/summary/`

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_views.py`:

```python
def test_grades_whatif_returns_needed_and_missable(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100, "total_items": 4}], "topics": [],
    })

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")

    assert response.status_code == 200
    assert "grade_needed" in response.data
    assert "missable_by_category" in response.data


def test_grades_whatif_400s_for_non_numeric_target(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/grades/whatif/?target=notanumber")

    assert response.status_code == 400


def test_grades_whatif_404s_without_syllabus(isolated_courses_dir, api_client):
    response = api_client.get("/api/courses/cs101/grades/whatif/?target=75")
    assert response.status_code == 404


def test_grades_summary_returns_rollup(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS101", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 88, "max_points": 100},
    ]})

    response = api_client.get("/api/grades/summary/")

    assert response.status_code == 200
    assert response.data["average_pct"] == 88.0


def test_grades_summary_empty_when_no_courses(isolated_courses_dir, api_client):
    response = api_client.get("/api/grades/summary/")

    assert response.status_code == 200
    assert response.data["courses"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_views.py -k "grades_whatif or grades_summary" -v`
Expected: FAIL — routes don't exist yet

- [ ] **Step 3: Implement**

In `agent/views.py`, add (after `GradeItemDetailView`):

```python
class GradesWhatIfView(APIView):
    """GET /api/courses/<course_id>/grades/whatif/?target=<pct>"""

    async def get(self, request, course_id):
        target_raw = request.query_params.get("target")
        try:
            target_pct = float(target_raw)
        except (TypeError, ValueError):
            return Response({"detail": "query param 'target' must be a number"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            needed = await sync_to_async(grades.grade_needed)(course_id, target_pct)
            missable = await sync_to_async(grades.missable_by_category)(course_id, target_pct)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"grade_needed": needed, "missable_by_category": missable}, status=status.HTTP_200_OK)


class GradesSummaryView(APIView):
    """GET /api/grades/summary/ — all-courses rollup."""

    async def get(self, request):
        data = await sync_to_async(grades.all_courses_summary)()
        return Response(data, status=status.HTTP_200_OK)
```

In `agent/urls.py`, add (after the new `grade-item-detail` line):

```python
    path("courses/<slug:course_id>/grades/whatif/", views.GradesWhatIfView.as_view(), name="grades-whatif"),
```

And add near the bottom, alongside `reminders/` and `dashboard/`:

```python
    path("grades/summary/", views.GradesSummaryView.as_view(), name="grades-summary"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest agent/tests/test_views.py -k "grades_whatif or grades_summary" -v`
Expected: PASS (5 passed)

Then run the full backend test suite to confirm nothing else broke:

Run: `pytest agent/tests/ -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "feat: add grades whatif and all-courses summary endpoints"
```

---

## Task 11: CLI — `manage.py grades`

**Files:**
- Create: `agent/management/commands/grades.py`

**Interfaces:**
- Consumes: `grades.add_item`, `grades.current_grade`, `grades.grade_needed`, `grades.missable_by_category` (Tasks 3-6), `storage.read_grades`, `storage.CourseNotFoundError`

- [ ] **Step 1: Implement `agent/management/commands/grades.py`**

```python
from django.core.management.base import BaseCommand, CommandError

from agent.services import grades, storage
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = "Add, list, or run what-if projections against a course's grades (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument(
            "--add", nargs=4, metavar=("COMPONENT", "TITLE", "SCORE", "MAX_POINTS"),
            help="Add a grade item, e.g. --add Homework \"HW 3\" 92 100",
        )
        parser.add_argument("--date", default=None, help="Date for --add, YYYY-MM-DD")
        parser.add_argument("--list", action="store_true", help="List entered items and the current grade")
        parser.add_argument(
            "--whatif", type=float, default=None, metavar="TARGET_PCT",
            help="Show the score needed on remaining work, and per-category missable counts, to hit TARGET_PCT",
        )

    def handle(self, *args, **options):
        course_id = options["course_id"]

        if options["add"]:
            component, title, score, max_points = options["add"]
            try:
                item = grades.add_item(course_id, component, title, float(score), float(max_points), options["date"])
            except (CourseNotFoundError, ValueError) as e:
                raise CommandError(str(e))
            self.stdout.write(self.style.SUCCESS(
                f"Added {item['title']} ({item['component']}): {item['score']}/{item['max_points']}"
            ))
            return

        if options["list"]:
            try:
                grade = grades.current_grade(course_id)
            except CourseNotFoundError as e:
                raise CommandError(str(e))
            for item in storage.read_grades(course_id)["items"]:
                self.stdout.write(f"  [{item['component']}] {item['title']}: {item['score']}/{item['max_points']}")
            overall = grade["overall_pct"]
            self.stdout.write(self.style.SUCCESS(
                f"Overall: {overall}% ({grade['letter']})" if overall is not None else "Overall: no grades entered yet"
            ))
            return

        if options["whatif"] is not None:
            try:
                needed = grades.grade_needed(course_id, options["whatif"])
                missable = grades.missable_by_category(course_id, options["whatif"])
            except CourseNotFoundError as e:
                raise CommandError(str(e))

            if needed["locked"]:
                self.stdout.write(f"Grade is locked at {needed['ceiling_pct']}% — nothing left to change.")
            elif needed["achievable"]:
                self.stdout.write(f"You need to average {needed['p_needed']}% on everything remaining to hit {options['whatif']}%.")
            else:
                self.stdout.write(f"Not achievable: would need {needed['p_needed']}% (max possible is {needed['ceiling_pct']}%).")
            for note in needed["notes"]:
                self.stdout.write(self.style.WARNING(note))
            for m in missable:
                if m["omitted_reason"]:
                    continue
                self.stdout.write(f"  {m['component']}: can miss {m['missable']} of {m['remaining']} remaining")
            return

        raise CommandError("specify --add, --list, or --whatif")
```

- [ ] **Step 2: Manually verify**

Run:
```bash
python manage.py extract_syllabus test-syllabi/cs101_clean.txt cs101 --course-name "Intro to CS" --force
python manage.py grades cs101 --add Homework "HW 1" 90 100
python manage.py grades cs101 --list
python manage.py grades cs101 --whatif 85
```
Expected: `--add` prints a success line; `--list` prints the one item and an overall percentage (or "no grades entered yet" if `cs101`'s syllabus has no `Homework` category — in that case use whatever `component` name the extracted syllabus actually has); `--whatif` prints either a needed-average line or a locked/not-achievable line, with no traceback.

- [ ] **Step 3: Commit**

```bash
git add agent/management/commands/grades.py
git commit -m "feat: add manage.py grades CLI"
```

---

## Task 12: Frontend — nav button, tab state, and `loadGrades` wiring

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET /api/courses/<id>/grades/` (Task 9), `GET /api/grades/summary/` (Task 10)
- Produces: `tab: 'grades'` state branch, `isGrades` render flag, `goGrades`/`navBtnStyleGrades` template vars, `this.loadGrades(courseId)`, `this.loadGradesSummary()`

This task only wires navigation, state, and data loading — no visible tab content yet (Task 13 adds the markup). After this task, clicking "Grade Calculator" should switch the sidebar highlight and silently fetch data with no errors in the browser console, even though nothing renders for the tab body yet.

- [ ] **Step 1: Add state fields**

In the `state = { ... }` block (around line 775, right after the `quizStep...quizErrorSource` line), add:

```javascript
    gradesLoading: false, gradesError: null, gradesItems: [], gradesBreakdown: null,
    gradesWhatIfTarget: '', gradesWhatIfLoading: false, gradesWhatIfError: null, gradesWhatIf: null,
    gradesSummaryLoading: false, gradesSummaryError: null, gradesSummary: null,
    addGradeOpen: false, addGradeEditingId: null, addGradeComponent: '', addGradeTitle: '',
    addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '', addGradeLoading: false, addGradeError: null,
```

Add sequence counters next to the existing ones (`_quizSeq = 0; ...` block around line 793):

```javascript
  _gradesSeq = 0;
  _gradesWhatIfSeq = 0;
  _gradesSummarySeq = 0;
```

- [ ] **Step 2: Add fetch methods**

After `loadQuestion` and its `.catch()` block ends (the block starting at line 956 ends around line 972 — add these methods right after that closing `}`), add:

```javascript
  loadGrades(courseId) {
    const seq = ++this._gradesSeq;
    this.setState({ gradesLoading: true, gradesError: null });
    fetch(`/api/courses/${courseId}/grades/`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesSeq) return;
        if (!ok) { this.setState({ gradesLoading: false, gradesError: data.detail || 'Could not load grades.' }); return; }
        const defaultTarget = (data.grade.grade_scale && data.grade.grade_scale.passing_pct) || 60;
        this.setState({
          gradesLoading: false, gradesItems: data.items, gradesBreakdown: data.grade,
          gradesWhatIfTarget: this.state.gradesWhatIfTarget || String(defaultTarget),
        });
        this.loadGradesWhatIf(courseId);
      })
      .catch(e => {
        if (seq !== this._gradesSeq) return;
        this.setState({ gradesLoading: false, gradesError: 'Network error: ' + e.message });
      });
  }

  loadGradesWhatIf(courseId) {
    const target = this.state.gradesWhatIfTarget;
    if (!target) return;
    const seq = ++this._gradesWhatIfSeq;
    this.setState({ gradesWhatIfLoading: true, gradesWhatIfError: null });
    fetch(`/api/courses/${courseId}/grades/whatif/?target=${encodeURIComponent(target)}`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesWhatIfSeq) return;
        if (!ok) { this.setState({ gradesWhatIfLoading: false, gradesWhatIfError: data.detail || 'Could not compute what-if.' }); return; }
        this.setState({ gradesWhatIfLoading: false, gradesWhatIf: data });
      })
      .catch(e => {
        if (seq !== this._gradesWhatIfSeq) return;
        this.setState({ gradesWhatIfLoading: false, gradesWhatIfError: 'Network error: ' + e.message });
      });
  }

  loadGradesSummary() {
    const seq = ++this._gradesSummarySeq;
    this.setState({ gradesSummaryLoading: true, gradesSummaryError: null });
    fetch('/api/grades/summary/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradesSummarySeq) return;
        if (!ok) { this.setState({ gradesSummaryLoading: false, gradesSummaryError: data.detail || 'Could not load the semester summary.' }); return; }
        this.setState({ gradesSummaryLoading: false, gradesSummary: data });
      })
      .catch(e => {
        if (seq !== this._gradesSummarySeq) return;
        this.setState({ gradesSummaryLoading: false, gradesSummaryError: 'Network error: ' + e.message });
      });
  }
```

- [ ] **Step 3: Wire tab switching**

In `renderVals()`, inside `setTab` (around line 1310-1339), the current structure bounces `quiz`/`progress`/`chat` differently and falls through to a generic `else` branch for everything else (which today only handles nothing else, but is where `'grades'` would land). Replace the `setTab` function body with:

```javascript
    const setTab = (t) => {
      this._quizSeq++;
      this._chatSeq++;
      if (t === 'dashboard') {
        this.setState({ tab: t });
        this.loadDashboard();
        this.loadDashboardRecent(s.course);
        return;
      }
      if (t === 'grades' && s.course === 'all') {
        this.setState({ tab: t });
        this.loadGradesSummary();
        return;
      }
      const targetCourse = s.course === 'all'
        ? (fallbackCourse || (s.courseDrafts[0] && s.courseDrafts[0].course_id) || null)
        : s.course;
      if (!targetCourse) return;
      if (t === 'quiz') {
        goToQuiz(targetCourse);
      } else if (t === 'chat') {
        if (targetCourse !== s.course) {
          this.setState({ tab: t, course: targetCourse, chatMessages: [], chatInput: '', chatError: null, chatSessionId: null });
        } else {
          this.setState({ tab: t });
        }
        this.loadChatSessions(targetCourse);
      } else if (t === 'progress') {
        this.setState({ tab: t, course: targetCourse });
        this.loadDashboard();
        this.loadDashboardRecent(targetCourse);
      } else if (t === 'grades') {
        this.setState({ tab: t, course: targetCourse, gradesWhatIfTarget: '' });
        this.loadGrades(targetCourse);
      } else {
        this.setState({ tab: t, course: targetCourse });
      }
    };
```

Now update `selectCourse` (right below `setTab`, around line 1341-1367) so switching the course chip while already on the Grades tab reloads grades data instead of falling into the generic `else`. Replace its body with:

```javascript
    const selectCourse = (courseId) => {
      this._quizSeq++;
      this._chatSeq++;
      if (courseId === 'all') {
        const bounce = s.tab === 'quiz' || s.tab === 'progress' || s.tab === 'chat';
        this.setState(bounce ? { course: 'all', tab: 'dashboard' } : { course: 'all' });
        if (bounce) this.loadDashboard();
        this.loadDashboardRecent('all');
        if (s.tab === 'grades') { this.setState({ course: 'all' }); this.loadGradesSummary(); }
        return;
      }
      if (s.tab === 'quiz') {
        goToQuiz(courseId);
      } else if (s.tab === 'dashboard') {
        this.setState({ course: courseId });
        this.loadDashboardRecent(courseId);
      } else if (s.tab === 'chat') {
        if (courseId !== s.course) {
          this.setState({ course: courseId, chatMessages: [], chatInput: '', chatError: null, chatSessionId: null });
          this.loadChatSessions(courseId);
        }
      } else if (s.tab === 'progress') {
        this.setState({ course: courseId });
        this.loadDashboardRecent(courseId);
      } else if (s.tab === 'grades') {
        this.setState({ course: courseId, gradesWhatIfTarget: '' });
        this.loadGrades(courseId);
      } else {
        this.setState({ course: courseId });
      }
    };
```

`courseId === 'all'` branch note: the `bounce` variable already excludes `'grades'` (it only bounces `quiz`/`progress`/`chat`), so selecting "All Courses" while on the Grades tab keeps `tab: 'grades'` and just needs its own summary reload — the extra `if (s.tab === 'grades')` block above handles that explicitly since it isn't part of the `bounce` set.

Similarly, in `confirmDeleteCourse()` (around line 1195-1226) and anywhere else `bounce = s.tab === 'quiz' || s.tab === 'progress' || s.tab === 'chat'` appears (there is one more, inside `confirmDeleteCourse` itself, already shown at lines 1210 and one more at the earlier-read `1210`/`1345` — both already excluded 'grades' by construction since the list is explicit and doesn't need editing; no change required there since deleting the currently-selected course while on Grades should still bounce you to Dashboard the same as it would from any per-course tab with nothing left to show). Leave `confirmDeleteCourse` as-is — it's out of scope for this task.

- [ ] **Step 4: Add the nav button and render flags**

In the sidebar nav buttons block (around line 60-63, right after the Quiz button's closing `</button>`), add:

```html
      <button type="button" onClick="{{ goGrades }}" style="{{ navBtnStyleGrades }}">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        Grade Calculator
      </button>
```

In `renderVals()`'s big return object (around lines 1568-1575, alongside `isQuiz`/`navBtnStyleQuiz`), add:

```javascript
      isGrades: s.tab === 'grades',
      navBtnStyleGrades: this.navBtn(s.tab === 'grades'),
```

And alongside `goQuiz: () => setTab('quiz'),` (around line 1607):

```javascript
      goGrades: () => setTab('grades'),
```

- [ ] **Step 5: Manually verify**

Run the dev server (`.\run_server.bat`), open `/`, click "Grade Calculator" in the sidebar. Confirm: the nav button highlights, no JS console errors appear, and a network request fires to either `/api/courses/<id>/grades/` (a course was selected) or `/api/grades/summary/` (All Courses was selected). Nothing visible renders in the main pane yet — that's expected, Task 13 adds it.

- [ ] **Step 6: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: wire Grade Calculator tab navigation and data loading"
```

---

## Task 13: Frontend — per-course stat cards and grading breakdown

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `isGrades`, `s.gradesBreakdown`, `s.gradesLoading`, `s.gradesError` (Task 12)

- [ ] **Step 1: Add computed template vars in `renderVals()`**

After the `progressTopicsRaw`/`courseHasNotes` block (around line 1242-1246), add:

```javascript
    const gradesOverallPct = s.gradesBreakdown && s.gradesBreakdown.overall_pct !== null
      ? Math.round(s.gradesBreakdown.overall_pct) + '%' : '—';
    const gradesOverallLetter = s.gradesBreakdown ? (s.gradesBreakdown.letter || 'No grade yet') : '';
    const gradesCategoriesGraded = s.gradesBreakdown
      ? s.gradesBreakdown.categories.filter(c => c.entered_count > 0).length : 0;
    const gradesCategoriesTotal = s.gradesBreakdown ? s.gradesBreakdown.categories.length : 0;
    const gradesCategoriesLabel = gradesCategoriesTotal > 0
      ? `${gradesCategoriesGraded} of ${gradesCategoriesTotal} categories graded` : 'No grading categories set up';
    const gradesItemsCount = s.gradesItems.length;
    const gradesBreakdownRows = (s.gradesBreakdown ? s.gradesBreakdown.categories : []).map(c => ({
      component: c.component,
      weightLabel: c.weight_pct + '%',
      avgLabel: c.avg_pct !== null ? Math.round(c.avg_pct) + '%' : 'No grades yet',
      countLabel: c.total_items ? `${c.entered_count} of ${c.total_items} entered` : `${c.entered_count} entered`,
      dropLabel: c.drop_lowest > 0 ? `Lowest ${c.drop_lowest} dropped` : null,
    }));
    const gradesHasGradingSetup = gradesCategoriesTotal > 0;
```

- [ ] **Step 2: Add the fields to the returned template-vars object**

In the big object returned by `renderVals()` (near the other `isGrades`/`navBtnStyleGrades` lines added in Task 12), add:

```javascript
      gradesLoading: s.gradesLoading, gradesError: s.gradesError,
      gradesOverallPct: gradesOverallPct, gradesOverallLetter: gradesOverallLetter,
      gradesCategoriesLabel: gradesCategoriesLabel, gradesItemsCount: gradesItemsCount,
      gradesBreakdownRows: gradesBreakdownRows, gradesHasGradingSetup: gradesHasGradingSetup,
      retryGrades: () => this.loadGrades(s.course),
```

- [ ] **Step 3: Add the template markup**

After the Progress tab's closing `</sc-if>` (the one matching `<sc-if value="{{ isProgress }}" ...>` — find it by locating where the Quiz tab's `<sc-if value="{{ isQuiz }}" ...>` begins, at line 379, and insert immediately before that line), add:

```html
    <sc-if value="{{ isGrades }}" hint-placeholder-val="{{ false }}">
      <div style="padding:var(--space-8) var(--space-8);max-width:1100px">
        <h1 style="font-family:var(--font-heading);font-size:28px;margin:0 0 4px">Grade Calculator</h1>
        <p style="margin:0 0 var(--space-6);opacity:.65;font-size:14.5px">{{ courseName }}</p>

        <sc-if value="{{ gradesLoading }}" hint-placeholder-val="{{ false }}">
          <div style="font-size:13px;opacity:.6;padding:12px 0">Loading…</div>
        </sc-if>

        <sc-if value="{{ gradesError }}" hint-placeholder-val="{{ false }}">
          <div style="font-size:13px;padding:12px 0;display:flex;align-items:center;gap:10px">
            <span style="opacity:.7">{{ gradesError }}</span>
            <button type="button" class="btn btn-secondary" onClick="{{ retryGrades }}">Try again</button>
          </div>
        </sc-if>

        <sc-if value="{{ !gradesLoading }}" hint-placeholder-val="{{ true }}">
          <sc-if value="{{ !gradesHasGradingSetup }}" hint-placeholder-val="{{ false }}">
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div class="card-title" style="margin-bottom:8px">No grading categories set up yet</div>
              <p class="card-body" style="margin:0">This course's syllabus doesn't have any grading categories (Homework, Exams, etc.) defined yet. Add them from the syllabus before entering grades.</p>
            </div>
          </sc-if>

          <sc-if value="{{ gradesHasGradingSetup }}" hint-placeholder-val="{{ true }}">
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--space-4);margin-bottom:var(--space-6)">
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div style="font-size:12.5px;opacity:.65;margin-bottom:var(--space-2)">Current grade</div>
                <div style="font-family:var(--font-heading);font-size:32px">{{ gradesOverallPct }}</div>
                <div style="font-size:12px;opacity:.55">{{ gradesOverallLetter }}</div>
              </div>
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div style="font-size:12.5px;opacity:.65;margin-bottom:var(--space-2)">Categories</div>
                <div style="font-family:var(--font-heading);font-size:20px;line-height:1.6">{{ gradesCategoriesLabel }}</div>
              </div>
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div style="font-size:12.5px;opacity:.65;margin-bottom:var(--space-2)">Items entered</div>
                <div style="font-family:var(--font-heading);font-size:32px">{{ gradesItemsCount }}</div>
              </div>
            </div>

            <div class="card elev-sm" style="padding:var(--space-6);margin-bottom:var(--space-6)">
              <div class="card-title" style="margin-bottom:var(--space-4)">Grading breakdown</div>
              <div style="display:flex;flex-direction:column;gap:10px">
                <sc-for list="{{ gradesBreakdownRows }}" as="row" hint-placeholder-count="3">
                  <div style="display:flex;align-items:center;gap:var(--space-4);padding:10px 0;border-bottom:1px solid var(--color-neutral-200)">
                    <div style="flex:1;min-width:0;font-size:13.5px;font-weight:600">{{ row.component }}</div>
                    <span class="tag tag-neutral">{{ row.weightLabel }}</span>
                    <div style="font-size:13px;opacity:.75;width:130px">{{ row.countLabel }}</div>
                    <sc-if value="{{ row.dropLabel }}" hint-placeholder-val="{{ false }}">
                      <span class="tag tag-accent">{{ row.dropLabel }}</span>
                    </sc-if>
                    <div style="font-size:14px;font-weight:600;width:90px;text-align:right">{{ row.avgLabel }}</div>
                  </div>
                </sc-for>
              </div>
            </div>
          </sc-if>
        </sc-if>
      </div>
    </sc-if>
```

- [ ] **Step 4: Manually verify**

Run the dev server, select a course with a syllabus that has a `grading` array (e.g. seed one via `manage.py extract_syllabus` or `manage.py grades <id> --add ...` from Task 11), open Grade Calculator. Confirm: the three stat cards render with real numbers (or `—`/"No grade yet" if nothing's entered), and the "Grading breakdown" card lists every category with its weight, entered count, and average. Then check a course with an empty `grading` array — confirm the "No grading categories set up yet" empty state shows instead of a broken 0%.

- [ ] **Step 5: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: render Grade Calculator stat cards and grading breakdown"
```

---

## Task 14: Frontend — grades list card and Add/Edit/Delete modal

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `POST /api/courses/<id>/grades/items/`, `PATCH/DELETE /api/courses/<id>/grades/items/<item_id>/` (Task 9), `s.gradesItems`, `s.gradesBreakdown.categories` (Task 12/13)
- Produces: `openAddGrade()`, `openEditGrade(item)`, `closeAddGrade()`, `submitAddGrade()`, `deleteGradeItem(itemId)`

There is no precedent anywhere in this file for a `<select>`/`<option>` element — every choice picker (e.g. the quiz's multiple-choice answers, `mcOptions` at line ~1484) is built as a row of clickable styled buttons via `sc-for` instead. This task follows that same button-chip pattern for picking a grading category, rather than introducing an unverified new input type into the DSL.

- [ ] **Step 1: Add the CRUD methods**

Add these methods to the `Component` class, right after `submitUpload`'s closing `}` (from the existing code around line 1052):

```javascript
  openAddGrade() {
    const s = this.state;
    const firstComponent = s.gradesBreakdown && s.gradesBreakdown.categories[0] ? s.gradesBreakdown.categories[0].component : '';
    this.setState({
      addGradeOpen: true, addGradeEditingId: null, addGradeComponent: firstComponent,
      addGradeTitle: '', addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '',
      addGradeLoading: false, addGradeError: null,
    });
  }

  openEditGrade(item) {
    this.setState({
      addGradeOpen: true, addGradeEditingId: item.id, addGradeComponent: item.component,
      addGradeTitle: item.title, addGradeScore: String(item.score), addGradeMaxPoints: String(item.max_points),
      addGradeDate: item.date || '', addGradeLoading: false, addGradeError: null,
    });
  }

  closeAddGrade() {
    this._addGradeSeq = (this._addGradeSeq || 0) + 1;
    this.setState({
      addGradeOpen: false, addGradeEditingId: null, addGradeComponent: '', addGradeTitle: '',
      addGradeScore: '', addGradeMaxPoints: '', addGradeDate: '', addGradeLoading: false, addGradeError: null,
    });
  }

  submitAddGrade() {
    const s = this.state;
    if (!s.addGradeComponent) { this.setState({ addGradeError: 'Choose a category.' }); return; }
    if (!s.addGradeTitle) { this.setState({ addGradeError: 'Enter a title.' }); return; }
    const score = parseFloat(s.addGradeScore);
    const maxPoints = parseFloat(s.addGradeMaxPoints);
    if (isNaN(score) || isNaN(maxPoints) || maxPoints <= 0) {
      this.setState({ addGradeError: 'Enter a valid score and max points.' });
      return;
    }

    const seq = ++this._addGradeSeq;
    const courseId = s.course;
    const body = { component: s.addGradeComponent, title: s.addGradeTitle, score: score, max_points: maxPoints, date: s.addGradeDate || null };
    this.setState({ addGradeLoading: true, addGradeError: null });

    const url = s.addGradeEditingId
      ? `/api/courses/${courseId}/grades/items/${s.addGradeEditingId}/`
      : `/api/courses/${courseId}/grades/items/`;
    const method = s.addGradeEditingId ? 'PATCH' : 'POST';

    fetch(url, {
      method: method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify(body)
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._addGradeSeq) return;
        if (!ok) { this.setState({ addGradeLoading: false, addGradeError: data.detail || 'Could not save that grade.' }); return; }
        this.closeAddGrade();
        this.loadGrades(courseId);
      })
      .catch(e => {
        if (seq !== this._addGradeSeq) return;
        this.setState({ addGradeLoading: false, addGradeError: 'Network error: ' + e.message });
      });
  }

  deleteGradeItem(itemId) {
    const courseId = this.state.course;
    fetch(`/api/courses/${courseId}/grades/items/${itemId}/`, {
      method: 'DELETE', headers: { 'X-CSRFToken': getCookie('csrftoken') }
    }).then(() => this.loadGrades(courseId));
  }
```

- [ ] **Step 2: Run tests to verify nothing broke**

This task has no new backend surface, so there's no new automated test — run the existing suite to confirm the template still loads without a Python-side regression:

Run: `pytest agent/tests/ -v`
Expected: all tests PASS (unchanged from Task 10)

- [ ] **Step 3: Add template vars in `renderVals()`**

Add these alongside the `gradesBreakdownRows` block from Task 13:

```javascript
    const chipStyle = (selected) => 'padding:6px 12px;border-radius:99px;cursor:pointer;font-size:12.5px;font-family:var(--font-body);' +
      (selected ? 'border:1px solid var(--color-accent-700);background:var(--color-accent-100);font-weight:600' : 'border:1px solid var(--color-neutral-200);background:#fff');
    const addGradeComponentChips = (s.gradesBreakdown ? s.gradesBreakdown.categories : []).map(c => ({
      label: c.component,
      style: chipStyle(s.addGradeComponent === c.component),
      onClick: () => this.setState({ addGradeComponent: c.component }),
    }));
    const gradesItemRows = s.gradesItems.map(item => ({
      id: item.id, component: item.component, title: item.title,
      scoreLabel: item.score + '/' + item.max_points,
      dateLabel: item.date || '',
      onEdit: () => this.openEditGrade(item),
      onDelete: () => this.deleteGradeItem(item.id),
    }));
    const onAddGradeTitleChange = (e) => this.setState({ addGradeTitle: e.target.value });
    const onAddGradeScoreChange = (e) => this.setState({ addGradeScore: e.target.value });
    const onAddGradeMaxPointsChange = (e) => this.setState({ addGradeMaxPoints: e.target.value });
    const onAddGradeDateChange = (e) => this.setState({ addGradeDate: e.target.value });
    const addGradeModalTitle = s.addGradeEditingId ? 'Edit grade' : 'Add grade';
    const addGradeSubmitLabel = s.addGradeEditingId ? 'Save' : 'Add';
```

Then add these to the object `renderVals()` returns (alongside `gradesBreakdownRows` from Task 13):

```javascript
      gradesItemRows: gradesItemRows, addGradeOpen: s.addGradeOpen, addGradeModalTitle: addGradeModalTitle,
      addGradeSubmitLabel: addGradeSubmitLabel, addGradeComponentChips: addGradeComponentChips,
      addGradeTitle: s.addGradeTitle, addGradeScore: s.addGradeScore, addGradeMaxPoints: s.addGradeMaxPoints,
      addGradeDate: s.addGradeDate, addGradeLoading: s.addGradeLoading, addGradeError: s.addGradeError,
      onAddGradeTitleChange: onAddGradeTitleChange, onAddGradeScoreChange: onAddGradeScoreChange,
      onAddGradeMaxPointsChange: onAddGradeMaxPointsChange, onAddGradeDateChange: onAddGradeDateChange,
      openAddGrade: () => this.openAddGrade(),
      closeAddGrade: () => this.closeAddGrade(),
      submitAddGrade: () => this.submitAddGrade(),
```

- [ ] **Step 4: Add the "Grades" list card and modal markup**

Inside the Grade Calculator `<sc-if value="{{ isGrades }}" ...>` block from Task 13, right after the "Grading breakdown" card's closing `</div>` (before the outer `</sc-if>` for `gradesHasGradingSetup`), add:

```html
            <div class="card elev-sm" style="padding:0;overflow:hidden;margin-bottom:var(--space-6)">
              <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-4) var(--space-6);border-bottom:1px solid var(--color-neutral-200)">
                <div class="card-title" style="margin:0">Grades</div>
                <button type="button" class="btn btn-primary" onClick="{{ openAddGrade }}">Add grade</button>
              </div>
              <sc-if value="{{ !gradesItemRows.length }}" hint-placeholder-val="{{ false }}">
                <div style="padding:var(--space-6);font-size:13px;opacity:.6">No grades entered yet.</div>
              </sc-if>
              <sc-for list="{{ gradesItemRows }}" as="row" hint-placeholder-count="3">
                <div style="display:flex;align-items:center;gap:var(--space-3);padding:12px var(--space-6);border-bottom:1px solid var(--color-neutral-200)">
                  <span class="tag tag-neutral">{{ row.component }}</span>
                  <div style="flex:1;min-width:0;font-size:13.5px">{{ row.title }}</div>
                  <div style="font-size:12.5px;opacity:.65;width:80px">{{ row.dateLabel }}</div>
                  <div style="font-size:14px;font-weight:600;width:80px;text-align:right">{{ row.scoreLabel }}</div>
                  <button type="button" class="btn btn-ghost" onClick="{{ row.onEdit }}">Edit</button>
                  <button type="button" class="btn btn-ghost" onClick="{{ row.onDelete }}">Delete</button>
                </div>
              </sc-for>
            </div>
```

Then, near the other modals, add the "Add grade" modal as a top-level sibling `<sc-if>` immediately after the Grade Calculator tab's closing `</sc-if>` — a modal reachable from the Grades tab belongs at the top level rather than nested inside the Dashboard-only "Upload notes" modal block at line 247-299, since it must render regardless of which tab is active while it's open:

```html
    <sc-if value="{{ addGradeOpen }}" hint-placeholder-val="{{ false }}">
      <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
        <div class="card elev-md" style="padding:var(--space-6);width:420px;max-width:90vw">
          <div class="card-title" style="margin:0 0 var(--space-4)">{{ addGradeModalTitle }}</div>

          <div style="display:flex;flex-direction:column;gap:12px;margin-bottom:var(--space-4)">
            <div>
              <div style="font-size:13px;margin-bottom:6px">Category</div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <sc-for list="{{ addGradeComponentChips }}" as="chip" hint-placeholder-count="3">
                  <button type="button" onClick="{{ chip.onClick }}" style="{{ chip.style }}">{{ chip.label }}</button>
                </sc-for>
              </div>
            </div>
            <div>
              <div style="font-size:13px;margin-bottom:4px">Title</div>
              <input class="input" placeholder="e.g. HW 3" value="{{ addGradeTitle }}" onChange="{{ onAddGradeTitleChange }}" style="width:100%"/>
            </div>
            <div style="display:flex;gap:12px">
              <div style="flex:1">
                <div style="font-size:13px;margin-bottom:4px">Score</div>
                <input class="input" placeholder="92" value="{{ addGradeScore }}" onChange="{{ onAddGradeScoreChange }}" style="width:100%"/>
              </div>
              <div style="flex:1">
                <div style="font-size:13px;margin-bottom:4px">Out of</div>
                <input class="input" placeholder="100" value="{{ addGradeMaxPoints }}" onChange="{{ onAddGradeMaxPointsChange }}" style="width:100%"/>
              </div>
            </div>
            <div>
              <div style="font-size:13px;margin-bottom:4px">Date (optional)</div>
              <input class="input" placeholder="YYYY-MM-DD" value="{{ addGradeDate }}" onChange="{{ onAddGradeDateChange }}" style="width:100%"/>
            </div>
          </div>

          <sc-if value="{{ addGradeError }}" hint-placeholder-val="{{ false }}">
            <p style="font-size:13px;color:var(--color-accent-700);margin:0 0 var(--space-4)">{{ addGradeError }}</p>
          </sc-if>

          <sc-if value="{{ addGradeLoading }}" hint-placeholder-val="{{ false }}">
            <div style="font-size:13px;opacity:.7;padding:8px 0">Saving…</div>
          </sc-if>

          <sc-if value="{{ !addGradeLoading }}" hint-placeholder-val="{{ true }}">
            <div style="display:flex;gap:8px">
              <button type="button" class="btn btn-secondary" onClick="{{ closeAddGrade }}">Cancel</button>
              <button type="button" class="btn btn-primary" onClick="{{ submitAddGrade }}">{{ addGradeSubmitLabel }}</button>
            </div>
          </sc-if>
        </div>
      </div>
    </sc-if>
```

- [ ] **Step 5: Manually verify**

Run the dev server, open Grade Calculator for a course with at least one grading category. Click "Add grade": confirm the modal opens with the first category pre-selected as a chip, fill in a title/score/max points, submit, and confirm the new row appears in the "Grades" list and the stat cards update. Click "Edit" on that row, change the score, save, and confirm the update reflects everywhere. Click "Delete" and confirm the row disappears and the stat cards recompute.

- [ ] **Step 6: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: add grades list and add/edit/delete grade modal"
```

---

## Task 15: Frontend — what-if card

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET /api/courses/<id>/grades/whatif/?target=<pct>` (Task 10), `s.gradesWhatIf`, `s.gradesWhatIfTarget` (Task 12)

- [ ] **Step 1: Add template vars in `renderVals()`**

Add alongside the other `grades*` computed vars from Task 13/14:

```javascript
    const onGradesWhatIfTargetChange = (e) => {
      this.setState({ gradesWhatIfTarget: e.target.value });
    };
    const setGradesWhatIfToPassing = () => {
      const passing = (s.gradesBreakdown && s.gradesBreakdown.grade_scale && s.gradesBreakdown.grade_scale.passing_pct) || 60;
      this.setState({ gradesWhatIfTarget: String(passing) });
      this.loadGradesWhatIf(s.course);
    };
    const runGradesWhatIf = () => this.loadGradesWhatIf(s.course);

    const whatIf = s.gradesWhatIf;
    const gradesWhatIfSummary = (() => {
      if (!whatIf) return '';
      const n = whatIf.grade_needed;
      if (n.locked) {
        return n.achievable
          ? `Your grade is locked at ${n.ceiling_pct}% — you've already hit this target.`
          : `Your grade is locked at ${n.ceiling_pct}% — this target is no longer reachable.`;
      }
      if (!n.achievable) {
        return `Not achievable: you'd need to average ${n.p_needed}% on everything remaining (max possible is ${n.ceiling_pct}%).`;
      }
      if (n.p_needed <= 0) {
        return `Already guaranteed — you'd hit this target even scoring 0 on everything remaining.`;
      }
      return `You need to average ${n.p_needed}% on everything remaining to hit this target.`;
    })();
    const gradesWhatIfNotes = whatIf ? whatIf.grade_needed.notes : [];
    const gradesMissableRows = (whatIf ? whatIf.missable_by_category : [])
      .filter(m => !m.omitted_reason)
      .map(m => ({ label: `${m.component}: can miss ${m.missable} of ${m.remaining} remaining` }));
    const gradesMissableOmitted = (whatIf ? whatIf.missable_by_category : [])
      .filter(m => m.omitted_reason)
      .map(m => ({ label: `${m.component}: ${m.omitted_reason}` }));
```

Add these to the object `renderVals()` returns:

```javascript
      gradesWhatIfTarget: s.gradesWhatIfTarget, onGradesWhatIfTargetChange: onGradesWhatIfTargetChange,
      setGradesWhatIfToPassing: setGradesWhatIfToPassing, runGradesWhatIf: runGradesWhatIf,
      gradesWhatIfLoading: s.gradesWhatIfLoading, gradesWhatIfError: s.gradesWhatIfError,
      gradesWhatIfSummary: gradesWhatIfSummary, gradesWhatIfNotes: gradesWhatIfNotes,
      gradesMissableRows: gradesMissableRows, gradesMissableOmitted: gradesMissableOmitted,
      hasGradesWhatIf: !!whatIf,
```

- [ ] **Step 2: Add the markup**

Inside the Grade Calculator `<sc-if value="{{ isGrades }}" ...>` block, right after the "Grades" list card added in Task 14 (still inside the `gradesHasGradingSetup` branch), add:

```html
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div class="card-title" style="margin-bottom:var(--space-4)">What-if</div>
              <div style="display:flex;align-items:flex-end;gap:8px;margin-bottom:var(--space-4)">
                <div>
                  <div style="font-size:13px;margin-bottom:4px">Target grade (%)</div>
                  <input class="input" value="{{ gradesWhatIfTarget }}" onChange="{{ onGradesWhatIfTargetChange }}" style="width:100px"/>
                </div>
                <button type="button" class="btn btn-secondary" onClick="{{ runGradesWhatIf }}">Calculate</button>
                <button type="button" class="btn btn-ghost" onClick="{{ setGradesWhatIfToPassing }}">Set to passing</button>
              </div>

              <sc-if value="{{ gradesWhatIfLoading }}" hint-placeholder-val="{{ false }}">
                <div style="font-size:13px;opacity:.6;padding:8px 0">Calculating…</div>
              </sc-if>

              <sc-if value="{{ gradesWhatIfError }}" hint-placeholder-val="{{ false }}">
                <p style="font-size:13px;opacity:.7;margin:0">{{ gradesWhatIfError }}</p>
              </sc-if>

              <sc-if value="{{ hasGradesWhatIf }}" hint-placeholder-val="{{ false }}">
                <p style="font-size:14.5px;margin:0 0 var(--space-4)">{{ gradesWhatIfSummary }}</p>

                <sc-for list="{{ gradesWhatIfNotes }}" as="note" hint-placeholder-count="1">
                  <p style="font-size:12.5px;opacity:.7;margin:0 0 8px">{{ note }}</p>
                </sc-for>

                <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.55;margin:var(--space-4) 0 var(--space-2)">How many can you miss?</div>
                <div style="display:flex;flex-direction:column;gap:6px">
                  <sc-for list="{{ gradesMissableRows }}" as="row" hint-placeholder-count="2">
                    <div style="font-size:13.5px">{{ row.label }}</div>
                  </sc-for>
                  <sc-for list="{{ gradesMissableOmitted }}" as="row" hint-placeholder-count="0">
                    <div style="font-size:12.5px;opacity:.55">{{ row.label }}</div>
                  </sc-for>
                </div>
              </sc-if>
            </div>
```

- [ ] **Step 3: Manually verify**

Open Grade Calculator for a course with `total_items` set on at least one category. Confirm the target field defaults to the course's passing percentage, "Calculate" refreshes the summary line and per-category missable list, "Set to passing" resets the target and recalculates, and a category without `total_items` shows up in the grayed-out "omitted" list with its reason instead of silently vanishing.

- [ ] **Step 4: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: add Grade Calculator what-if card"
```

---

## Task 16: Frontend — all-courses view

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET /api/grades/summary/` (Task 10), `s.gradesSummary`, `s.gradesSummaryLoading`, `s.gradesSummaryError` (Task 12)

- [ ] **Step 1: Add template vars in `renderVals()`**

```javascript
    const gradesSummaryAveragePct = s.gradesSummary && s.gradesSummary.average_pct !== null
      ? Math.round(s.gradesSummary.average_pct) + '%' : 'No grades entered yet';
    const gradesSummaryExcludedLabel = (s.gradesSummary && s.gradesSummary.excluded_count > 0)
      ? `${s.gradesSummary.excluded_count} course(s) excluded — no grades entered yet` : '';
    const gradesSummaryRows = (s.gradesSummary ? s.gradesSummary.courses : []).map(c => ({
      courseId: c.course_id,
      name: c.course_name || (c.course_id || '').toUpperCase(),
      pctLabel: c.error ? 'Error' : (c.current_pct !== null && c.current_pct !== undefined ? Math.round(c.current_pct) + '%' : '—'),
      letterLabel: c.error ? c.error : (c.letter || 'No grade yet'),
      onClick: () => selectCourse(c.course_id),
    }));
```

Add these to the object `renderVals()` returns:

```javascript
      gradesSummaryLoading: s.gradesSummaryLoading, gradesSummaryError: s.gradesSummaryError,
      gradesSummaryAveragePct: gradesSummaryAveragePct, gradesSummaryExcludedLabel: gradesSummaryExcludedLabel,
      gradesSummaryRows: gradesSummaryRows,
      retryGradesSummary: () => this.loadGradesSummary(),
```

Note: `gradesSummaryRows` references `selectCourse`, which is defined earlier in the same `renderVals()` function body (Task 12, Step 3) — since both are `const` declarations in the same function scope with `selectCourse` declared first, this is a valid forward-reference-free use, not a hoisting issue.

- [ ] **Step 2: Add the markup**

The all-courses view needs its own top-level branch, separate from the per-course markup added in Tasks 13-15 (which all assume `s.course !== 'all'`). Wrap the per-course content added in Task 13 with a course-scoped condition, and add a sibling branch for `s.course === 'all'`. Change the Grade Calculator `<sc-if value="{{ isGrades }}" ...>` block's opening (from Task 13) so its first line of content becomes:

```html
    <sc-if value="{{ isGrades }}" hint-placeholder-val="{{ false }}">
      <div style="padding:var(--space-8) var(--space-8);max-width:1100px">
        <h1 style="font-family:var(--font-heading);font-size:28px;margin:0 0 4px">Grade Calculator</h1>
        <p style="margin:0 0 var(--space-6);opacity:.65;font-size:14.5px">{{ courseName }}</p>

        <sc-if value="{{ isGradesAllCourses }}" hint-placeholder-val="{{ false }}">
          <sc-if value="{{ gradesSummaryLoading }}" hint-placeholder-val="{{ false }}">
            <div style="font-size:13px;opacity:.6;padding:12px 0">Loading…</div>
          </sc-if>
          <sc-if value="{{ gradesSummaryError }}" hint-placeholder-val="{{ false }}">
            <div style="font-size:13px;padding:12px 0;display:flex;align-items:center;gap:10px">
              <span style="opacity:.7">{{ gradesSummaryError }}</span>
              <button type="button" class="btn btn-secondary" onClick="{{ retryGradesSummary }}">Try again</button>
            </div>
          </sc-if>
          <sc-if value="{{ !gradesSummaryLoading }}" hint-placeholder-val="{{ true }}">
            <div class="card elev-sm" style="padding:var(--space-6);margin-bottom:var(--space-6)">
              <div style="font-size:12.5px;opacity:.65;margin-bottom:var(--space-2)">Semester average</div>
              <div style="font-family:var(--font-heading);font-size:32px">{{ gradesSummaryAveragePct }}</div>
              <sc-if value="{{ gradesSummaryExcludedLabel }}" hint-placeholder-val="{{ false }}">
                <div style="font-size:12px;opacity:.55;margin-top:4px">{{ gradesSummaryExcludedLabel }}</div>
              </sc-if>
            </div>

            <div class="card elev-sm" style="padding:0;overflow:hidden">
              <sc-for list="{{ gradesSummaryRows }}" as="row" hint-placeholder-count="2">
                <div style="display:flex;align-items:center;gap:var(--space-3);padding:14px var(--space-6);border-bottom:1px solid var(--color-neutral-200);cursor:pointer" onClick="{{ row.onClick }}">
                  <div style="flex:1;min-width:0;font-size:14px;font-weight:600">{{ row.name }}</div>
                  <div style="font-size:12.5px;opacity:.65;width:140px">{{ row.letterLabel }}</div>
                  <div style="font-size:16px;font-weight:700;width:70px;text-align:right">{{ row.pctLabel }}</div>
                </div>
              </sc-for>
            </div>
          </sc-if>
        </sc-if>

        <sc-if value="{{ !isGradesAllCourses }}" hint-placeholder-val="{{ true }}">
```

And at the very end of the per-course content block from Tasks 13-15 (right before that block's closing `</div></sc-if>` that closes the outermost `isGrades` wrapper), close the new wrapper `sc-if` by adding one more `</sc-if>` immediately before the existing closing `</div>\n    </sc-if>` pair, so the final structure reads:

```html
        </sc-if>
      </div>
    </sc-if>
```

(one `</sc-if>` closes the `!isGradesAllCourses` branch just opened in this task, the existing `</div>` closes the outer padding wrapper, and the existing `</sc-if>` closes the top-level `isGrades` block — unchanged from Task 13).

- [ ] **Step 3: Add the `isGradesAllCourses` flag**

Add alongside `isGrades` in the returned object (from Task 12):

```javascript
      isGradesAllCourses: s.tab === 'grades' && s.course === 'all',
```

- [ ] **Step 4: Manually verify**

Open Grade Calculator, select "All Courses" — confirm the semester-average card and the per-course list render (not a bounce to Dashboard, per the design's deliberate deviation from Quiz/Progress/Chat). Click a course row and confirm it switches to that course's per-course Grade Calculator view. Then re-select "All Courses" from the sidebar chip while already on the Grades tab and confirm the summary reloads correctly.

- [ ] **Step 5: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: add Grade Calculator all-courses view"
```

---

## Task 17: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest agent/tests/ -v`
Expected: all tests PASS

- [ ] **Step 2: Seed a realistic scenario**

Use the API directly against the running dev server (`.\run_server.bat`) to set up `cs101`'s grading config with `total_items` on at least one category — there is no management command for editing grading config, only for adding grade items, so this step uses `curl` against `GradingConfigView` (Task 8) instead:

```bash
curl -X PUT http://127.0.0.1:8000/api/courses/cs101/grading/ \
  -H "Content-Type: application/json" \
  -d '{"grading": [{"component": "Homework", "weight_pct": 40, "total_items": 5, "drop_lowest": 1}, {"component": "Exams", "weight_pct": 60, "total_items": 2}]}'
```

Then add a few items via `manage.py grades cs101 --add Homework "HW 1" 90 100`, `--add Homework "HW 2" 70 100`, `--add Exams "Midterm" 85 100`.

- [ ] **Step 3: Walk the full UI flow**

Open `/`, select `cs101`, click "Grade Calculator." Confirm:
- Stat cards show a real overall percentage and letter matching a hand calculation ((90+70)/2 = 80% Homework at 40% weight, 85% Exams at 60% weight = 0.4×80 + 0.6×85 = 83% since both categories have data).
- The "Grading breakdown" card shows both categories with correct entered counts (`2 of 5` for Homework, `1 of 2` for Exams) and the drop-lowest note on Homework.
- Add, edit, and delete a grade item from the "Grades" card; confirm every card updates immediately after each action.
- In the "What-if" card, enter a target above your current grade and confirm the needed-average message and per-category missable counts look sane by hand; enter an unreachable target (e.g. 99.9%) and confirm the "not achievable" message with a ceiling shows instead of a broken number.
- Switch to "All Courses" and confirm `cs101` appears in the list with the same percentage, and a course with no grades entered shows `—`/"No grade yet" rather than 0%.
- Confirm the browser's network tab shows no failed (4xx/5xx) requests during this whole flow, and the JS console has no errors.

- [ ] **Step 4: Confirm no regressions on other tabs**

Click through Dashboard, Ask Cora, Progress, and Quiz for `cs101` and for "All Courses" — confirm all four still behave exactly as before this feature (the Grades tab additions to `setTab`/`selectCourse` in Task 12 only added new branches, they didn't change the existing `dashboard`/`quiz`/`chat`/`progress` branches).

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-18-grade-calculator-design.md` maps to a task — data model (Tasks 1-2), `current_grade`/renormalization/drop-lowest (Task 3), CRUD (Task 4), `grade_needed` (Task 5), `missable_by_category` (Task 6), `all_courses_summary` (Task 7), all six API endpoints (Tasks 8-10), CLI (Task 11), nav/bounce behavior + stat cards + breakdown (Tasks 12-13), grades list + modal (Task 14), what-if card (Task 15), all-courses view (Task 16).
- **Placeholder scan:** no TBDs; every step has complete code. Task 17 Step 2 explicitly calls out that no management command covers grading-config edits (only item CRUD), rather than leaving that gap implicit.
- **Type consistency checked:** `current_grade()`'s return shape (`overall_pct`, `letter`, `grade_scale`, `categories[].{component,weight_pct,avg_pct,entered_count,total_items,drop_lowest}`) is defined once in Task 3 and consumed identically in Tasks 7, 9, 12, 13. `grade_needed()`'s shape (`target_pct`, `locked`, `p_needed`, `achievable`, `ceiling_pct`, `notes`) is defined in Task 5 and consumed identically in Tasks 10, 11, 15. `missable_by_category()`'s per-entry shape (`component`, `remaining`, `missable`, `omitted_reason`) is defined in Task 6 and consumed identically in Tasks 10, 11, 15. Item shape (`id`, `component`, `title`, `score`, `max_points`, `date`) is consistent from Task 1 through Task 14.

