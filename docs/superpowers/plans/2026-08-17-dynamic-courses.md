# Dynamic Courses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OnTrack's hardcoded two-course frontend (`cs101`/`psyc201`) with a dynamic course list, and add UI to create a new class (with or without a syllabus up front) and upload notes for any class.

**Architecture:** Backend gets one new lightweight concept — a "draft" course (`courses/<id>/course.json`, a name with no syllabus yet) — layered on top of the existing syllabus-based storage without touching any of it. The frontend (`agent/templates/agent/ontrack.html`, a single Django template + inline JS driving a `dc-runtime` component) swaps its hardcoded `COURSE_IDS` array and duplicated per-course markup for data-driven loops over whatever `/api/dashboard/` actually returns.

**Tech Stack:** Django/DRF (`adrf` async views), flat-file JSON storage, pytest, the project's `dc-runtime` template syntax (`sc-if`/`sc-for`/`{{ }}` bindings resolved by `renderVals()`).

## Global Constraints

- A draft course_id can't collide with an existing draft or an existing real (syllabus'd) course — `CourseAlreadyExistsError`, 409.
- No note uploads, quizzing, or chat for a draft — those already hard-require `syllabus.json` (`chunk_notes.py:191-193`, `sessions.py:105-111`) and are unmodified.
- New CSS/behavior follows the file's existing conventions exactly — `sc-if`/`sc-for` structure, `.btn`/`.card`/`.tag` classes from the design system, inline styles matching neighboring markup.
- No automated frontend test suite exists for `ontrack.html` (plain markup + inline JS, no JS test runner in this repo) — frontend task verification is manual: run the dev server, drive the page in a browser.
- Course-id slugs follow `storage.py`'s `COURSE_ID_RE`: `^[a-zA-Z0-9_-]{1,64}$`.

---

### Task 1: Draft course storage & listing

**Files:**
- Modify: `agent/services/storage.py:12` (import), end of file after line 489
- Modify: `agent/services/reminders.py:9` (import), after `list_courses()` (line 21)
- Test: `agent/tests/test_course_drafts.py` (new)

**Interfaces:**
- Produces: `storage.CourseAlreadyExistsError`, `storage.write_course_draft(course_id: str, course_name: str) -> Path`, `reminders.list_draft_courses() -> list[dict]` (each `{"course_id", "course_name", "created_at"}`, sorted by `course_id`).

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_course_drafts.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_course_drafts.py -v`
Expected: FAIL — `AttributeError: module 'agent.services.storage' has no attribute 'write_course_draft'` (and similar for `CourseAlreadyExistsError`, `reminders.list_draft_courses`).

- [ ] **Step 3: Implement `storage.py`**

Change the import line at `agent/services/storage.py:12`:

```python
from datetime import datetime
```

to:

```python
from datetime import datetime, timezone
```

Add at the end of the file (after `write_syllabus`, line 489):

```python


class CourseAlreadyExistsError(Exception):
    """Raised when a course_id already has either course.json or syllabus.json."""


