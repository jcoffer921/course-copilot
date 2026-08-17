# Progress Tab Real Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Progress tab's hardcoded/fake content (three stat tiles, "Mastery by topic," "Recent attempts") with real backend data, and add a real, backend-computed global study streak.

**Architecture:** Three sequential tasks, backend-to-frontend: (1) a new `agent/services/streak.py` computing a global (cross-course) consecutive-day streak from every course's `quiz_history.json`; (2) extending `agent/services/dashboard.py`'s existing `_course_summary()`/`build_dashboard()` to add a per-course `topics` field (full syllabus topic list merged with mastery status) and a top-level `streak` field; (3) rewiring `agent/templates/agent/ontrack.html`'s Progress tab JS to consume this real data instead of its hardcoded `courseData` mock, plus six template bindings that are currently literal text.

**Tech Stack:** Django (sync service functions, async DRF view unchanged), pytest (pytest-django), vanilla JS in a Django template (`{% verbatim %}`-wrapped DC pseudo-component app, no build step).

## Global Constraints

- Every number the Progress tab shows must come from real data — no hardcoded/fabricated values remain anywhere in this tab.
- Study streak is **global across all courses** (not per-course): studying any course on a given day keeps it alive. This was an explicit product decision, not an oversight.
- Streak semantics: consecutive UTC calendar days with ≥1 quiz attempt anywhere, counted backward from today; if today has no activity yet but yesterday does, the streak is still "alive" (counts backward from yesterday) rather than resetting to 0 the instant today has no entry — it only breaks after a full day passes with zero activity anywhere.
- Quiz accuracy is computed from the same recent-attempts sample already shown in "Recent attempts" (the existing `?limit=4`-per-course fetch) — not a separate full-history query. This matches what the tab's original mock already implied ("2 of 4").
- **Correction to the design spec:** the spec assumed the Progress tab might need "All courses" aggregation for its stat tiles/mastery list. It doesn't — `selectCourse('all')` while on the Progress tab already bounces to the Dashboard tab (`agent/templates/agent/ontrack.html`, existing line ~875, unchanged by this plan), so the Progress tab is always scoped to one concrete course. Only the streak is inherently cross-course, by design.
- No visual/layout redesign — this pass is data-correctness only. Every element that's already a `{{ }}` binding keeps its existing markup structure; only its data source changes.
- No new `/api/progress/` endpoint — reuse the existing `GET /api/dashboard/` and `GET /api/courses/<id>/quiz/history/` endpoints.
- Do not change `mastery.py`'s EWMA scoring, `quiz.py`'s question generation, or the Quiz tab.

---

### Task 1: Global study streak — `agent/services/streak.py`

**Files:**
- Create: `agent/services/streak.py`
- Test: `agent/tests/test_streak.py`

**Interfaces:**
- Consumes: `reminders.list_courses() -> list[str]` (existing, `agent/services/reminders.py:14`), `storage.read_quiz_history(course_id: str) -> dict` (existing, `agent/services/storage.py:424`, returns `{"course_id": str, "attempts": list}`), `storage.QuizStorageError` (existing exception, raised when an existing `quiz_history.json` is corrupt).
- Produces: `current_streak() -> int` — zero-argument, cross-course. Task 2 imports and calls this.

- [ ] **Step 1: Write the failing tests**

Create `agent/tests/test_streak.py`:

