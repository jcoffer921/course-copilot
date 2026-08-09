# Dashboard Live Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Dashboard tab of `course_copilot.html` to real backend data — upcoming deadlines, weak topics, the "Your courses" grid, and recent quiz activity — and make `courseHasNotes` (which gates Quiz/Chat/Progress's empty states too) genuinely live everywhere via a `componentDidMount()` fetch, replacing a mock value that only happened to match reality.

**Architecture:** Two small new backend endpoints, both pure compositions of already-existing service functions (no new business logic, no new storage format). `GET /api/dashboard/` aggregates deadlines-across-courses plus per-course summary stats in one payload (avoids an N-call fan-out from the frontend for the course-cards grid, which needs every course's data simultaneously). `GET /api/courses/<id>/quiz/history/` is a small, reusable, course-scoped "recent attempts" endpoint. On the frontend, a `componentDidMount()` hook fetches the aggregate endpoint once on load; the Dashboard tab (and course-switching while on it) refetches for freshness, mirroring the refetch-on-entry pattern the Quiz tab already established.

**Tech Stack:** Django 6 (ASGI), adrf async views, vanilla JS `fetch` inside the existing DC pseudo-component template. No build step, no JS test runner (backend gets pytest coverage; frontend changes get manual/live-browser verification, same split as the Quiz pass).

## Global Constraints

- No new storage format or schema change — both new endpoints only ever read existing files (`syllabus.json`, `notes/*.json`, `quiz_history.json`, `mastery_scores.json`) via already-existing `storage.py`/`mastery.py`/`reminders.py` functions.
- Progress and Chat tabs stay entirely on mock data — do not touch `allTopicsRaw`, `attemptsRaw` (as consumed by Progress's own "Mastery by topic"/"Recent attempts" cards), or anything under `isChat`/`isProgress` template blocks.
- Dashboard's new "Recent quiz activity" data uses its own prop (`dashboardRecentAttempts`), deliberately NOT reusing the existing `recentAttempts` prop that Progress's own "Recent attempts" card reads — keeps this pass's scope from bleeding into the future Progress pass.
- No dynamic course discovery — the sidebar and all course lookups stay hardcoded to `cs101`/`psyc201`. `/api/dashboard/` internally uses `reminders.list_courses()` (which scans disk), but the frontend only ever reads the two keys it already knows about.
- A corrupt per-course file must not take down the whole `/api/dashboard/` response for every other course — isolate the failure to that course's own slot.

---

### Task 1: `GET /api/dashboard/` — cross-course aggregate endpoint

**Files:**
- Create: `agent/services/dashboard.py`
- Test: `agent/tests/test_dashboard.py`
- Modify: `agent/views.py` (add `DashboardView`, add `dashboard` to the services import)
- Modify: `agent/urls.py` (add the route)

**Interfaces:**
- Consumes: `reminders.list_courses() -> list[str]`, `reminders.upcoming_deadlines(within_days=None|int, course_ids=None|list[str]) -> list[dict]` (each `{"course_id", "date", "title", "type"}`), `storage.read_syllabus(course_id) -> dict` (has `"course_name"`, `"topics"`, `"grading"`), `storage.read_notes(course_id) -> list`, `mastery.weak_topics(course_id) -> list[dict]` (each `{"topic", "score", "attempts", "last_seen", "status"}`), `storage.SyllabusStorageError`, `storage.QuizStorageError`.
- Produces: `dashboard.build_dashboard() -> dict` with shape:
  ```python
  {
    "deadlines": [{"course_id": str, "date": str, "title": str, "type": str}, ...],
    "courses": {
      "<course_id>": {
        "course_name": str, "has_notes": bool, "topics_count": int, "quizzed_count": int,
        "next_deadline": {"course_id": str, "date": str, "title": str, "type": str} | None,
        "grading": [{"component": str, "weight_pct": int}, ...],
        "weak_topics": [{"topic": str, "score": float, "attempts": int, "last_seen": str, "status": str}, ...],
      } | {"error": str},
      ...
    }
  }
  ```
  Later tasks consume this exact shape from the JSON HTTP response — field names above are load-bearing for Task 3.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_dashboard.py`:

```python
import pytest

from agent.services import dashboard, mastery, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_course(course_id, topics, grading, dates, has_notes=False):
    storage.write_syllabus(course_id, {
        "course_id": course_id,
        "course_name": course_id.upper(),
        "dates": dates,
        "grading": grading,
        "topics": topics,
    })
    if has_notes:
        storage.write_notes(course_id, "lecture01", {
            "lecture_id": "lecture01",
            "source": "notes",
            "date": "2026-01-01",
            "topics": topics[:1],
            "chunks": [{"id": "c1", "topic": topics[0], "text": "..."}],
        })


def test_build_dashboard_composes_course_data(isolated_courses_dir):
    _seed_course(
        "cs101", topics=["A", "B", "C"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": "2026-08-10", "title": "Quiz 1", "type": "assignment"}],
        has_notes=True,
    )
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    mastery.rebuild_scores("cs101")

    data = dashboard.build_dashboard()

    course = data["courses"]["cs101"]
    assert course["course_name"] == "CS101"
    assert course["has_notes"] is True
    assert course["topics_count"] == 3
    assert course["quizzed_count"] == 1
    assert course["grading"] == [{"component": "HW", "weight_pct": 100}]
    assert [t["topic"] for t in course["weak_topics"]] == ["A"]


def test_build_dashboard_course_without_notes_or_mastery(isolated_courses_dir):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[], has_notes=False)

    data = dashboard.build_dashboard()

    course = data["courses"]["psyc201"]
    assert course["has_notes"] is False
    assert course["quizzed_count"] == 0
    assert course["weak_topics"] == []
    assert course["next_deadline"] is None


def test_build_dashboard_next_deadline_uncapped_but_top_level_deadlines_windowed(isolated_courses_dir):
    from datetime import date, timedelta

    far_date = (date.today() + timedelta(days=20)).isoformat()
    _seed_course(
        "cs101", topics=["A"], grading=[],
        dates=[{"date": far_date, "title": "Midterm", "type": "exam"}], has_notes=False,
    )

    data = dashboard.build_dashboard()

    assert data["courses"]["cs101"]["next_deadline"] == {
        "course_id": "cs101", "date": far_date, "title": "Midterm", "type": "exam",
    }
    assert data["deadlines"] == []


def test_build_dashboard_isolates_corrupt_course(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[], has_notes=False)

    bad_dir = isolated_courses_dir / "badcourse"
    bad_dir.mkdir()
    (bad_dir / "syllabus.json").write_text("{not valid json", encoding="utf-8")

    data = dashboard.build_dashboard()

    assert "error" in data["courses"]["badcourse"]
    assert data["courses"]["cs101"]["topics_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.services.dashboard'` (or `ImportError`)

- [ ] **Step 3: Implement `agent/services/dashboard.py`**

```python
"""
Cross-course summary for the Dashboard tab: global upcoming deadlines plus,
per course, everything the "Your courses" grid needs. Pure composition of
existing reads — no new storage format, nothing written.
"""

from . import mastery, reminders, storage


def _course_summary(course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id)
    weak_topics = mastery.weak_topics(course_id)
    upcoming = reminders.upcoming_deadlines(within_days=None, course_ids=[course_id])

    return {
        "course_name": syllabus.get("course_name", course_id),
        "has_notes": bool(storage.read_notes(course_id)),
        "topics_count": len(syllabus.get("topics", [])),
        "quizzed_count": len(weak_topics),
        "next_deadline": upcoming[0] if upcoming else None,
        "grading": syllabus.get("grading", []),
        "weak_topics": weak_topics,
    }


def build_dashboard() -> dict:
    """Never raises — a corrupt course's data is isolated to
    {"error": "..."} in its own slot rather than failing every other
    course's dashboard data along with it."""
    courses = {}
    for course_id in reminders.list_courses():
        try:
            courses[course_id] = _course_summary(course_id)
        except (storage.SyllabusStorageError, storage.QuizStorageError) as e:
            courses[course_id] = {"error": str(e)}

    return {
        "deadlines": reminders.upcoming_deadlines(within_days=14),
        "courses": courses,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: 4 passed

- [ ] **Step 5: Add `DashboardView`**

In `agent/views.py`, change the services import (line 14) from:
```python
from .services import chunk_notes, mastery, quiz, reminders, sessions, storage
```
to:
```python
from .services import chunk_notes, dashboard, mastery, quiz, reminders, sessions, storage
```

Add this class immediately after `RemindersView` (after its closing, currently ending around line 262, right before `class SyllabusDetailView`):

```python
class DashboardView(APIView):
    """
    GET /api/dashboard/
    Cross-course summary for the Dashboard tab: upcoming deadlines (14-day
    window) plus, per course, topics/quizzed counts, next deadline
    (uncapped), grading, and weak topics. Always 200 — a corrupt course's
    data is isolated to its own {"error": ...} slot by build_dashboard(),
    never fails the whole response.
    """

    async def get(self, request):
        data = await sync_to_async(dashboard.build_dashboard)()
        return Response(data, status=status.HTTP_200_OK)
```

- [ ] **Step 6: Add the URL route**

In `agent/urls.py`, add this line right after `path("reminders/", ...)`:
```python
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
```

- [ ] **Step 7: Verify the full suite and manage.py check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all passing (previous count + 4 new)

Run: `venv/Scripts/python.exe manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add agent/services/dashboard.py agent/tests/test_dashboard.py agent/views.py agent/urls.py
git commit -m "Add GET /api/dashboard/ cross-course aggregate endpoint"
```

---

### Task 2: `GET /api/courses/<id>/quiz/history/` — recent attempts endpoint

**Files:**
- Modify: `agent/services/quiz.py` (add `recent_attempts`)
- Create: `agent/tests/test_quiz.py`
- Modify: `agent/views.py` (add `QuizHistoryView`)
- Modify: `agent/urls.py` (add the route)

**Interfaces:**
- Consumes: `storage.read_quiz_history(course_id) -> dict` (has `"attempts": [...]`, each attempt has `"timestamp"`).
- Produces: `quiz.recent_attempts(course_id: str, limit: int = 10) -> list[dict]`, newest-first by `timestamp`. Consumed by Task 3's frontend via the HTTP response `{"attempts": [...]}`.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_quiz.py`:

```python
import pytest

from agent.services import quiz, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def test_recent_attempts_newest_first(isolated_courses_dir):
    storage.append_quiz_attempt("cs101", {"topic": "A", "timestamp": "2026-01-01T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "B", "timestamp": "2026-01-03T00:00:00"})
    storage.append_quiz_attempt("cs101", {"topic": "C", "timestamp": "2026-01-02T00:00:00"})

    attempts = quiz.recent_attempts("cs101")

    assert [a["topic"] for a in attempts] == ["B", "C", "A"]


def test_recent_attempts_respects_limit(isolated_courses_dir):
    for i in range(5):
        storage.append_quiz_attempt("cs101", {"topic": str(i), "timestamp": f"2026-01-0{i + 1}T00:00:00"})

    attempts = quiz.recent_attempts("cs101", limit=2)

    assert len(attempts) == 2
    assert [a["topic"] for a in attempts] == ["4", "3"]


def test_recent_attempts_empty_for_new_course(isolated_courses_dir):
    assert quiz.recent_attempts("brandnew") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_quiz.py -v`
Expected: FAIL with `AttributeError: module 'agent.services.quiz' has no attribute 'recent_attempts'`

- [ ] **Step 3: Implement `recent_attempts()`**

Append to `agent/services/quiz.py` (after `record_attempt`, at the end of the file):

```python
def recent_attempts(course_id: str, limit: int = 10) -> list:
    """Most recent quiz attempts for this course, newest first."""
    history = storage.read_quiz_history(course_id)
    attempts = sorted(history.get("attempts", []), key=lambda a: a.get("timestamp") or "", reverse=True)
    return attempts[:limit]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_quiz.py -v`
Expected: 3 passed

- [ ] **Step 5: Add `QuizHistoryView`**

In `agent/views.py`, add this class immediately after `QuizRecordView` (after its closing, currently ending around line 243, right before `class RemindersView`):

```python
class QuizHistoryView(APIView):
    """
    GET /api/courses/<course_id>/quiz/history/?limit=<int, default 10>
    Most recent quiz attempts for this course, newest first.
    """

    async def get(self, request, course_id):
        raw_limit = request.query_params.get("limit")
        limit = int(raw_limit) if raw_limit else 10

        try:
            attempts = await sync_to_async(quiz.recent_attempts)(course_id, limit=limit)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"attempts": attempts}, status=status.HTTP_200_OK)
```

- [ ] **Step 6: Add the URL route**

In `agent/urls.py`, add this line right after `path("courses/<slug:course_id>/quiz/record/", ...)`:
```python
    path("courses/<slug:course_id>/quiz/history/", views.QuizHistoryView.as_view(), name="quiz-history"),
```

- [ ] **Step 7: Verify the full suite and manage.py check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all passing (previous count + 3 new)

Run: `venv/Scripts/python.exe manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add agent/services/quiz.py agent/tests/test_quiz.py agent/views.py agent/urls.py
git commit -m "Add GET /api/courses/<id>/quiz/history/ recent-attempts endpoint"
```

---

### Task 3: Wire the Dashboard tab to `/api/dashboard/` and `/api/courses/<id>/quiz/history/`

**Files:**
- Modify: `agent/templates/agent/course_copilot.html`
  - `state = {...}` block (currently `course_copilot.html:404-408`)
  - `renderVals()` body: `courseData` object (currently `:492-539`), the `cd`/`courseHasNotes`/`emptyStateMessage`/`setTab`/`selectCourse` block (`:540-562`), the `deadlines`/`weakTopics`/`allTopics`/`recentAttempts` computation block (`:564-582`), and the returned props object (`:620-` onward)
  - New class methods: `componentDidMount`, `loadDashboard`, `loadDashboardRecent`
  - Dashboard template block (currently `:79-188`)

**Interfaces:**
- Consumes: `GET /api/dashboard/` → `{ deadlines: [...], courses: { "<id>": {course_name, has_notes, topics_count, quizzed_count, next_deadline, grading, weak_topics} | {error} } }` (Task 1). `GET /api/courses/<id>/quiz/history/?limit=4` → `{ attempts: [{topic, question, correct, ...}, ...] }` (Task 2).
- Produces: nothing consumed outside this file.

**Note on line numbers:** Tasks 1 and 2 don't touch this file, so the line numbers below match the file's current state exactly. If a prior step in this task shifted lines, re-locate by the quoted surrounding code rather than the number.

- [ ] **Step 1: Add new state fields**

In `state = {...}` (`course_copilot.html:404-408`), change:
```js
  state = {
    tab: 'dashboard', course: 'cs101',
    quizStep: 0, quizQuestion: null, quizMcAnswer: null,
    quizCorrectCount: 0, quizLoading: false, quizError: null, quizErrorSource: null
  };
```
to:
```js
  state = {
    tab: 'dashboard', course: 'cs101',
    courseMeta: null, dashboardDeadlines: [], dashboardLoading: false, dashboardError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
    quizStep: 0, quizQuestion: null, quizMcAnswer: null,
    quizCorrectCount: 0, quizLoading: false, quizError: null, quizErrorSource: null
  };
```

- [ ] **Step 2: Add `componentDidMount`, `loadDashboard`, `loadDashboardRecent` methods**

Add these three methods to the `Component` class, immediately before `loadQuestion` (`course_copilot.html:432`):

```js
  componentDidMount() {
    this.loadDashboard();
    this.loadDashboardRecent(this.state.course);
  }

  loadDashboard() {
    this.setState({ dashboardLoading: true, dashboardError: null });
    fetch('/api/dashboard/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) { this.setState({ dashboardLoading: false, dashboardError: data.detail || 'Could not load dashboard data.' }); return; }
        this.setState({ dashboardLoading: false, courseMeta: data.courses, dashboardDeadlines: data.deadlines });
      })
      .catch(e => this.setState({ dashboardLoading: false, dashboardError: 'Network error: ' + e.message }));
  }

  loadDashboardRecent(courseId) {
    this.setState({ dashboardRecentLoading: true, dashboardRecentError: null });
    fetch(`/api/courses/${courseId}/quiz/history/?limit=4`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) { this.setState({ dashboardRecentLoading: false, dashboardRecentError: data.detail || 'Could not load recent activity.' }); return; }
        this.setState({ dashboardRecentLoading: false, dashboardRecentAttempts: data.attempts });
      })
      .catch(e => this.setState({ dashboardRecentLoading: false, dashboardRecentError: 'Network error: ' + e.message }));
  }
```

These deliberately don't set `X-CSRFToken` headers — both are `GET` requests, which Django's CSRF protection never checks.

- [ ] **Step 3: Update `setTab` and `selectCourse` to refresh Dashboard data**

In `course_copilot.html:544-562`, change:
```js
    const setTab = (t) => {
      this._quizSeq++;
      if (t === 'quiz') {
        this.setState({ tab: t, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
        if (courseHasNotes) this.loadQuestion(s.course);
      } else {
        this.setState({ tab: t });
      }
    };

    const selectCourse = (courseId) => {
      this._quizSeq++;
      if (s.tab === 'quiz') {
        this.setState({ course: courseId, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
        if (courseData[courseId].hasNotes) this.loadQuestion(courseId);
      } else {
        this.setState({ course: courseId });
      }
    };
```
to:
```js
    const setTab = (t) => {
      this._quizSeq++;
      if (t === 'quiz') {
        this.setState({ tab: t, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
        if (courseHasNotes) this.loadQuestion(s.course);
      } else if (t === 'dashboard') {
        this.setState({ tab: t });
        this.loadDashboard();
        this.loadDashboardRecent(s.course);
      } else {
        this.setState({ tab: t });
      }
    };

    const selectCourse = (courseId) => {
      this._quizSeq++;
      if (s.tab === 'quiz') {
        this.setState({ course: courseId, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
        if (courseMetaFor(courseId) && courseMetaFor(courseId).has_notes) this.loadQuestion(courseId);
      } else if (s.tab === 'dashboard') {
        this.setState({ course: courseId });
        this.loadDashboardRecent(courseId);
      } else {
        this.setState({ course: courseId });
      }
    };
```

(`courseMetaFor` is defined in Step 4, which runs earlier in `renderVals()` — both `setTab` and `selectCourse` are defined after it, so this is safe.)

- [ ] **Step 4: Replace `cd`/`courseHasNotes`/`emptyStateMessage` derivation and shrink `courseData`**

`courseData` (`course_copilot.html:492-539`) loses every field now sourced live: `hasNotes`, `grading`, `deadlinesRaw`, `weakTopics`, `name`. `allTopicsRaw` and `attemptsRaw` stay — they still feed Progress's own (still-mock) cards. Change:
```js
    const courseData = {
      cs101: {
        name: 'Intro to Computer Science',
        hasNotes: true,
        grading: [
          { component: 'Homework', weight_pct: 30 },
          { component: 'Midterm', weight_pct: 25 },
          { component: 'Final', weight_pct: 25 },
          { component: 'Participation', weight_pct: 20 }
        ],
        deadlinesRaw: [
          { month: 'SEP', day: '4', title: 'First day of class', course: 'CS101', type: 'other' },
          { month: 'SEP', day: '18', title: 'Homework 1 due', course: 'CS101', type: 'assignment' },
          { month: 'OCT', day: '2', title: 'Homework 2 due', course: 'CS101', type: 'assignment' },
          { month: 'OCT', day: '14', title: 'Midterm Exam', course: 'CS101', type: 'exam' },
        ],
        weakTopics: [
          { topic: 'Recursion', pct: 46, barStyle: 'width:46%;height:100%;border-radius:99px;background:var(--color-accent-700)' },
          { topic: 'Sorting & searching', pct: 55, barStyle: 'width:55%;height:100%;border-radius:99px;background:var(--color-accent-700)' }
        ],
        allTopicsRaw: [
          { topic: 'Recursion', score: 0.46, status: 'developing' },
          { topic: 'Sorting and searching algorithms', score: 0.55, status: 'developing' },
          { topic: 'Variables, control flow, and functions', score: null, status: 'unassessed' },
          { topic: 'Lists, dictionaries, and strings', score: null, status: 'unassessed' },
          { topic: 'Basic object-oriented programming', score: null, status: 'unassessed' },
          { topic: 'Big-O notation and algorithmic complexity', score: null, status: 'unassessed' },
          { topic: 'File I/O and error handling', score: null, status: 'unassessed' },
        ],
        attemptsRaw: [
          { topic: 'Recursion', question: 'What happens without a base case?', correct: true },
          { topic: 'Sorting and searching algorithms', question: 'What is the time complexity of binary search?', correct: false },
          { topic: 'Recursion', question: 'Time complexity of naive recursive Fibonacci?', correct: false },
          { topic: 'Sorting and searching algorithms', question: 'Worst-case time complexity of Linear Search?', correct: true },
        ]
      },
      psyc201: {
        name: 'Cognitive Psychology',
        hasNotes: false,
        grading: [
          { component: 'Problem sets', weight_pct: 20 },
          { component: 'Midterm', weight_pct: 30 },
          { component: 'Final', weight_pct: 35 },
          { component: 'Participation', weight_pct: 15 }
        ],
        deadlinesRaw: [], weakTopics: [], allTopicsRaw: [], attemptsRaw: []
      }
    };
    const cd = courseData[s.course];
    const courseHasNotes = cd.hasNotes;
    const emptyStateMessage = 'No notes uploaded yet for ' + cd.name + ' — nothing to quiz or track until a lecture is added.';
```
to:
```js
    const courseData = {
      cs101: {
        allTopicsRaw: [
          { topic: 'Recursion', score: 0.46, status: 'developing' },
          { topic: 'Sorting and searching algorithms', score: 0.55, status: 'developing' },
          { topic: 'Variables, control flow, and functions', score: null, status: 'unassessed' },
          { topic: 'Lists, dictionaries, and strings', score: null, status: 'unassessed' },
          { topic: 'Basic object-oriented programming', score: null, status: 'unassessed' },
          { topic: 'Big-O notation and algorithmic complexity', score: null, status: 'unassessed' },
          { topic: 'File I/O and error handling', score: null, status: 'unassessed' },
        ],
        attemptsRaw: [
          { topic: 'Recursion', question: 'What happens without a base case?', correct: true },
          { topic: 'Sorting and searching algorithms', question: 'What is the time complexity of binary search?', correct: false },
          { topic: 'Recursion', question: 'Time complexity of naive recursive Fibonacci?', correct: false },
          { topic: 'Sorting and searching algorithms', question: 'Worst-case time complexity of Linear Search?', correct: true },
        ]
      },
      psyc201: {
        allTopicsRaw: [], attemptsRaw: []
      }
    };
    const courseMetaFor = (id) => (s.courseMeta && s.courseMeta[id]) || null;
    const cd = courseData[s.course];
    const courseHasNotes = !!(courseMetaFor(s.course) && courseMetaFor(s.course).has_notes);
    const courseDisplayName = (courseMetaFor(s.course) && courseMetaFor(s.course).course_name) || s.course.toUpperCase();
    const emptyStateMessage = 'No notes uploaded yet for ' + courseDisplayName + ' — nothing to quiz or track until a lecture is added.';
```

- [ ] **Step 5: Replace the `deadlines`/`weakTopics` computation, add course-card and recent-activity helpers**

In `course_copilot.html:564-582`, change:
```js
    const deadlines = cd.deadlinesRaw.map(d => Object.assign({}, d, {
      typeLabel: d.type === 'exam' ? 'Exam' : d.type === 'assignment' ? 'Assignment' : 'Term start',
      tagStyle: typeStyle(d.type)
    }));
    const weakTopics = cd.weakTopics;
    const allTopics = cd.allTopicsRaw.map(function (t) {
```
to:
```js
    const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const dateParts = (isoDate) => {
      const bits = isoDate.split('-').map(Number);
      return { monthAbbrUpper: MONTH_LABELS[bits[1] - 1].toUpperCase(), monthLabel: MONTH_LABELS[bits[1] - 1], day: String(bits[2]) };
    };

    const deadlines = s.dashboardDeadlines.map(d => {
      const dp = dateParts(d.date);
      return {
        month: dp.monthAbbrUpper, day: dp.day, title: d.title, course: d.course_id.toUpperCase(),
        typeLabel: d.type === 'exam' ? 'Exam' : d.type === 'assignment' ? 'Assignment' : 'Other',
        tagStyle: typeStyle(d.type)
      };
    });
    const weakTopics = ((courseMetaFor(s.course) && courseMetaFor(s.course).weak_topics) || []).slice(0, 2).map(t => {
      const pct = Math.round(t.score * 100);
      return { topic: t.topic, pct: pct, barStyle: 'width:' + pct + '%;height:100%;border-radius:99px;background:var(--color-accent-700)' };
    });
    const courseCardSummary = (meta) => {
      if (!meta) return 'Loading…';
      const parts = [meta.topics_count + ' topics', meta.quizzed_count + ' quizzed'];
      if (meta.next_deadline) {
        const dp = dateParts(meta.next_deadline.date);
        parts.push(meta.next_deadline.title.toLowerCase() + ' ' + dp.monthLabel + ' ' + dp.day);
      }
      return parts.join(' · ');
    };
    const courseCardTags = (meta) => (meta ? meta.weak_topics.slice(0, 2) : []).map(t => ({
      label: t.topic + ' — ' + (statusLabel[t.status] || t.status)
    }));
    const dashboardRecentActivity = s.dashboardRecentAttempts.map(a => ({
      topic: a.topic, question: a.question, correct: a.correct, incorrect: !a.correct,
      iconColor: a.correct ? 'var(--color-accent-2-700)' : 'var(--color-accent-700)'
    }));
    const retryDashboard = () => this.loadDashboard();
    const retryDashboardRecent = () => this.loadDashboardRecent(s.course);

    const allTopics = cd.allTopicsRaw.map(function (t) {
```

(`typeStyle` and `statusLabel` are pre-existing locals defined earlier in `renderVals()` — reused as-is, not redefined.)

- [ ] **Step 6: Update the returned props object**

In the `return { ... }` object (`course_copilot.html:620` onward):
- Change `courseName: cd.name,` to `courseName: courseDisplayName,`
- Change `gradingCs101: courseData.cs101.grading,` to `gradingCs101: (courseMetaFor('cs101') && courseMetaFor('cs101').grading) || [],`
- Change `gradingPsyc201: courseData.psyc201.grading,` to `gradingPsyc201: (courseMetaFor('psyc201') && courseMetaFor('psyc201').grading) || [],`
- Add these new keys (anywhere in the object; grouping near `deadlines`/`weakTopics` is cleanest):
```js
      dashboardLoading: s.dashboardLoading,
      showDashboardError: !!s.dashboardError && !s.courseMeta,
      dashboardError: s.dashboardError,
      retryDashboard: retryDashboard,
      showDashboardLoading: s.dashboardLoading && !s.courseMeta,
      cs101Summary: courseCardSummary(courseMetaFor('cs101')),
      psyc201Summary: courseCardSummary(courseMetaFor('psyc201')),
      cs101Tags: courseCardTags(courseMetaFor('cs101')),
      psyc201Tags: courseCardTags(courseMetaFor('psyc201')),
      dashboardRecentActivity: dashboardRecentActivity,
      dashboardRecentLoading: s.dashboardRecentLoading,
      dashboardRecentError: s.dashboardRecentError,
      retryDashboardRecent: retryDashboardRecent,
```

- [ ] **Step 7: Template — deadlines card always shows; "Needs practice" stays notes-gated**

In `course_copilot.html:89-129`, change the opening/closing of the outer gate and the "Needs practice" card so deadlines are ungated (cross-course, shown regardless of the selected course's notes status) while "Needs practice" keeps its own gate. Change:
```html
        <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
          <div style="display:grid;grid-template-columns:1.4fr 1fr;gap:var(--space-6);margin-bottom:var(--space-6)">
            <div class="card elev-sm" style="padding:var(--space-6)">
```
to:
```html
        <div style="display:grid;grid-template-columns:1.4fr 1fr;gap:var(--space-6);margin-bottom:var(--space-6)">
            <div class="card elev-sm" style="padding:var(--space-6)">
```
(remove the `<sc-if value="{{ courseHasNotes }}">` wrapper opening, keep everything else in the deadlines card exactly as-is — it already binds to `{{ deadlines }}`, which Step 5 repointed to live data).

Then change the "Needs practice" card and the grid's closing tag from:
```html
            <div class="card elev-sm" style="padding:var(--space-6);background:var(--color-accent-100);border-color:var(--color-accent-200)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-3)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-800)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                  <div class="card-title" style="margin:0;color:var(--color-accent-900,var(--color-accent-800))">Needs practice</div>
              </div>
              <p style="font-size:13px;opacity:.75;margin:0 0 var(--space-4)">Based on your quiz history in CS101.</p>
              <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:var(--space-4)">
                <sc-for list="{{ weakTopics }}" as="t" hint-placeholder-count="2">
                  <div>
                    <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px"><span style="font-weight:600">{{ t.topic }}</span><span style="opacity:.65">{{ t.pct }}%</span></div>
                    <div style="height:6px;border-radius:99px;background:var(--color-accent-200)"><div style="{{ t.barStyle }}"></div></div>
                  </div>
                </sc-for>
              </div>
              <button type="button" class="btn btn-primary btn-block" onClick="{{ practiceWeak }}">Practice weak topics</button>
            </div>
          </div>
        </sc-if>
```
to:
```html
            <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
              <div class="card elev-sm" style="padding:var(--space-6);background:var(--color-accent-100);border-color:var(--color-accent-200)">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-3)">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-800)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                    <div class="card-title" style="margin:0;color:var(--color-accent-900,var(--color-accent-800))">Needs practice</div>
                </div>
                <p style="font-size:13px;opacity:.75;margin:0 0 var(--space-4)">Based on your quiz history in {{ courseIdUpper }}.</p>
                <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:var(--space-4)">
                  <sc-for list="{{ weakTopics }}" as="t" hint-placeholder-count="2">
                    <div>
                      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px"><span style="font-weight:600">{{ t.topic }}</span><span style="opacity:.65">{{ t.pct }}%</span></div>
                      <div style="height:6px;border-radius:99px;background:var(--color-accent-200)"><div style="{{ t.barStyle }}"></div></div>
                    </div>
                  </sc-for>
                </div>
                <button type="button" class="btn btn-primary btn-block" onClick="{{ practiceWeak }}">Practice weak topics</button>
              </div>
            </sc-if>
            <sc-if value="{{ !courseHasNotes }}" hint-placeholder-val="{{ false }}">
              <div class="card elev-sm" style="padding:var(--space-6)">
                <div class="card-kicker">{{ courseIdUpper }}</div>
                <div class="card-title">{{ courseName }}</div>
                <p class="card-body" style="font-size:13px">Add notes to {{ courseName }} to get weak-topic recommendations here.</p>
              </div>
            </sc-if>
        </div>
```

Now add loading/error handling around the whole grid — wrap the grid (the `<div style="display:grid;...">...</div>` block just changed) with:
```html
        <sc-if value="{{ showDashboardLoading }}" hint-placeholder-val="{{ false }}">
          <div class="card elev-sm" style="padding:var(--space-6);text-align:center;opacity:.7;margin-bottom:var(--space-6)">
            Loading dashboard…
          </div>
        </sc-if>
        <sc-if value="{{ showDashboardError }}" hint-placeholder-val="{{ false }}">
          <div class="card elev-sm" style="padding:var(--space-6);margin-bottom:var(--space-6)">
            <p class="card-body" style="margin:0 0 var(--space-4)">{{ dashboardError }}</p>
            <button type="button" class="btn btn-secondary" onClick="{{ retryDashboard }}">Try again</button>
          </div>
        </sc-if>
```
placed immediately before the grid `<div>`, so the full sequence in the file reads: loading card → error card → the deadlines/needs-practice grid (all three are independent siblings — `showDashboardLoading` and `showDashboardError` are mutually exclusive with each other and, once `courseMeta` is populated, both become false and the real grid shows; a background refetch after that point never re-triggers the loading takeover, matching the `showDashboardLoading`/`showDashboardError` definitions from Step 6, which only fire before the first successful load).

- [ ] **Step 8: Template — course-cards grid uses live `courseMeta`**

In `course_copilot.html:143-173`, change:
```html
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">CS101</div>
            <div class="card-title">Intro to Computer Science</div>
            <p class="card-body">7 topics · 2 quizzed · midterm Oct 14</p>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <span class="tag tag-accent">Recursion — developing</span>
              <span class="tag tag-accent">Sorting — developing</span>
            </div>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ gradingCs101 }}" as="g" hint-placeholder-count="4">
                <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
              </sc-for>
            </div>
          </div>
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">PSYC201</div>
            <div class="card-title">Cognitive Psychology</div>
            <p class="card-body">Syllabus added — no lecture notes uploaded yet.</p>
            <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
              Upload notes
            </button>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ gradingPsyc201 }}" as="g" hint-placeholder-count="4">
                <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
              </sc-for>
            </div>
          </div>
```
to:
```html
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">CS101</div>
            <div class="card-title">Intro to Computer Science</div>
            <p class="card-body">{{ cs101Summary }}</p>
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
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">PSYC201</div>
            <div class="card-title">Cognitive Psychology</div>
            <p class="card-body">{{ psyc201Summary }}</p>
            <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)">
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
```

- [ ] **Step 9: Template — recent-activity list uses live data + its own loading/error state**

In `course_copilot.html:175-186`, change:
```html
        <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
          <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.55;margin-bottom:var(--space-3)">Recent quiz activity</div>
          <div class="card elev-sm" style="padding:0;overflow:hidden">
            <sc-for list="{{ recentAttempts }}" as="a" hint-placeholder-count="4">
              <div style="display:flex;align-items:center;gap:var(--space-3);padding:12px var(--space-6);border-bottom:1px solid var(--color-neutral-200)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{{ a.iconColor }}" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><sc-if value="{{ a.correct }}" hint-placeholder-val="{{ true }}"><path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/></sc-if><sc-if value="{{ a.incorrect }}" hint-placeholder-val="{{ false }}"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></sc-if></svg>
                <div style="flex:1;min-width:0;font-size:13.5px">{{ a.question }}</div>
                <span class="tag tag-neutral">{{ a.topic }}</span>
              </div>
            </sc-for>
          </div>
        </sc-if>
```
to:
```html
        <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
          <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.55;margin-bottom:var(--space-3)">Recent quiz activity</div>
          <sc-if value="{{ dashboardRecentLoading }}" hint-placeholder-val="{{ false }}">
            <div style="font-size:13px;opacity:.6;padding:12px 0">Loading…</div>
          </sc-if>
          <sc-if value="{{ dashboardRecentError }}" hint-placeholder-val="{{ false }}">
            <div style="font-size:13px;padding:12px 0;display:flex;align-items:center;gap:10px">
              <span style="opacity:.7">{{ dashboardRecentError }}</span>
              <button type="button" class="btn btn-secondary" onClick="{{ retryDashboardRecent }}">Try again</button>
            </div>
          </sc-if>
          <sc-if value="{{ !dashboardRecentLoading }}" hint-placeholder-val="{{ true }}">
            <div class="card elev-sm" style="padding:0;overflow:hidden">
              <sc-for list="{{ dashboardRecentActivity }}" as="a" hint-placeholder-count="4">
                <div style="display:flex;align-items:center;gap:var(--space-3);padding:12px var(--space-6);border-bottom:1px solid var(--color-neutral-200)">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{{ a.iconColor }}" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><sc-if value="{{ a.correct }}" hint-placeholder-val="{{ true }}"><path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/></sc-if><sc-if value="{{ a.incorrect }}" hint-placeholder-val="{{ false }}"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></sc-if></svg>
                  <div style="flex:1;min-width:0;font-size:13.5px">{{ a.question }}</div>
                  <span class="tag tag-neutral">{{ a.topic }}</span>
                </div>
              </sc-for>
            </div>
          </sc-if>
        </sc-if>
```
(The `!dashboardRecentLoading` wrapper around the list means the list still shows during an error too — acceptable since an error only replaces the loading spinner, and the list will simply be whatever was last successfully loaded, or empty on first load. This mirrors the "don't hide stale data behind a hard error" choice already made for the top-level dashboard in Step 7.)

- [ ] **Step 10: `manage.py check` sanity pass**

Run: `venv/Scripts/python.exe manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 11: Full regression suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all passing, same count as after Task 2 (this task touches no Python)

- [ ] **Step 12: Live browser verification (uses the `run` skill or Playwright)**

Start the app (`manage.py runserver`, given the ASGI static-file fix from the prior pass — either entrypoint now serves static assets correctly), then in a browser:
1. Load `/` fresh (don't click into Quiz first). Confirm Dashboard shows real CS101 deadlines, real weak-topics bars, and both course cards with live topic/quizzed counts and grading — confirms `componentDidMount()` fired.
2. Switch to Quiz directly from this fresh load (without having visited Dashboard's data first — it already loaded via `componentDidMount`, but confirm Quiz's empty-state gating still correctly reflects real `has_notes`, not a stale/default value).
3. Switch to PSYC201 on Dashboard. Confirm its course card shows real topic count and grading from its actual `syllabus.json`, "Needs practice" is replaced by the shorter no-notes message, and "Recent quiz activity" doesn't render (no notes → `courseHasNotes` false).
4. Take a full 3-question CS101 quiz round via the Quiz tab, then return to Dashboard. Confirm weak-topics bars, the CS101 course card's quizzed-count, and "Recent quiz activity" all reflect the just-completed round without a page reload.
5. Check the browser console for errors throughout.

- [ ] **Step 13: Commit**

```bash
git add agent/templates/agent/course_copilot.html
git commit -m "Wire Dashboard tab to live /api/dashboard/ and quiz/history/ endpoints"
```

---

## Explicitly out of scope (per spec, do not implement here)

- Progress and Chat tabs — later passes. Progress's own "Mastery by topic" and "Recent attempts" cards stay on `allTopicsRaw`/`attemptsRaw` mock data even though the underlying real data (`mastery.weak_topics`, `quiz.recent_attempts`) now exists.
- Dynamic course discovery / a course-listing endpoint — sidebar and `courseMeta` lookups stay hardcoded to `cs101`/`psyc201`.
- A CLI management command for `recent_attempts()` — not requested.