def write_course_draft(course_id: str, course_name: str) -> Path:
    """Writes course.json — a class that has a name but no syllabus yet.
    Raises InvalidCourseIdError (via _course_dir) for a bad slug, and
    CourseAlreadyExistsError if course_id already has course.json or
    syllabus.json — a draft can't collide with itself or a real course."""
    out_dir = _course_dir(course_id)
    course_path = out_dir / "course.json"
    syllabus_path = out_dir / "syllabus.json"

    if course_path.exists():
        raise CourseAlreadyExistsError(f"'{course_id}' already exists as a draft class")
    if syllabus_path.exists():
        raise CourseAlreadyExistsError(f"'{course_id}' already exists as a class")

    out_dir.mkdir(parents=True, exist_ok=True)
    course_path.write_text(
        json.dumps({
            "course_id": course_id,
            "course_name": course_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2),
        encoding="utf-8",
    )
    return course_path
```

- [ ] **Step 4: Implement `reminders.py`**

Insert a new import line right after the existing one at `agent/services/reminders.py:9`, so lines 9-10 become:

```python
from datetime import date, datetime, timedelta
import json
```

Add a new function right after `list_courses()` (after line 21, before `upcoming_deadlines`):

```python


def list_draft_courses() -> list:
    """Returns every course as {"course_id", "course_name", "created_at"}
    that has course.json but not syllabus.json — a class with a name but no
    syllabus uploaded yet — sorted by course_id. A course.json that fails to
    parse is skipped rather than raising, matching list_courses()'s "never
    fail the whole scan over one bad entry" shape."""
    if not storage.COURSES_DIR.exists():
        return []
    drafts = []
    for p in sorted(storage.COURSES_DIR.iterdir(), key=lambda p: p.name):
        if not p.is_dir():
            continue
        if (p / "syllabus.json").exists():
            continue
        course_json = p / "course.json"
        if not course_json.exists():
            continue
        try:
            drafts.append(json.loads(course_json.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return drafts
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_course_drafts.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Run the full suite as a regression check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: same pass/skip counts as before this change, plus the 9 new tests, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add agent/services/storage.py agent/services/reminders.py agent/tests/test_course_drafts.py
git commit -m "$(cat <<'EOF'
Add draft-course storage (name without a syllabus yet)

course.json lets a class exist with just a name, isolated from every
syllabus-gated service (dashboard, quiz, chat, mastery, notes) — none
of them change, since they already require syllabus.json.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Draft creation endpoint

**Files:**
- Modify: `agent/serializers.py`
- Modify: `agent/views.py:7-18` (imports), after `ExtractSyllabusView` (after line 81)
- Modify: `agent/urls.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `storage.write_course_draft`, `storage.CourseAlreadyExistsError`, `storage.InvalidCourseIdError` (Task 1).
- Produces: `POST /api/courses/<course_id>/` — 201 `{"course_id", "course_name"}` on success, 400 for a bad slug or missing name, 409 on collision.

- [ ] **Step 1: Write the failing tests**

Add to `agent/tests/test_views.py` (after the existing `test_domain_suggestions_view_404s_without_syllabus`, before the `_NeverCalledMessages` class at line 112):

```python
def test_create_course_draft_returns_201(isolated_courses_dir, api_client):
    response = api_client.post(
        "/api/courses/newclass/", {"course_name": "New Class"}, format="json",
    )

    assert response.status_code == 201
    assert response.data == {"course_id": "newclass", "course_name": "New Class"}
    assert (isolated_courses_dir / "newclass" / "course.json").exists()


def test_create_course_draft_rejects_blank_name(isolated_courses_dir, api_client):
    response = api_client.post("/api/courses/newclass/", {"course_name": ""}, format="json")

    assert response.status_code == 400


def test_create_course_draft_conflicts_with_existing_draft(isolated_courses_dir, api_client):
    api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    response = api_client.post("/api/courses/newclass/", {"course_name": "New Class"}, format="json")

    assert response.status_code == 409


def test_create_course_draft_conflicts_with_existing_real_course(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.post("/api/courses/cs101/", {"course_name": "Intro to CS"}, format="json")

    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k create_course_draft -v`
Expected: FAIL — 404 (no matching URL yet).

- [ ] **Step 3: Add the serializer**

In `agent/serializers.py`, insert after `ChunkNotesRequestSerializer` (after line 19), before `IngestReferenceRequestSerializer`:

```python


class CreateCourseDraftRequestSerializer(serializers.Serializer):
    course_name = serializers.CharField(allow_blank=False)
```

- [ ] **Step 4: Add the view**

In `agent/views.py`, add `CreateCourseDraftRequestSerializer` to the import block at lines 7-15 (alphabetically, after `ChunkNotesRequestSerializer`):

```python
from .serializers import (
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    ChunkNotesRequestSerializer,
    CreateCourseDraftRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
)
```

Add a new view class after `ExtractSyllabusView` (after line 81, before `class ChunkNotesView`):

```python


class CourseDraftCreateView(APIView):
    """
    POST /api/courses/<course_id>/
    body: {"course_name": "..."}

    Creates a draft class — a name with no syllabus yet. 409 if course_id
    already exists as either a draft or a real (syllabus'd) course.
    """

    async def post(self, request, course_id):
        serializer = CreateCourseDraftRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        course_name = serializer.validated_data["course_name"]

        try:
            await sync_to_async(storage.write_course_draft)(course_id, course_name)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseAlreadyExistsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {"course_id": course_id, "course_name": course_name},
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 5: Wire the URL**

In `agent/urls.py`, add a new line right before `path("reminders/", ...)`:

```python
    path("courses/<slug:course_id>/", views.CourseDraftCreateView.as_view(), name="course-create-draft"),
    path("reminders/", views.RemindersView.as_view(), name="reminders"),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -k create_course_draft -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full suite as a regression check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: previous count + 4, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add agent/serializers.py agent/views.py agent/urls.py agent/tests/test_views.py
git commit -m "$(cat <<'EOF'
Add POST /api/courses/<id>/ to create a draft class

Wires storage.write_course_draft() up as an endpoint — a class can now
be created with just a name, syllabus added later.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Dashboard exposes drafts

**Files:**
- Modify: `agent/services/dashboard.py:78-86`
- Test: `agent/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `reminders.list_draft_courses()` (Task 1).
- Produces: `build_dashboard()` return value gains a `"drafts"` key (list, same shape as `list_draft_courses()`); `"courses"`/`"deadlines"`/`"streak"` unchanged.

- [ ] **Step 1: Write the failing test**

Add to `agent/tests/test_dashboard.py`, after `test_build_dashboard_notes_count_reflects_multiple_lectures` (end of file):

```python


def test_build_dashboard_includes_drafts(isolated_courses_dir):
    storage.write_course_draft("newclass", "New Class")
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["drafts"] == [{
        "course_id": "newclass", "course_name": "New Class",
        "created_at": data["drafts"][0]["created_at"],
    }]
    assert "newclass" not in data["courses"]
    assert "cs101" in data["courses"]


def test_build_dashboard_drafts_empty_when_none_exist(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["drafts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -k drafts -v`
Expected: FAIL — `KeyError: 'drafts'`.

- [ ] **Step 3: Implement**

In `agent/services/dashboard.py`, change the `return` statement at the end of `build_dashboard()` (lines 78-86):

```python
    return {
        # Restricted to the courses that read cleanly above — passing no
        # course_ids would make upcoming_deadlines() re-scan every course
        # (via its own list_courses() call) including any corrupt one,
        # raising past the per-course isolation this function promises.
        "deadlines": reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids),
        "streak": streak.current_streak(),
        "courses": courses,
    }
```

to:

```python
    return {
        # Restricted to the courses that read cleanly above — passing no
        # course_ids would make upcoming_deadlines() re-scan every course
        # (via its own list_courses() call) including any corrupt one,
        # raising past the per-course isolation this function promises.
        "deadlines": reminders.upcoming_deadlines(within_days=14, course_ids=good_course_ids),
        "streak": streak.current_streak(),
        "courses": courses,
        "drafts": reminders.list_draft_courses(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

- [ ] **Step 5: Run the full suite as a regression check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: previous count + 2, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add agent/services/dashboard.py agent/tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
Expose draft courses from the dashboard endpoint

Additive "drafts" field alongside the existing "courses" dict — real
courses are completely unaffected.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Frontend — dynamic course list core

**Files:**
- Modify: `agent/templates/agent/ontrack.html` (state, `loadDashboard`, `loadDashboardRecent`, module-level constants, sidebar chip markup, `renderVals()`)

**Interfaces:**
- Consumes: `/api/dashboard/`'s new `"drafts"` field (Task 3).
- Produces: `realCourseIds` and `fallbackCourse` (locals computed at the top of `renderVals()`, `fallbackCourse` is `null` when there are zero real courses); `courseChips` (array bound to the sidebar's `sc-for`); `s.courseDrafts` (state field, array of `{course_id, course_name, created_at}`). Later tasks (5-8) read `s.courseDrafts`, `realCourseIds`, and reuse the `courseMetaFor`/`selectCourse` helpers already in this function.

This task has no isolated unit test (it's markup + inline JS in a Django template, no JS test runner in this repo — see Global Constraints). Verification is manual, in Step 6.

- [ ] **Step 1: Add `courseDrafts` to state and `loadDashboard()`**

In `agent/templates/agent/ontrack.html`, change (lines 547-549):

```javascript
  state = {
    tab: 'dashboard', course: 'all',
    courseMeta: null, dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
```

to:

```javascript
  state = {
    tab: 'dashboard', course: 'all',
    courseMeta: null, courseDrafts: [], dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
```

Change (line 599):

```javascript
        this.setState({ dashboardLoading: false, courseMeta: data.courses, dashboardDeadlines: data.deadlines, dashboardStreak: data.streak });
```

to:

```javascript
        this.setState({ dashboardLoading: false, courseMeta: data.courses, courseDrafts: data.drafts, dashboardDeadlines: data.deadlines, dashboardStreak: data.streak });
```

- [ ] **Step 2: Remove the hardcoded course list, fix `loadDashboardRecent`**

Delete lines 543-544:

```javascript
const COURSE_IDS = ['cs101', 'psyc201'];
const FALLBACK_COURSE = 'cs101';
```

(leave the surrounding blank lines — `getCookie`'s closing `}` is directly above, `class Component extends DCLogic {` directly below).

Change `loadDashboardRecent` (line 610), which is a class method and doesn't have access to `renderVals()`'s locals:

```javascript
    const ids = courseId === 'all' ? COURSE_IDS : [courseId];
```

to:

```javascript
    const ids = courseId === 'all' ? Object.keys(this.state.courseMeta || {}) : [courseId];
```

- [ ] **Step 3: Compute `realCourseIds`/`fallbackCourse`, replace every other `COURSE_IDS`/`FALLBACK_COURSE` use**

Right after `const s = this.state;` (line 817), add:

```javascript
    const realCourseIds = Object.keys(s.courseMeta || {}).sort();
    const fallbackCourse = realCourseIds[0] || null;
```

Change line 829:

```javascript
    const anyCourseHasNotes = COURSE_IDS.some(id => courseMetaFor(id) && courseMetaFor(id).notes_count > 0);
```

to:

```javascript
    const anyCourseHasNotes = realCourseIds.some(id => courseMetaFor(id) && courseMetaFor(id).notes_count > 0);
```

Change `setTab` (lines 855-856) — add a null-guard, since `fallbackCourse` isn't guaranteed to exist the way the old hardcoded constant was:

```javascript
      const targetCourse = s.course === 'all' ? FALLBACK_COURSE : s.course;
      if (t === 'quiz') {
```

to:

```javascript
      const targetCourse = s.course === 'all' ? fallbackCourse : s.course;
      if (!targetCourse) return;
      if (t === 'quiz') {
```

Change line 918:

```javascript
      ? COURSE_IDS.map(weakTopicsForCourse).reduce((a, b) => a.concat(b), []).sort((a, b) => a.score - b.score)
```

to:

```javascript
      ? realCourseIds.map(weakTopicsForCourse).reduce((a, b) => a.concat(b), []).sort((a, b) => a.score - b.score)
```

Change `practiceWeak` (lines 928-935) — same null-guard reasoning:

```javascript
    const practiceWeak = () => {
      this._quizSeq++;
      this._chatSeq++;
      const targetCourse = s.course === 'all'
        ? ((rawWeakTopics[0] && rawWeakTopics[0].course_id) || FALLBACK_COURSE)
        : s.course;
      goToQuiz(targetCourse);
    };
```

to:

```javascript
    const practiceWeak = () => {
      this._quizSeq++;
      this._chatSeq++;
      const targetCourse = s.course === 'all'
        ? ((rawWeakTopics[0] && rawWeakTopics[0].course_id) || fallbackCourse)
        : s.course;
      if (!targetCourse) return;
      goToQuiz(targetCourse);
    };
```

- [ ] **Step 4: Compute `courseChips`, replace the two hardcoded sidebar chips**

In the markup, change (lines 68-75):

```html
        <div style="{{ courseChipStyleCs101 }}" onClick="{{ selectCs101 }}">
          <span style="width:8px;height:8px;border-radius:99px;background:var(--color-accent);flex:none"></span>
          Intro to Computer Science
        </div>
        <div style="{{ courseChipStylePsyc }}" onClick="{{ selectPsyc }}">
          <span style="width:8px;height:8px;border-radius:99px;background:var(--color-accent-2);flex:none"></span>
          Cognitive Psychology
        </div>
```

to:

```html
        <sc-for list="{{ courseChips }}" as="c" hint-placeholder-count="2">
          <div style="{{ c.chipStyle }}" onClick="{{ c.onClick }}">
            <span style="{{ c.dotStyle }}"></span>
            {{ c.label }}
          </div>
        </sc-for>
```

(the "All Courses" chip immediately above, lines 64-67, is unchanged — it isn't per-course).

In `renderVals()`, add right after the `emptyStateMessage` computation (after line 838, before `const goToQuiz = ...`):

```javascript
    const dotColors = ['var(--color-accent)', 'var(--color-accent-2)'];
    const courseChips = realCourseIds.map((id, i) => ({
      id: id,
      label: (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase(),
      chipStyle: this.courseChip(s.course === id),
      dotStyle: 'width:8px;height:8px;border-radius:99px;background:' + dotColors[i % dotColors.length] + ';flex:none',
      onClick: () => selectCourse(id)
    })).concat(s.courseDrafts.map(d => ({
      id: d.course_id,
      label: d.course_name + ' · pending',
      chipStyle: this.courseChip(s.course === d.course_id),
      dotStyle: 'width:8px;height:8px;border-radius:99px;background:var(--color-neutral-400);flex:none',
      onClick: () => selectCourse(d.course_id)
    })));
```

(`selectCourse` is defined later in the same function, at line 874 today — that's fine, it's a `const` function expression hoisted by closure timing, not declaration order, since `courseChips` is only *read* inside the object each chip's `onClick` closure captures, evaluated later when clicked, not when `courseChips` is built.)

- [ ] **Step 5: Update the return object**

In the object returned by `renderVals()`, remove these three lines (1079-1080, 1082-1083):

```javascript
      courseChipStyleCs101: this.courseChip(s.course === 'cs101'),
      courseChipStylePsyc: this.courseChip(s.course === 'psyc201'),
```

```javascript
      selectCs101: () => selectCourse('cs101'),
      selectPsyc: () => selectCourse('psyc201'),
```

Add in their place (same area, right after `courseChipStyleAll: this.courseChip(s.course === 'all'),`):

```javascript
      courseChips: courseChips,
```

(keep `selectAll: () => selectCourse('all'),` — unchanged, the "All Courses" chip still uses it directly).

- [ ] **Step 6: Manually verify**

Start the dev server: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8030 --noreload`

Open `http://127.0.0.1:8030/` in a browser. Confirm:
- The sidebar shows exactly two course chips (CS101 in terracotta dot, PSYC201 in sage dot) — same as before this change, now rendered through the loop instead of hardcoded markup.
- Clicking each chip still selects that course (chip background highlights, Dashboard content scopes to it).
- Clicking "All Courses" still works.
- Browser console shows no errors (confirms `COURSE_IDS`/`FALLBACK_COURSE` removal didn't leave a dangling reference anywhere).

Stop the dev server.

- [ ] **Step 7: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Make the sidebar course list dynamic

Replaces the hardcoded COURSE_IDS/FALLBACK_COURSE and duplicated
CS101/PSYC201 chip markup with a loop over whatever the dashboard
endpoint actually returns, including draft (syllabus-pending) classes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Frontend — "Add a class" modal

**Files:**
- Modify: `agent/templates/agent/ontrack.html` (module-level `slugify` helper, state, new class methods, sidebar button, new modal markup, `renderVals()`)

**Interfaces:**
- Consumes: `POST /api/courses/<id>/syllabus/extract/` (existing), `POST /api/courses/<id>/` (Task 2).
- Produces: class methods `openAddClass()`, `openAddClassForDraft(courseId, courseName)`, `closeAddClass()`, `submitAddClass()` — Task 6 calls `this.openAddClassForDraft(...)` from a draft course card's button.

- [ ] **Step 1: Add the `slugify` helper**

In `agent/templates/agent/ontrack.html`, right after the `getCookie` function closes (after line 541, before the blank line that used to hold `COURSE_IDS`), add:

```javascript
function slugify(name) {
  return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}
```

- [ ] **Step 2: Add state and a sequence counter**

Change the state block (now ending at the line with `chatSessionId: null, chatSessions: [], chatSessionsLoading: false, chatSessionsError: null`):

```javascript
    chatMessages: [], chatInput: '', chatLoading: false, chatSending: false, chatError: null,
    chatSessionId: null, chatSessions: [], chatSessionsLoading: false, chatSessionsError: null
  };
```

to:

```javascript
    chatMessages: [], chatInput: '', chatLoading: false, chatSending: false, chatError: null,
    chatSessionId: null, chatSessions: [], chatSessionsLoading: false, chatSessionsError: null,
    addClassOpen: false, addClassName: '', addClassId: '', addClassIdLocked: false,
    addClassFile: null, addClassLoading: false, addClassError: null
  };
```

Add a sequence counter alongside the existing ones (after `_sessionsSeq = 0;`):

```javascript
  _addClassSeq = 0;
```

- [ ] **Step 3: Add the class methods**

Add after `openUpload`/`closeUpload`/`submitUpload` (after `submitUpload`'s closing brace, before `renderVals() {`):

```javascript
  openAddClass() {
    this.setState({
      addClassOpen: true, addClassName: '', addClassId: '', addClassIdLocked: false,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  openAddClassForDraft(courseId, courseName) {
    this.setState({
      addClassOpen: true, addClassName: courseName, addClassId: courseId, addClassIdLocked: true,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  closeAddClass() {
    this._addClassSeq++;
    this.setState({
      addClassOpen: false, addClassName: '', addClassId: '', addClassIdLocked: false,
      addClassFile: null, addClassLoading: false, addClassError: null
    });
  }

  submitAddClass() {
    const s = this.state;
    if (s.addClassIdLocked) {
      if (!s.addClassFile) { this.setState({ addClassError: 'Choose a syllabus file to upload.' }); return; }
    } else {
      if (!s.addClassName.trim() || !s.addClassId) { this.setState({ addClassError: 'Enter a class name.' }); return; }
    }
    const seq = ++this._addClassSeq;
    this.setState({ addClassLoading: true, addClassError: null });

    const onDone = ({ ok, status, data }) => {
      if (seq !== this._addClassSeq) return;
      if (status === 409) { this.setState({ addClassLoading: false, addClassError: data.detail || 'That class already exists.' }); return; }
      if (!ok) { this.setState({ addClassLoading: false, addClassError: data.detail || 'Could not create that class.' }); return; }
      this.closeAddClass();
      this.loadDashboard();
    };
    const onError = (e) => {
      if (seq !== this._addClassSeq) return;
      this.setState({ addClassLoading: false, addClassError: 'Network error: ' + e.message });
    };

    if (s.addClassFile) {
      const body = new FormData();
      body.append('file', s.addClassFile);
      body.append('course_name', s.addClassName);
      fetch(`/api/courses/${s.addClassId}/syllabus/extract/`, {
        method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: body
      })
        .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
        .then(onDone)
        .catch(onError);
      return;
    }

    fetch(`/api/courses/${s.addClassId}/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ course_name: s.addClassName })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
      .then(onDone)
      .catch(onError);
  }
```

- [ ] **Step 4: Add the sidebar button**

In the markup, right after the closing `</div>` of the "This semester" chip block (the `</div>` that closes the `<div style="margin-top:var(--space-6)">` wrapping "This semester" — the block that now ends with the `sc-for` from Task 4, followed by two `</div>` closes), insert a new block:

```html
    <div style="margin-top:var(--space-2);display:flex;flex-direction:column;gap:2px">
      <button type="button" class="btn btn-ghost" style="justify-content:flex-start;width:100%;padding:7px 10px" onClick="{{ openAddClass }}">+ Add class</button>
    </div>
```

- [ ] **Step 5: Add the modal markup**

Right before the final `</div>` that closes the outermost `<div style="display:flex;height:100vh;overflow:hidden">` (the line right before `{% endverbatim %}`), insert:

```html
  <sc-if value="{{ addClassOpen }}" hint-placeholder-val="{{ false }}">
    <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
      <div class="card elev-md" style="padding:var(--space-6);width:420px;max-width:90vw">
        <div class="card-title" style="margin:0 0 var(--space-4)">{{ addClassModalTitle }}</div>

        <sc-if value="{{ !addClassIdLocked }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;flex-direction:column;gap:12px;margin-bottom:var(--space-4)">
            <div>
              <div style="font-size:13px;margin-bottom:4px">Class name</div>
              <input class="input" value="{{ addClassName }}" onChange="{{ onAddClassNameChange }}" style="width:100%"/>
            </div>
            <div style="font-size:12px;opacity:.55">Will be added as <strong>{{ addClassId }}</strong></div>
          </div>
        </sc-if>

        <div style="margin-bottom:var(--space-4)">
          <div style="font-size:13px;margin-bottom:4px">Syllabus <sc-if value="{{ !addClassIdLocked }}" hint-placeholder-val="{{ true }}">(optional — add it now or later)</sc-if></div>
          <input type="file" accept=".pdf,.txt,.md" onChange="{{ onAddClassFileChange }}" style="font-size:13px"/>
        </div>

        <sc-if value="{{ addClassError }}" hint-placeholder-val="{{ false }}">
          <p style="font-size:13px;color:var(--color-accent-700);margin:0 0 var(--space-4)">{{ addClassError }}</p>
        </sc-if>

        <sc-if value="{{ addClassLoading }}" hint-placeholder-val="{{ false }}">
          <div style="font-size:13px;opacity:.7;padding:8px 0">Adding your class…</div>
        </sc-if>

        <sc-if value="{{ !addClassLoading }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary" onClick="{{ closeAddClass }}">Cancel</button>
            <button type="button" class="btn btn-primary" onClick="{{ submitAddClass }}">{{ addClassSubmitLabel }}</button>
          </div>
        </sc-if>
      </div>
    </div>
  </sc-if>
```

- [ ] **Step 6: Add the `renderVals()` bindings**

Add, right after the `courseChips` computation from Task 4:

```javascript
    const onAddClassNameChange = (e) => {
      const name = e.target.value;
      if (s.addClassIdLocked) {
        this.setState({ addClassName: name });
      } else {
        this.setState({ addClassName: name, addClassId: slugify(name) });
      }
    };
    const onAddClassFileChange = (e) => this.setState({ addClassFile: e.target.files[0] || null, addClassError: null });
    const addClassModalTitle = s.addClassIdLocked ? ('Add syllabus — ' + s.addClassName) : 'Add a class';
    const addClassSubmitLabel = s.addClassIdLocked ? 'Upload syllabus' : 'Add class';
```

Add to the returned object (anywhere after `courseChips: courseChips,`):

```javascript
      openAddClass: () => this.openAddClass(),
      addClassOpen: s.addClassOpen,
      addClassName: s.addClassName,
      addClassId: s.addClassId,
      addClassIdLocked: s.addClassIdLocked,
      addClassModalTitle: addClassModalTitle,
      addClassSubmitLabel: addClassSubmitLabel,
      onAddClassNameChange: onAddClassNameChange,
      onAddClassFileChange: onAddClassFileChange,
      addClassError: s.addClassError,
      addClassLoading: s.addClassLoading,
      closeAddClass: () => this.closeAddClass(),
      submitAddClass: () => this.submitAddClass(),
```

- [ ] **Step 7: Manually verify**

Start the dev server: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8030 --noreload`

Open `http://127.0.0.1:8030/`. Click "+ Add class". Confirm:
- Typing a name (e.g. "Organic Chemistry") live-updates the "Will be added as `organic-chemistry`" line.
- Submitting with no file: modal closes, a new sidebar chip appears with a dim/neutral dot and "· pending" suffix (this exercises Task 4's `courseChips` for the draft case).
- Click "+ Add class" again, type a *different* name, attach a small `.txt` file as the syllabus (any plain text works — extraction may fail without a real syllabus format or a configured `ANTHROPIC_API_KEY`, which is fine for this check; confirm the request is sent and a `4xx`/`5xx` error renders in the modal rather than the page crashing). If a working `ANTHROPIC_API_KEY` is configured, confirm success instead: the new class appears as a normal (non-pending) chip.
- Submitting with a name that collides with an existing class shows the 409 error message in the modal.

Delete any test course directories created during this check (e.g. `courses/organic-chemistry/`) so they don't get committed.

Stop the dev server.

- [ ] **Step 8: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Add the "Add a class" modal

Sidebar action that creates a class from a name alone (draft, syllabus
added later) or with a syllabus attached (real immediately) — reuses
the existing syllabus-extract endpoint for the latter and the new
draft-create endpoint for the former.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Frontend — dynamic "Your courses" dashboard cards

**Files:**
- Modify: `agent/templates/agent/ontrack.html` (dashboard card markup, `renderVals()`)

**Interfaces:**
- Consumes: `realCourseIds`, `s.courseDrafts` (Task 4), `this.openUpload` (existing), `this.openAddClassForDraft` (Task 5).
- Produces: `yourCoursesCards` (array bound to the dashboard's `sc-for`).

- [ ] **Step 1: Replace the card markup**

In the markup, change (the "Your courses" grid block):

```html
        <div style="{{ yourCoursesGridStyle }}">
          <sc-if value="{{ showCs101Card }}" hint-placeholder-val="{{ true }}">
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div class="card-kicker">CS101</div>
              <div class="card-title">Intro to Computer Science</div>
              <p class="card-body">{{ cs101Summary }}</p>
              <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)" onClick="{{ openUploadCs101 }}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
                Upload notes
              </button>
              <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                <sc-for list="{{ cs101Tags }}" as="tag" hint-placeholder-count="2">
                  <span class="tag tag-accent">{{ tag.label }}</span>
                </sc-for>
              </div>
              <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                <sc-for list="{{ gradingCs101 }}" as="g" hint-placeholder-count="4">
                  <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
                </sc-for>
              </div>
            </div>
          </sc-if>
          <sc-if value="{{ showPsyc201Card }}" hint-placeholder-val="{{ true }}">
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div class="card-kicker">PSYC201</div>
              <div class="card-title">Cognitive Psychology</div>
              <p class="card-body">{{ psyc201Summary }}</p>
              <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)" onClick="{{ openUploadPsyc201 }}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
                Upload notes
              </button>
              <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                <sc-for list="{{ psyc201Tags }}" as="tag" hint-placeholder-count="2">
                  <span class="tag tag-accent">{{ tag.label }}</span>
                </sc-for>
              </div>
              <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                <sc-for list="{{ gradingPsyc201 }}" as="g" hint-placeholder-count="4">
                  <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
                </sc-for>
              </div>
            </div>
          </sc-if>
        </div>
```

to:

```html
        <div style="{{ yourCoursesGridStyle }}">
          <sc-for list="{{ yourCoursesCards }}" as="c" hint-placeholder-count="2">
            <sc-if value="{{ c.isDraft }}" hint-placeholder-val="{{ false }}">
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div class="card-kicker">{{ c.kicker }}</div>
                <div class="card-title">{{ c.name }}</div>
                <p class="card-body">Syllabus pending</p>
                <button type="button" class="btn btn-primary" style="margin-top:var(--space-2)" onClick="{{ c.onAddSyllabus }}">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
                  Upload syllabus
                </button>
              </div>
            </sc-if>
            <sc-if value="{{ !c.isDraft }}" hint-placeholder-val="{{ true }}">
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div class="card-kicker">{{ c.kicker }}</div>
                <div class="card-title">{{ c.name }}</div>
                <p class="card-body">{{ c.summary }}</p>
                <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)" onClick="{{ c.onUpload }}">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
                  Upload notes
                </button>
                <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                  <sc-for list="{{ c.tags }}" as="tag" hint-placeholder-count="2">
                    <span class="tag tag-accent">{{ tag.label }}</span>
                  </sc-for>
                </div>
                <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
                  <sc-for list="{{ c.grading }}" as="g" hint-placeholder-count="4">
                    <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
                  </sc-for>
                </div>
              </div>
            </sc-if>
          </sc-for>
        </div>
```

- [ ] **Step 2: Compute `yourCoursesCards`, remove the old per-course computations**

In `renderVals()`, remove these lines from the returned object:

```javascript
      gradingCs101: (courseMetaFor('cs101') && courseMetaFor('cs101').grading) || [],
      gradingPsyc201: (courseMetaFor('psyc201') && courseMetaFor('psyc201').grading) || [],
```

```javascript
      showCs101Card: s.course === 'all' || s.course === 'cs101',
      showPsyc201Card: s.course === 'all' || s.course === 'psyc201',
```

```javascript
      cs101Summary: courseCardSummary(courseMetaFor('cs101')),
      psyc201Summary: courseCardSummary(courseMetaFor('psyc201')),
      cs101Tags: courseCardTags(courseMetaFor('cs101')),
      psyc201Tags: courseCardTags(courseMetaFor('psyc201')),
```

```javascript
      openUploadCs101: () => this.openUpload('cs101'),
      openUploadPsyc201: () => this.openUpload('psyc201'),
```

Add a new computation right before the `return {` line (after `courseCardTags`/`dashboardRecentActivity` are defined, anywhere before the return statement — place it right after the `courseCardTags` const, which is defined a few lines above `dashboardRecentActivity` in the existing code):

```javascript
    const yourCoursesCards = realCourseIds
      .filter(id => s.course === 'all' || s.course === id)
      .map(id => {
        const meta = courseMetaFor(id);
        return {
          id: id, isDraft: false,
          kicker: id.toUpperCase(),
          name: (meta && meta.course_name) || id.toUpperCase(),
          summary: courseCardSummary(meta),
          tags: courseCardTags(meta),
          grading: (meta && meta.grading) || [],
          onUpload: () => this.openUpload(id)
        };
      })
      .concat(
        s.courseDrafts
          .filter(d => s.course === 'all' || s.course === d.course_id)
          .map(d => ({
            id: d.course_id, isDraft: true,
            kicker: d.course_id.toUpperCase(),
            name: d.course_name,
            onAddSyllabus: () => this.openAddClassForDraft(d.course_id, d.course_name)
          }))
      );
```

Add `yourCoursesCards: yourCoursesCards,` to the returned object in place of the six removed lines.

- [ ] **Step 3: Manually verify**

Start the dev server: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8030 --noreload`

Open `http://127.0.0.1:8030/`. Confirm:
- The Dashboard's "Your courses" grid shows CS101 and PSYC201 exactly as before (kicker, name, summary, "Upload notes" button, tags).
- Use "+ Add class" (Task 5) with no file to create a draft. Confirm its card shows the class name, "Syllabus pending", and an "Upload syllabus" button (not the tags/grading rows a real card has).
- Click that draft card's "Upload syllabus" button. Confirm the "Add a class" modal opens titled "Add syllabus — `<name>`", with no name field (just the file input), matching `addClassIdLocked` behavior from Task 5.
- Click a real course's "Upload notes" button — confirm it still opens the existing upload-notes modal (this exercises `openUpload`, unchanged, now called with a loop variable instead of a dedicated per-course function).
- Select a single course from the sidebar (not "All Courses") — confirm the grid narrows to just that one card.

Delete any test course directories created during this check.

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Make the dashboard "Your courses" grid dynamic

Collapses the duplicated CS101/PSYC201 card blocks into one loop, with
a distinct card variant for draft (syllabus-pending) classes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Frontend — "Upload notes" sidebar entry

**Files:**
- Modify: `agent/templates/agent/ontrack.html` (state, class methods, sidebar button, new picker modal, `renderVals()`)

**Interfaces:**
- Consumes: `realCourseIds`, `courseMetaFor` (Task 4), `this.openUpload` (existing).

- [ ] **Step 1: Add state and methods**

Add `uploadPickerOpen: false` to the state block (same edit region as Task 5's state addition — append to the object):

```javascript
    addClassOpen: false, addClassName: '', addClassId: '', addClassIdLocked: false,
    addClassFile: null, addClassLoading: false, addClassError: null,
    uploadPickerOpen: false
  };
```

Add methods after `closeAddClass`/`submitAddClass` (before `renderVals() {`):

```javascript
  openUploadPicker() {
    this.setState({ uploadPickerOpen: true });
  }

  closeUploadPicker() {
    this.setState({ uploadPickerOpen: false });
  }
```

- [ ] **Step 2: Add the sidebar button**

Change the block Task 5 added:

```html
    <div style="margin-top:var(--space-2);display:flex;flex-direction:column;gap:2px">
      <button type="button" class="btn btn-ghost" style="justify-content:flex-start;width:100%;padding:7px 10px" onClick="{{ openAddClass }}">+ Add class</button>
    </div>
```

to:

```html
    <div style="margin-top:var(--space-2);display:flex;flex-direction:column;gap:2px">
      <button type="button" class="btn btn-ghost" style="justify-content:flex-start;width:100%;padding:7px 10px" onClick="{{ openAddClass }}">+ Add class</button>
      <button type="button" class="btn btn-ghost" style="justify-content:flex-start;width:100%;padding:7px 10px" onClick="{{ openUploadPicker }}">Upload notes</button>
    </div>
```

- [ ] **Step 3: Add the picker modal markup**

Right after the "Add a class" modal's closing `</sc-if>` (Task 5, Step 5), before the final `</div>` closing the outermost flex container, insert:

```html
  <sc-if value="{{ uploadPickerOpen }}" hint-placeholder-val="{{ false }}">
    <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
      <div class="card elev-md" style="padding:var(--space-6);width:320px;max-width:90vw">
        <div class="card-title" style="margin:0 0 var(--space-4)">Upload notes — choose a class</div>
        <sc-if value="{{ uploadPickerEmpty }}" hint-placeholder-val="{{ false }}">
          <p class="card-body" style="margin:0 0 var(--space-4)">No classes with a syllabus yet — add a class first.</p>
        </sc-if>
        <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:var(--space-4)">
          <sc-for list="{{ uploadPickerItems }}" as="item" hint-placeholder-count="2">
            <div style="padding:8px 10px;border-radius:var(--radius-lg);cursor:pointer;font-size:13.5px" onClick="{{ item.onClick }}">{{ item.name }}</div>
          </sc-for>
        </div>
        <button type="button" class="btn btn-secondary" onClick="{{ closeUploadPicker }}">Cancel</button>
      </div>
    </div>
  </sc-if>
```

- [ ] **Step 4: Add the `renderVals()` bindings**

Add, near the other Task-5-added consts:

```javascript
    const uploadPickerItems = realCourseIds.map(id => ({
      id: id,
      name: (courseMetaFor(id) && courseMetaFor(id).course_name) || id.toUpperCase(),
      onClick: () => { this.closeUploadPicker(); this.openUpload(id); }
    }));
```

Add to the returned object:

```javascript
      openUploadPicker: () => this.openUploadPicker(),
      closeUploadPicker: () => this.closeUploadPicker(),
      uploadPickerOpen: s.uploadPickerOpen,
      uploadPickerEmpty: realCourseIds.length === 0,
      uploadPickerItems: uploadPickerItems,
```

- [ ] **Step 5: Manually verify**

Start the dev server: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8030 --noreload`

Open `http://127.0.0.1:8030/`. Click "Upload notes" in the sidebar. Confirm:
- A picker lists CS101 and PSYC201 by name (not any draft class you may have created in earlier task verification — drafts must not appear here).
- Clicking one closes the picker and opens the existing upload-notes modal for that course (same modal the per-card button opens).
- Uploading a note through this path succeeds exactly as the per-card button does (the same `openUpload`/`submitUpload` machinery, untouched).

Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Add an "Upload notes" sidebar entry

A second way to reach the existing upload-notes modal: pick a class
first from the sidebar, rather than navigating to its dashboard card.
Drafts are excluded — they can't accept notes without a syllabus.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Frontend — draft empty states in Quiz/Chat/Progress

**Files:**
- Modify: `agent/templates/agent/ontrack.html` (Chat tab markup, `renderVals()`)

**Interfaces:**
- Consumes: `s.courseDrafts` (Task 4).
- Produces: `courseIsDraft` (used by Quiz/Progress's existing empty-state markup unchanged, and by a new wrapper around the Chat tab's content).

- [ ] **Step 1: Compute `courseIsDraft` and branch `emptyStateMessage`/`courseDisplayName`**

In `renderVals()`, right after `const courseMetaLoaded = s.courseMeta !== null;` (line 833), add:

```javascript
    const courseIsDraft = s.course !== 'all' && s.courseDrafts.some(d => d.course_id === s.course);
    const draftName = courseIsDraft ? (s.courseDrafts.find(d => d.course_id === s.course) || {}).course_name : null;
```

Change `courseDisplayName` (lines 834-836):

```javascript
    const courseDisplayName = s.course === 'all'
      ? 'your courses'
      : (courseMetaFor(s.course) && courseMetaFor(s.course).course_name) || s.course.toUpperCase();
```

to:

```javascript
    const courseDisplayName = s.course === 'all'
      ? 'your courses'
      : (courseMetaFor(s.course) && courseMetaFor(s.course).course_name) || draftName || s.course.toUpperCase();
```

Change `emptyStateMessage` (line 838):

```javascript
    const emptyStateMessage = 'No notes uploaded yet for ' + courseDisplayName + ' — nothing to quiz or track until a lecture is added.';
```

to:

```javascript
    const emptyStateMessage = courseIsDraft
      ? "This class doesn't have a syllabus yet. Add one from the sidebar to start tracking it."
      : 'No notes uploaded yet for ' + courseDisplayName + ' — nothing to quiz or track until a lecture is added.';
```

(Quiz and Progress already render `emptyStateMessage` inside the existing `showNoNotesEmptyState` card at two places in the markup — no template change needed for either tab; `showNoNotesEmptyState` already evaluates `true` for a draft today, since `courseHasNotes` is `false` for a course with no entry in `courseMeta`.)

- [ ] **Step 2: Gate the Chat tab behind `courseIsDraft`**

In the markup, change the Chat tab's opening (currently):

```html
    <sc-if value="{{ isChat }}" hint-placeholder-val="{{ false }}">
      <div style="display:flex;height:100%">
        <div style="width:270px;flex:none;border-right:1px solid var(--color-neutral-200);padding:var(--space-6);overflow-y:auto">
```

to:

```html
    <sc-if value="{{ isChat }}" hint-placeholder-val="{{ false }}">
      <sc-if value="{{ courseIsDraft }}" hint-placeholder-val="{{ false }}">
        <div style="padding:var(--space-8) var(--space-8);max-width:720px;margin:0 auto">
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">{{ courseIdUpper }}</div>
            <div class="card-title">{{ courseName }}</div>
            <p class="card-body">{{ emptyStateMessage }}</p>
          </div>
        </div>
      </sc-if>
      <sc-if value="{{ !courseIsDraft }}" hint-placeholder-val="{{ true }}">
      <div style="display:flex;height:100%">
        <div style="width:270px;flex:none;border-right:1px solid var(--color-neutral-200);padding:var(--space-6);overflow-y:auto">
```

And change the Chat tab's closing (currently):

```html
        </div>
      </div>
    </sc-if>
```

(the one immediately following the chat input row, closing the two-pane layout and then `isChat`) to:

```html
        </div>
      </div>
      </sc-if>
    </sc-if>
```

- [ ] **Step 3: Add `courseIsDraft` to the returned object**

Add to the object `renderVals()` returns:

```javascript
      courseIsDraft: courseIsDraft,
```

- [ ] **Step 4: Manually verify**

Start the dev server: `venv/Scripts/python.exe manage.py runserver 127.0.0.1:8030 --noreload`

Open `http://127.0.0.1:8030/`. Use "+ Add class" to create a draft (no file). Select that draft's sidebar chip, then:
- Go to **Quiz** — confirm it shows "This class doesn't have a syllabus yet. Add one from the sidebar to start tracking it." instead of the "no notes" message, with the draft's name as the card title (not its raw id).
- Go to **Progress** — same message, same card.
- Go to **Ask Cora** — confirm the whole two-pane chat layout (session list, message input) is replaced by the same empty-state card, and no network error appears in the console from an attempted `/sessions/` or `/ask/` call against a syllabus-less course.
- Select a real course (CS101) again and confirm Quiz/Progress/Chat all behave exactly as before this task on a course that has a syllabus.

Delete the test draft's directory (`courses/<slug>/`) created during this check.

Stop the dev server.

- [ ] **Step 5: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "$(cat <<'EOF'
Add a draft-aware empty state to Quiz, Chat, and Progress

A syllabus-pending class now gets its own message ("add a syllabus
from the sidebar") instead of the "no notes uploaded" message meant
for a real course, and the Chat tab no longer renders an input a
draft can't actually use.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