```python
from datetime import date, timedelta

import pytest

from agent.services import storage, streak


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    """Redirects storage.COURSES_DIR to a throwaway tmp_path so these tests
    never touch real course data."""
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


def _seed_syllabus(course_id):
    """current_streak() only scans courses reminders.list_courses() finds,
    which requires a syllabus.json to exist — a course with quiz attempts
    but no syllabus can't happen in practice (quizzing requires chunked
    notes, which requires a syllabus first), but streak.py still needs a
    real syllabus.json on disk for the course to be discovered at all."""
    storage.write_syllabus(course_id, {
        "course_id": course_id, "course_name": course_id.upper(),
        "dates": [], "grading": [], "topics": [],
    })


def _attempt_at(d, topic="X", correct=True):
    return {"topic": topic, "correct": correct, "timestamp": d.isoformat() + "T12:00:00+00:00"}


def test_streak_zero_with_no_attempts_anywhere(isolated_courses_dir):
    _seed_syllabus("cs101")

    assert streak.current_streak() == 0


def test_streak_counts_consecutive_days_across_courses(isolated_courses_dir):
    today = date.today()
    _seed_syllabus("cs101")
    _seed_syllabus("psyc201")
    storage.append_quiz_attempt("cs101", _attempt_at(today))
    storage.append_quiz_attempt("psyc201", _attempt_at(today - timedelta(days=1)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))

    assert streak.current_streak() == 3


def test_streak_alive_with_activity_yesterday_but_not_today(isolated_courses_dir):
    today = date.today()
    _seed_syllabus("cs101")
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=1)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))

    assert streak.current_streak() == 2


def test_streak_breaks_after_full_day_gap(isolated_courses_dir):
    today = date.today()
    _seed_syllabus("cs101")
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=2)))
    storage.append_quiz_attempt("cs101", _attempt_at(today - timedelta(days=3)))

    assert streak.current_streak() == 0


def test_streak_ignores_a_course_with_corrupt_quiz_history(isolated_courses_dir, tmp_path):
    today = date.today()
    _seed_syllabus("cs101")
    _seed_syllabus("badcourse")
    storage.append_quiz_attempt("cs101", _attempt_at(today))
    (tmp_path / "badcourse" / "quiz_history.json").write_text("{not valid json", encoding="utf-8")

    assert streak.current_streak() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest agent/tests/test_streak.py -v`
Expected: `ModuleNotFoundError` or `ImportError` for `agent.services.streak` — the module doesn't exist yet.

- [ ] **Step 3: Implement `agent/services/streak.py`**

