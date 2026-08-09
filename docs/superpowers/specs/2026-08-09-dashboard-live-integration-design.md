# Dashboard live integration — design

## Context

`agent/templates/agent/course_copilot.html` has four tabs. Quiz was wired to real backend data in a prior pass (`docs/superpowers/specs/2026-08-09-quiz-live-integration-design.md`); Dashboard, Progress, and Chat still run entirely on hardcoded mock data in `renderVals()`'s `courseData` object (`course_copilot.html:492-539`).

This pass wires up **Dashboard only**. Progress and Chat stay mock and are separate future passes.

Dashboard has four pieces today, all reading from `courseData[s.course]` (`cd`, `course_copilot.html:540`) except the course-cards grid, which reads `courseData.cs101`/`courseData.psyc201` directly regardless of the selected course:

1. **Upcoming deadlines** card (`courseHasNotes` block, `course_copilot.html:89-128`) — `cd.deadlinesRaw`, course-scoped in the mock even though each entry already carries a `course` field as if meant to span courses.
2. **Needs practice / weak topics** card (same block) — `cd.weakTopics`, course-scoped.
3. **Your courses** grid (`course_copilot.html:143-173`) — two manually-written cards, NOT scoped to `s.course`, showing both CS101 and PSYC201's topic count, quizzed count, next deadline, grading, and status tags simultaneously.
4. **Recent quiz activity** list (`course_copilot.html:175-186`) — `cd.attemptsRaw`, course-scoped. The same underlying prop (`recentAttempts`) is also read by Progress's own "Recent attempts" card (`course_copilot.html:239-251`) — see "Explicitly out of scope" for why this pass does not make Progress's copy live too.

Also: `courseHasNotes` (`course_copilot.html:541`) is currently `cd.hasNotes`, a mock boolean that happens to match reality (CS101 true, PSYC201 false) by coincidence of the sample data. It gates empty-state UI across Quiz, Chat, and Progress, not just Dashboard.

## What changes and why

**Two small new backend endpoints**, both pure compositions of already-existing service functions — no new business logic:

- `GET /api/dashboard/` — a cross-course aggregate (deadlines + per-course summary stats), because the "Your courses" grid needs data for every course simultaneously, not just the selected one. A dedicated aggregate avoids an N-call fan-out from the frontend and mirrors the cross-course aggregation `agent/services/reminders.py` already does.
- `GET /api/courses/<id>/quiz/history/?limit=10` — recent attempts for one course, reusing `storage.read_quiz_history()`. Kept separate from the aggregate endpoint (rather than folded into it) because it's genuinely course-scoped, general-purpose, and will be reused by the future Progress pass.

**`courseHasNotes` becomes genuinely live everywhere**, not just on Dashboard. A `componentDidMount()` hook (the DC runtime supports this — confirmed in `agent/static/agent/support.js:831,993`) fetches `/api/dashboard/` once when the app first loads, so Quiz/Chat/Progress's existing empty-state gating reads real data even if the user never visits the Dashboard tab first. This touches already-shipped Quiz code (`course_copilot.html:541`, `548`, `558`) but replaces a coincidental mock value with the real signal it was always standing in for.

## Design

### 1. `agent/services/dashboard.py` (new)

```python
def build_dashboard() -> dict:
    """Cross-course summary for the Dashboard tab: global upcoming deadlines
    plus, per course, everything the "Your courses" grid needs. Pure
    composition of existing reads — no new storage format, nothing written."""
```