```python
"""
Global (cross-course) study streak: consecutive UTC calendar days with at
least one quiz attempt logged anywhere. Read-only, no writes — mirrors
reminders.py's cross-course scanning style. Deliberately global rather than
per-course: studying any course on a given day keeps the streak alive.
"""

from datetime import date, datetime, timedelta

from . import reminders, storage


def _attempt_dates(course_id: str) -> set:
    """Returns the set of UTC calendar dates this course has at least one
    quiz attempt on. A corrupt quiz_history.json contributes no dates rather
    than failing the whole streak computation — matches build_dashboard()'s
    per-course isolation contract in dashboard.py."""
    try:
        history = storage.read_quiz_history(course_id)
    except storage.QuizStorageError:
        return set()

    dates = set()
    for attempt in history.get("attempts", []):
        timestamp = attempt.get("timestamp")
        if not timestamp:
            continue
        try:
            dates.add(datetime.fromisoformat(timestamp).date())
        except ValueError:
            continue
    return dates


def current_streak() -> int:
    """Consecutive calendar days, across ALL courses combined, with at least
    one quiz attempt. Counts backward from today if today has activity, or
    from yesterday if today doesn't (yet) but yesterday does — the streak
    stays alive until a full day passes with zero activity anywhere, rather
    than resetting the instant today has no entry yet. 0 if neither today
    nor yesterday has any activity, including a brand-new install."""
    all_dates = set()
    for course_id in reminders.list_courses():
        all_dates |= _attempt_dates(course_id)

    today = date.today()
    if today in all_dates:
        cursor = today
    elif (today - timedelta(days=1)) in all_dates:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak_length = 0
    while cursor in all_dates:
        streak_length += 1
        cursor -= timedelta(days=1)
    return streak_length
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest agent/tests/test_streak.py -v`
Expected: all 5 tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add agent/services/streak.py agent/tests/test_streak.py
git commit -m "feat: add global study streak service"
```

---

### Task 2: Wire streak + full topic list into `dashboard.py`

**Files:**
- Modify: `agent/services/dashboard.py`
- Test: `agent/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `streak.current_streak() -> int` (Task 1). Existing `mastery.weak_topics(course_id) -> list[dict]` (each dict has `"topic"`, `"score"`, `"status"`, plus `"attempts"`/`"last_seen"` this task doesn't use). Existing `storage.read_syllabus(course_id) -> dict | None` (has a `"topics": list[str]` field).
- Produces: `build_dashboard() -> dict` gains a new top-level `"streak": int` key. Each entry in `build_dashboard()["courses"]` (via `_course_summary()`) gains a new `"topics"` key: `list[{"topic": str, "score": float | None, "status": str}]`, one entry per syllabus topic, in syllabus order, `status: "unassessed"`/`score: None` for any topic `mastery.weak_topics()` hasn't scored yet. Task 3 (the template) consumes both.

- [ ] **Step 1: Write the failing tests**

In `agent/tests/test_dashboard.py`, extend `test_build_dashboard_composes_course_data` to also assert the new `topics` field, and add one new test for the all-unassessed case and one for the top-level `streak` field:

```python
def test_build_dashboard_composes_course_data(isolated_courses_dir):
    _seed_course(
        "cs101", topics=["A", "B", "C"],
        grading=[{"component": "HW", "weight_pct": 100}],
        dates=[{"date": "2026-08-10", "title": "Quiz 1", "type": "assignment"}],
        notes_count=1,
    )
    storage.append_quiz_attempt("cs101", {"topic": "A", "correct": True, "timestamp": "2026-01-01T00:00:00"})
    mastery.rebuild_scores("cs101")

    data = dashboard.build_dashboard()

    course = data["courses"]["cs101"]
    assert course["course_name"] == "CS101"
    assert course["notes_count"] == 1
    assert course["topics_count"] == 3
    assert course["quizzed_count"] == 1
    assert course["grading"] == [{"component": "HW", "weight_pct": 100}]
    assert [t["topic"] for t in course["weak_topics"]] == ["A"]
    assert course["topics"] == [
        {"topic": "A", "score": pytest.approx(0.65), "status": "developing"},
        {"topic": "B", "score": None, "status": "unassessed"},
        {"topic": "C", "score": None, "status": "unassessed"},
    ]


def test_build_dashboard_topics_all_unassessed_without_quiz_history(isolated_courses_dir):
    _seed_course("psyc201", topics=["X", "Y"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["courses"]["psyc201"]["topics"] == [
        {"topic": "X", "score": None, "status": "unassessed"},
        {"topic": "Y", "score": None, "status": "unassessed"},
    ]


def test_build_dashboard_includes_streak(isolated_courses_dir):
    _seed_course("cs101", topics=["A"], grading=[], dates=[])

    data = dashboard.build_dashboard()

    assert data["streak"] == 0
```

Note: `pytest.approx(0.65)` matches `test_mastery.py`'s existing hand-verified EWMA math (ALPHA=0.3, NEUTRAL_SCORE=0.5, one correct attempt: `0.3*1 + 0.7*0.5 = 0.65`), and `_status_for_score(0.65)` is `"developing"` since it's `>= WEAK_THRESHOLD (0.4)` and `< STRONG_THRESHOLD (0.7)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest agent/tests/test_dashboard.py -v`
Expected: `test_build_dashboard_composes_course_data` fails with `KeyError: 'topics'`; the two new tests fail the same way (or `KeyError: 'streak'` for the streak test).

- [ ] **Step 3: Implement the `dashboard.py` changes**

Replace the full contents of `agent/services/dashboard.py`:

```python
"""
Cross-course summary for the Dashboard tab: global upcoming deadlines plus,
per course, everything the "Your courses" grid needs. Pure composition of
existing reads — no new storage format, nothing written.
"""

from . import mastery, reminders, storage, streak


def _merge_topics(syllabus_topics: list, weak_topics: list) -> list:
    """Every topic from the syllabus, in syllabus order, tagged with its
    mastery status. A topic mastery.weak_topics() hasn't scored yet (never
    quizzed) gets score=None, status="unassessed" rather than being omitted —
    the Progress tab's "Mastery by topic" list needs every syllabus topic
    represented, not just the ones with quiz history."""
    scores_by_topic = {t["topic"]: t for t in weak_topics}
    return [
        {
            "topic": topic,
            "score": scores_by_topic[topic]["score"] if topic in scores_by_topic else None,
            "status": scores_by_topic[topic]["status"] if topic in scores_by_topic else "unassessed",
        }
        for topic in syllabus_topics
    ]


def _course_summary(course_id: str) -> dict:
    syllabus = storage.read_syllabus(course_id)
    weak_topics = mastery.weak_topics(course_id)
    upcoming = reminders.upcoming_deadlines(within_days=None, course_ids=[course_id])
    syllabus_topics = syllabus.get("topics", [])

    return {
        "course_name": syllabus.get("course_name", course_id),
        "notes_count": len(storage.read_notes(course_id)),
        "topics_count": len(syllabus_topics),
        "quizzed_count": len(weak_topics),
        "next_deadline": upcoming[0] if upcoming else None,
        "grading": syllabus.get("grading", []),
        "weak_topics": weak_topics,
        "topics": _merge_topics(syllabus_topics, weak_topics),
    }


def build_dashboard() -> dict:
    """Never raises — a corrupt course's data is isolated to
    {"error": "..."} in its own slot rather than failing every other
    course's dashboard data along with it."""
    courses = {}
    good_course_ids = []
    for course_id in reminders.list_courses():
        try:
            courses[course_id] = _course_summary(course_id)
            good_course_ids.append(course_id)
        except (storage.SyllabusStorageError, storage.QuizStorageError) as e:
            courses[course_id] = {"error": str(e)}

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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest agent/tests/test_dashboard.py -v`
Expected: all tests `PASS`, including the pre-existing ones (`test_build_dashboard_course_without_notes_or_mastery`, `test_build_dashboard_next_deadline_uncapped_but_top_level_deadlines_windowed`, `test_build_dashboard_isolates_corrupt_course`, `test_build_dashboard_notes_count_reflects_multiple_lectures`) — none of their existing assertions reference `topics` or `streak`, so they still pass unmodified against the new response shape.

- [ ] **Step 5: Run the full backend test suite to confirm no regression**

Run: `pytest agent/tests/ -v`
Expected: all tests `PASS` or `SKIPPED` (live-API tests skip without `ANTHROPIC_API_KEY`) — in particular `agent/tests/test_views.py`'s dashboard-related tests, if any, still pass against the grown response shape.

- [ ] **Step 6: Commit**

```bash
git add agent/services/dashboard.py agent/tests/test_dashboard.py
git commit -m "feat: add real topic mastery list and streak to dashboard data"
```

---

### Task 3: Wire the Progress tab template to real data

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET /api/dashboard/`'s response, now including `data.streak: int` and `data.courses[id].topics: list[{"topic", "score", "status"}]` (Task 2). Existing `GET /api/courses/<id>/quiz/history/?limit=N` response (unchanged), already fetched via the existing `loadDashboardRecent(courseId)` method.
- Produces: no new interfaces for other tasks — this is the leaf consumer.

- [ ] **Step 1: Add `dashboardStreak` to component state**

In `agent/templates/agent/ontrack.html`, find the `state = { ... }` block (currently around line 526-536):

```javascript
  state = {
    tab: 'dashboard', course: 'all',
    courseMeta: null, dashboardDeadlines: [], dashboardLoading: false, dashboardError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
```

Change the second line to add `dashboardStreak: 0`:

```javascript
  state = {
    tab: 'dashboard', course: 'all',
    courseMeta: null, dashboardDeadlines: [], dashboardStreak: 0, dashboardLoading: false, dashboardError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
```

- [ ] **Step 2: Capture `streak` in `loadDashboard()`**

Find `loadDashboard()` (currently around line 570-584):

```javascript
  loadDashboard() {
    const seq = ++this._dashSeq;
    this.setState({ dashboardLoading: true, dashboardError: null });
    fetch('/api/dashboard/')
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._dashSeq) return;
        if (!ok) { this.setState({ dashboardLoading: false, dashboardError: data.detail || 'Could not load dashboard data.' }); return; }
        this.setState({ dashboardLoading: false, courseMeta: data.courses, dashboardDeadlines: data.deadlines });
      })
```

Change the success line to also capture `data.streak`:

```javascript
        this.setState({ dashboardLoading: false, courseMeta: data.courses, dashboardDeadlines: data.deadlines, dashboardStreak: data.streak });
```

- [ ] **Step 3: Load recent attempts when entering the Progress tab or switching courses on it**

Find `setTab` (currently around line 847-869):

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
      const targetCourse = s.course === 'all' ? FALLBACK_COURSE : s.course;
      if (t === 'quiz') {
        goToQuiz(targetCourse);
      } else if (t === 'chat') {
        if (targetCourse !== s.course) {
          this.setState({ tab: t, course: targetCourse, chatMessages: [], chatInput: '', chatError: null, chatSessionId: null });
        } else {
          this.setState({ tab: t });
        }
        this.loadChatSessions(targetCourse);
      } else {
        this.setState({ tab: t, course: targetCourse });
      }
    };
```

Add a `progress` branch before the final `else`:

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
      const targetCourse = s.course === 'all' ? FALLBACK_COURSE : s.course;
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
        this.loadDashboardRecent(targetCourse);
      } else {
        this.setState({ tab: t, course: targetCourse });
      }
    };
```

Find `selectCourse` (currently around line 871-894):

```javascript
    const selectCourse = (courseId) => {
      this._quizSeq++;
      this._chatSeq++;
      if (courseId === 'all') {
        const bounce = s.tab === 'quiz' || s.tab === 'progress' || s.tab === 'chat';
        this.setState(bounce ? { course: 'all', tab: 'dashboard' } : { course: 'all' });
        if (bounce) this.loadDashboard();
        this.loadDashboardRecent('all');
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
      } else {
        this.setState({ course: courseId });
      }
    };
```

Add a `progress` branch before the final `else`:

```javascript
    const selectCourse = (courseId) => {
      this._quizSeq++;
      this._chatSeq++;
      if (courseId === 'all') {
        const bounce = s.tab === 'quiz' || s.tab === 'progress' || s.tab === 'chat';
        this.setState(bounce ? { course: 'all', tab: 'dashboard' } : { course: 'all' });
        if (bounce) this.loadDashboard();
        this.loadDashboardRecent('all');
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
      } else {
        this.setState({ course: courseId });
      }
    };
```

- [ ] **Step 4: Remove the hardcoded `courseData` mock and derive `allTopics` from real data**

Find (currently around line 806-829):

```javascript
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
    const cd = courseData[s.course] || { allTopicsRaw: [], attemptsRaw: [] };
    const anyCourseHasNotes = COURSE_IDS.some(id => courseMetaFor(id) && courseMetaFor(id).notes_count > 0);