Composes, per course from `reminders.list_courses()`:
- `course_name` — `syllabus["course_name"]`
- `has_notes` — `bool(storage.read_notes(course_id))`
- `topics_count` — `len(syllabus.get("topics", []))`
- `quizzed_count` — `len(mastery.weak_topics(course_id))` (mastery only contains topics with ≥1 attempt, so this is exactly "how many topics have been quizzed")
- `next_deadline` — first entry of `reminders.upcoming_deadlines(within_days=None, course_ids=[course_id])`, or `None`. Deliberately **uncapped**, unlike the top-level `deadlines` list below — a midterm 2 months out must still show as "next deadline" on its own course card even though it's outside the digest's 14-day window.
- `grading` — `syllabus["grading"]`
- `weak_topics` — `mastery.weak_topics(course_id)` (`[]` if `mastery_scores.json` doesn't exist yet — this is the normal PSYC201 state, not an error; `weak_topics()` already handles this per `agent/services/mastery.py:69-72`)

Top-level `deadlines` — `reminders.upcoming_deadlines(within_days=14)` (matches `reminders.py`'s own default window, this is the "what's coming up soon" digest, separate purpose from each course's own `next_deadline`).

**Per-course failure isolation:** if `read_syllabus`/`weak_topics` raises for one course (e.g. a corrupt `syllabus.json`), that course's entry gets `{"error": "..."}` instead of failing the whole response — one bad course shouldn't take down every other course's dashboard.

### 2. `DashboardView` (new, `agent/views.py`)

```
GET /api/dashboard/ → 200 with the shape above. No params, no auth beyond what already exists.
```

Async view, `await sync_to_async(dashboard.build_dashboard)()`, same pattern as `MasteryView`/`RemindersView`. Added to `agent/urls.py` at the top level (alongside `reminders/`, not nested under `courses/<id>/`, since it's cross-course).

### 3. `quiz.recent_attempts()` (new function, `agent/services/quiz.py`)

```python
def recent_attempts(course_id: str, limit: int = 10) -> list:
    """Most recent quiz attempts for this course, newest first."""
```

Reuses `storage.read_quiz_history(course_id)`, reverse-sorts by `timestamp`, slices to `limit`.

### 4. `QuizHistoryView` (new, `agent/views.py`)

```
GET /api/courses/<id>/quiz/history/?limit=<int, default 10> → 200 {"attempts": [...]}
```

Same error handling pattern as `QuizGenerateView` (404/`InvalidCourseIdError` → 400). Added to `agent/urls.py` alongside the other `courses/<id>/quiz/...` routes.

### 5. Component state (`course_copilot.html`, `Component` class)

Add:
```js
courseMeta: null,          // { cs101: {...}, psyc201: {...} } from /api/dashboard/, or null before first load
dashboardDeadlines: [],    // top-level deadlines list from the same payload
dashboardLoading: false,
dashboardError: null,
dashboardRecentAttempts: [],   // from /api/courses/<id>/quiz/history/, selected-course only
dashboardRecentLoading: false,
dashboardRecentError: null,
```

`courseHasNotes` (`course_copilot.html:541`) changes from `cd.hasNotes` to `(s.courseMeta && s.courseMeta[s.course] && s.courseMeta[s.course].has_notes) || false` — `false` while `courseMeta` hasn't loaded yet (matches today's momentary-mock-read behavior; the fetch is fast and has no LLM cost, so this window is brief).

### 6. `componentDidMount()` (new method)

```js
componentDidMount() {
  this.loadDashboard();
}
```

### 7. `loadDashboard()` (new method)

```js
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
```

Called from `componentDidMount()` (once, on app load) and again from `goDashboard` (every time the Dashboard tab is entered, for freshness after quizzing elsewhere) — both routing through the same method, no duplicated fetch logic.

### 8. `loadDashboardRecent(courseId)` (new method)

Same shape as `loadDashboard()`, hitting `/api/courses/${courseId}/quiz/history/?limit=4` (4 to match the mock's existing placeholder count), populating `dashboardRecentAttempts`/`dashboardRecentLoading`/`dashboardRecentError`. Called when the Dashboard tab is entered and when the course chip is switched while already on Dashboard — mirrors Quiz's existing `setTab`/`selectCourse` pattern (`course_copilot.html:544-562`).

### 9. Template changes

- Deadlines card: iterate `{{ dashboardDeadlines }}` instead of `{{ deadlines }}` (mock-derived from `cd.deadlinesRaw`); each entry already carries `course_id` from the API, template adds a course-name/label lookup the same way `typeStyle`/`typeLabel` are computed today.
- Weak-topics card: `{{ dashboardWeakTopics }}`, derived as `(s.courseMeta && s.courseMeta[s.course] && s.courseMeta[s.course].weak_topics) || []`, mapped through the same `pct`/`barStyle` shaping the mock's `weakTopics` already used.
- Course-cards grid: keeps its current two-block structure (still just cs101/psyc201 — no dynamic course list, per the existing hardcoded sidebar). Each block reads from `s.courseMeta.cs101`/`s.courseMeta.psyc201` instead of the mock `courseData.cs101`/`courseData.psyc201`.
- Recent-activity list: `{{ dashboardRecentAttempts }}` (new prop, deliberately not reusing `recentAttempts` — see "Explicitly out of scope").
- New loading/error states for the Dashboard tab as a whole (`dashboardLoading`/`dashboardError`) and for the recent-activity sub-widget (`dashboardRecentLoading`/`dashboardRecentError`), same lightweight-card + retry pattern Quiz already established (`course_copilot.html:295-306` in the current file, for the loading/error cards).

## Explicitly out of scope for this pass

- **Progress and Chat tabs** stay entirely on mock data — separate future passes.
- **Progress's own "Recent attempts" card and "Mastery by topic" list** (`course_copilot.html:224-251`, both reading `allTopics`/`recentAttempts`) are NOT wired in this pass, even though `quiz/history/` and `mastery/` now technically provide the data — Dashboard's recent-activity widget gets its own distinct prop (`dashboardRecentAttempts`) specifically to avoid entangling the two passes.
- **Dynamic course discovery.** The sidebar and `courseMeta` lookups stay hardcoded to `cs101`/`psyc201`; `/api/dashboard/` returns whatever `reminders.list_courses()` finds (matching that function's existing default behavior), but the frontend only reads the two keys it already knows about.
- **A CLI command for `recent_attempts()`.** Not requested; nothing in the existing CLI surface needs it.

## Verification

- `python manage.py check` after the new views/urls.
- `pytest` — new tests for `dashboard.build_dashboard()` (composition logic, per-course failure isolation) and `quiz.recent_attempts()` (ordering, `limit`), plus the two new views' happy-path/error responses.
- Live browser check: Dashboard shows real CS101 deadlines/weak-topics/course-card stats and PSYC201's genuinely-empty state (0 topics quizzed, "no notes" card, but real topic count/grading from its actual syllabus); switching to Quiz directly (without visiting Dashboard first) still correctly gates on real `has_notes` via `componentDidMount()`; taking a quiz round and returning to Dashboard shows updated weak-topics/quizzed-count/recent-activity without a page reload.