```

Replace with:

```javascript
    const courseMetaFor = (id) => (s.courseMeta && s.courseMeta[id]) || null;
    const progressTopicsRaw = (courseMetaFor(s.course) && courseMetaFor(s.course).topics) || [];
    const anyCourseHasNotes = COURSE_IDS.some(id => courseMetaFor(id) && courseMetaFor(id).notes_count > 0);
```

- [ ] **Step 5: Point `allTopics` at real data and delete the fake `recentAttempts`**

Find (currently around line 956-969):

```javascript
    const allTopics = cd.allTopicsRaw.map(function (t) {
      var pct = t.score ? Math.round(t.score * 100) : 6;
      var color = t.score ? statusColor[t.status] : 'var(--color-neutral-300)';
      return {
        topic: t.topic,
        statusLabel: statusLabel[t.status],
        statusStyle: 'font-size:12px;font-weight:600;color:' + statusColor[t.status],
        barStyle: 'width:' + pct + '%;height:100%;border-radius:99px;background:' + color
      };
    });
    const recentAttempts = cd.attemptsRaw.map(a => Object.assign({}, a, {
      incorrect: !a.correct,
      iconColor: a.correct ? 'var(--color-accent-2-700)' : 'var(--color-accent-700)'
    }));
```

Replace with:

```javascript
    const allTopics = progressTopicsRaw.map(function (t) {
      var pct = t.score ? Math.round(t.score * 100) : 6;
      var color = t.score ? statusColor[t.status] : 'var(--color-neutral-300)';
      return {
        topic: t.topic,
        statusLabel: statusLabel[t.status],
        statusStyle: 'font-size:12px;font-weight:600;color:' + statusColor[t.status],
        barStyle: 'width:' + pct + '%;height:100%;border-radius:99px;background:' + color
      };
    });
```

(The `recentAttempts` const is deleted outright — Step 7 repoints the template's `recentAttempts` binding at the already-computed `dashboardRecentActivity`, which has the exact same shape and is fed by the real quiz-history fetch Step 3 wires up.)

- [ ] **Step 6: Compute the three stat tiles from real data**

Find `const dashboardRecentActivity = ...` (currently around line 942-946):

```javascript
    const dashboardRecentActivity = s.dashboardRecentAttempts.map(a => ({
      topic: (s.course === 'all' ? a.course_id.toUpperCase() + ' · ' : '') + a.topic,
      question: a.question, correct: a.correct, incorrect: !a.correct,
      iconColor: a.correct ? 'var(--color-accent-2-700)' : 'var(--color-accent-700)'
    }));
```

Immediately after it, add:

```javascript
    const progressMeta = courseMetaFor(s.course);
    const syllabusCoveredPct = (progressMeta && progressMeta.topics_count > 0)
      ? Math.round(100 * progressMeta.quizzed_count / progressMeta.topics_count) + '%'
      : '—';
    const syllabusCoveredLabel = progressMeta
      ? (progressMeta.quizzed_count + ' of ' + progressMeta.topics_count + ' topics quizzed')
      : 'Loading…';
    const streakLabel = s.dashboardStreak + (s.dashboardStreak === 1 ? ' day' : ' days');
    const streakSubLabel = s.dashboardStreak > 0 ? 'Keep it going' : 'Start today';
    const quizAccuracyTotal = s.dashboardRecentAttempts.length;
    const quizAccuracyCorrect = s.dashboardRecentAttempts.filter(a => a.correct).length;
    const quizAccuracyPct = quizAccuracyTotal > 0
      ? Math.round(100 * quizAccuracyCorrect / quizAccuracyTotal) + '%'
      : '—';
    const quizAccuracyLabel = quizAccuracyTotal > 0
      ? (quizAccuracyCorrect + ' of ' + quizAccuracyTotal + ' answers correct')
      : 'No attempts yet';
```

- [ ] **Step 7: Wire the new values into the returned bindings object**

Find (currently around line 1081):

```javascript
      deadlines: deadlines, weakTopics: weakTopics, allTopics: allTopics, recentAttempts: recentAttempts, mcOptions: mcOptions, quizDots: quizDots,
```

Replace with (repoints `recentAttempts` at `dashboardRecentActivity` — same shape, real data — and adds the three stat-tile bindings):

```javascript
      deadlines: deadlines, weakTopics: weakTopics, allTopics: allTopics, recentAttempts: dashboardRecentActivity, mcOptions: mcOptions, quizDots: quizDots,
      syllabusCoveredPct: syllabusCoveredPct, syllabusCoveredLabel: syllabusCoveredLabel,
      streakLabel: streakLabel, streakSubLabel: streakSubLabel,
      quizAccuracyPct: quizAccuracyPct, quizAccuracyLabel: quizAccuracyLabel,
```

- [ ] **Step 8: Replace the six hardcoded stat-tile literals with bindings**

Find (currently lines 283-309):

```html
        <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--space-4);margin-bottom:var(--space-6)">
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>
                <span style="font-size:12.5px;opacity:.65">Syllabus covered</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">29%</div>
              <div style="font-size:12px;opacity:.55">2 of 7 topics quizzed</div>
            </div>
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-2-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>
                <span style="font-size:12.5px;opacity:.65">Study streak</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">3 days</div>
              <div style="font-size:12px;opacity:.55">Keep it going</div>
            </div>
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M16 7h6v6"/><path d="m22 7-8.5 8.5-5-5L2 17"/></svg>
                <span style="font-size:12.5px;opacity:.65">Quiz accuracy</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">50%</div>
              <div style="font-size:12px;opacity:.55">2 of 4 answers correct</div>
            </div>
          </div>
```

Replace the three inner literal pairs (leave the surrounding grid/card/svg markup untouched):

```html
        <sc-if value="{{ courseHasNotes }}" hint-placeholder-val="{{ true }}">
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--space-4);margin-bottom:var(--space-6)">
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>
                <span style="font-size:12.5px;opacity:.65">Syllabus covered</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">{{ syllabusCoveredPct }}</div>
              <div style="font-size:12px;opacity:.55">{{ syllabusCoveredLabel }}</div>
            </div>
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-2-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>
                <span style="font-size:12.5px;opacity:.65">Study streak</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">{{ streakLabel }}</div>
              <div style="font-size:12px;opacity:.55">{{ streakSubLabel }}</div>
            </div>
            <div class="card elev-sm" style="padding:var(--space-6)">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-700)" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M16 7h6v6"/><path d="m22 7-8.5 8.5-5-5L2 17"/></svg>
                <span style="font-size:12.5px;opacity:.65">Quiz accuracy</span>
              </div>
              <div style="font-family:var(--font-heading);font-size:32px">{{ quizAccuracyPct }}</div>
              <div style="font-size:12px;opacity:.55">{{ quizAccuracyLabel }}</div>
            </div>
          </div>
```

- [ ] **Step 9: Manual verification against real course data**

Start the dev server (see `README.md`'s "Option B: Run the API server") and, in a separate terminal, sanity-check the API response directly:

```bash
curl -s http://127.0.0.1:8000/api/dashboard/ | python -m json.tool
```

Confirm: a top-level `"streak"` key (an integer), and `courses.cs101.topics` is a list where every entry has `"topic"`, `"score"`, `"status"` — entries matching `courses/cs101/mastery_scores.json`'s scored topics show real scores/status, every other syllabus topic shows `"score": null, "status": "unassessed"`.

Then in a browser: load `/`, open the Progress tab for `cs101` (has real quiz history on disk) — confirm the three stat tiles show real numbers matching the API response (not "29%"/"3 days"/"50%"), "Mastery by topic" lists all 7 real cs101 syllabus topics with real statuses, and "Recent attempts" shows real questions from `courses/cs101/quiz_history.json` instead of the old fake ones ("What happens without a base case?" etc. — if those exact strings still appear, confirm via the JSON that they're real logged attempts, not leftover mock text). Switch to `psyc201` (no notes/quizzes yet) and confirm the tiles show `0`/`—`/"No attempts yet" rather than blank or fake data.

- [ ] **Step 10: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: wire Progress tab to real dashboard data"
```

---

## Self-Review Notes

- **Spec coverage:** Design doc's Architecture section (3 changes) → Tasks 1-3 respectively. Stat tile computation → Task 3 Step 6/8. "Mastery by topic" new shape → Task 2 Step 3 (`_merge_topics`) + Task 3 Steps 4-5. "Recent attempts" reuse → Task 3 Steps 5/7. Streak definition/edge cases → Task 1. Corrupt-course isolation → Task 1's `_attempt_dates` try/except + its dedicated test, Task 2's existing `build_dashboard()` try/except (unchanged, still covers the new `topics` field since it's inside `_course_summary()`). Testing section → each task's Step 1/4-5. The "All courses" edge case discussion in the design doc is superseded by the Global Constraints correction above (Progress tab can't be viewed with `course === 'all'`), so no task implements course-aggregation logic for the stat tiles/mastery list — only the streak aggregates, by design.
- **Placeholder scan:** no TBD/TODO; every step shows complete code or an exact command with expected output.
- **Type consistency:** `streak.current_streak() -> int` (Task 1) is called exactly that way in `dashboard.py` (Task 2) and consumed as `data.streak` / `s.dashboardStreak` (Task 3). `_merge_topics(syllabus_topics: list, weak_topics: list) -> list` (Task 2) produces the exact `{"topic", "score", "status"}` shape Task 3's `allTopics` mapping (`t.score`, `t.status`, `t.topic`) expects — unchanged from the original mock's per-item shape, so the existing template markup's `{{ t.topic }}`/`{{ t.statusStyle }}`/`{{ t.statusLabel }}`/`{{ t.barStyle }}` bindings need no changes.
