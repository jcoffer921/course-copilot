# Progress tab — wire to real data — design

## Context

The Progress tab (`agent/templates/agent/ontrack.html`, rendered when `isProgress` is true) is the one remaining screen in OnTrack that isn't wired to the real backend, despite the Dashboard, Chat, and Quiz tabs all being fully API-driven. Specifically:

1. The three stat tiles ("Syllabus covered", "Study streak", "Quiz accuracy") are **literal hardcoded strings** in the template markup — no `{{ }}` bindings at all. They never change regardless of course or actual activity.
2. "Mastery by topic" is driven by a hand-written JS object literal (`courseData.cs101.allTopicsRaw`, `renderVals()` around line 806) with 7 fabricated topics, instead of the real `/api/courses/<id>/mastery/`-backed data (`mastery.weak_topics()`) already used correctly on the Dashboard tab.
3. "Recent attempts" is driven by another hardcoded fake list (`courseData.cs101.attemptsRaw`), even though the app already fetches real quiz history (`GET /api/courses/<id>/quiz/history/`) for the Dashboard tab's recent-activity widget — just not reused here.
4. Only `cs101` has any mock data in `courseData`; `psyc201` and any future course fall through to an empty `{allTopicsRaw: [], attemptsRaw: []}`, and "All courses" isn't handled at all.
5. There is no backend concept of a "study streak" anywhere — the "3 days" tile has nothing behind it.

This design wires the tab to real data end-to-end and adds real streak tracking, without a visual/layout redesign — the goal is correctness, not a new look.

## Goals

- Every number the Progress tab shows must be real, derived from actual course/quiz data — never fabricated or hardcoded.
- Behave correctly for any course (not just `cs101`), including a course with zero quiz activity, and for "All courses."
- Add a real, backend-computed study streak (global across all courses, not per-course).
- Reuse existing endpoints and services wherever the data already exists; only add new surface where it genuinely doesn't (the streak).

## Architecture

Three changes, no visual/layout changes:

1. **Extend `agent/services/dashboard.py`'s `_course_summary()`** to add a `topics` field: every topic from `syllabus.json`, each merged with its mastery status from `mastery.weak_topics()`. Topics never quizzed get `score: null, status: "unassessed"`. This makes `GET /api/dashboard/` (already called by the app on load and on every course switch) the single source for both the stat-tile math (`topics_count`/`quizzed_count`, which already exist in the response) and the full "Mastery by topic" list.

2. **Reuse the existing quiz-history fetch.** `loadDashboardRecent(courseId)` already exists and is called for the Dashboard tab's recent-activity widget (`GET /api/courses/<id>/quiz/history/?limit=4`, merged across courses for "All courses"). The Progress tab starts triggering the same call on tab entry and course switch, and its "Recent attempts" card renders `dashboardRecentActivity` (already computed in `renderVals()`) instead of the fake `recentAttempts`/`courseData` list. "Quiz accuracy" is computed from that same fetched sample (`correct / total`) — no separate query.

3. **Add `agent/services/streak.py`**, a new small read-only cross-course service (same shape as `reminders.py`: no `course_id` parameter, scans every course). `current_streak()` returns an `int`. Wire it into `dashboard.build_dashboard()` as a new top-level `"streak"` key alongside the existing `"deadlines"` and `"courses"` keys — no new endpoint, since the Progress tab already loads `/api/dashboard/`.

**Alternatives considered:**
- A single new `/api/progress/` endpoint composing everything server-side in one call. Rejected: duplicates logic already cleanly split across `dashboard.py`/`quiz.py`, and adds a new endpoint + view + tests for one tab when the pieces mostly already exist.
- Doing all the merging client-side in JS (fetch `syllabus.json`, mastery, and quiz history separately in the browser). Rejected: pushes "which topics are unassessed" merge logic into the template instead of the services layer, where this codebase's conventions already put this kind of composition (see `dashboard.py`'s existing role).

## Data shapes

### `/api/dashboard/` response — new `topics` field per course

```json
{
  "deadlines": [...],
  "streak": 3,
  "courses": {
    "cs101": {
      "course_name": "...",
      "notes_count": 2,
      "topics_count": 7,
      "quizzed_count": 2,
      "next_deadline": {...},
      "grading": [...],
      "weak_topics": [...],
      "topics": [
        {"topic": "Recursion", "score": 0.46, "status": "developing"},
        {"topic": "Sorting and searching algorithms", "score": 0.55, "status": "developing"},
        {"topic": "File I/O and error handling", "score": null, "status": "unassessed"}
      ]
    }
  }
}
```

`topics` preserves `syllabus.json`'s topic order (not sorted weakest-first like `weak_topics` — that ordering is for quiz-selection bias, not for a syllabus-shaped progress list). A topic appears once: if `mastery.weak_topics()` has a matching entry, its `score`/`status` are used; otherwise `score: null, status: "unassessed"`.

### Stat tile computation (client-side, from data already fetched)

- **Syllabus covered** = `quizzed_count / topics_count` (existing fields, already in `courseMeta`). For "All courses," sum both across `COURSE_IDS` before dividing.
- **Study streak** = `s.dashboardStreak` (new top-level field from `/api/dashboard/`), same value regardless of selected course.
- **Quiz accuracy** = `correct / total` over `s.dashboardRecentAttempts` (the same list "Recent attempts" renders). `0/0` (no attempts yet) renders as "No attempts yet" rather than a misleading 0% or NaN.

### Streak semantics

`streak.current_streak()`:
1. Read every course_id from `reminders.list_courses()`.
2. For each, read `quiz_history.json` and collect each attempt's `timestamp` truncated to a UTC calendar date.
3. Union all courses' dates into one set (global, not per-course — studying any course on a given day keeps the streak alive).
4. Count consecutive days backward from **today**. If today has no activity but **yesterday** does, count backward from yesterday instead (the streak is still "alive" until a full day passes with zero activity anywhere — standard streak semantics, not reset the instant today has no entry yet).
5. No activity in either today or yesterday → streak is `0`.
6. No quiz activity anywhere ever → streak is `0` (not hidden — the tile always renders a real number, consistent with how `topics_count`/`quizzed_count` already handle "no data yet").

## Edge cases

- **Course with a syllabus but zero notes/quizzes** (e.g. `psyc201` today): `topics` lists every syllabus topic as `unassessed`; "Recent attempts" is empty; accuracy shows "No attempts yet." This already matches the existing `showNoNotesEmptyState` gating for the rest of the tab (unchanged).
- **"All courses" selected**: `topics` isn't meaningful merged across courses as a single flat list (topic names aren't guaranteed unique across courses) — the "Mastery by topic" card keeps its current per-course scoping requirement, i.e. it only renders when a specific course is selected, exactly as `weakTopics` already prefixes course_id when aggregated. "Recent attempts" and the stat tiles already aggregate across courses via the existing `loadDashboardRecent('all')` / `COURSE_IDS` patterns, so those keep working as today's Dashboard tab does.
- **Corrupt course data**: `build_dashboard()` already isolates a corrupt course to `{"error": ...}` in its own slot (see `test_build_dashboard_isolates_corrupt_course`); the new `topics` field follows the same try/except boundary — a corrupt course still doesn't take down the whole dashboard response.

## Explicitly out of scope

- Any visual/layout redesign of the Progress tab — this pass is data-correctness only.
- Per-course streaks (decided: global, matches how study habits actually work — see design discussion).
- "True lifetime" quiz accuracy computed from full, uncapped history — accuracy uses the same recent-attempts sample already shown in the "Recent attempts" card, consistent with what the mock itself implied ("2 of 4").
- A new dedicated `/api/progress/` endpoint.
- Any change to `mastery.py`'s EWMA scoring, `quiz.py`'s question generation, or the Quiz tab.

## Testing

- `agent/tests/test_dashboard.py`: extend `_seed_course`/existing tests to assert the new `topics` field's shape (assessed topic reflects its real score/status, unassessed topic gets `score: null, status: "unassessed"`, order matches syllabus order), and that a corrupt course still isolates cleanly with the new field present.
- New `agent/tests/test_streak.py`, following `test_dashboard.py`'s `isolated_courses_dir` fixture convention: streak of `0` with no attempts anywhere; streak counts consecutive days across multiple courses (global, not per-course); streak stays alive with an attempt yesterday but none today; streak breaks (resets to `0`) after a full day with no activity in any course.
- Manual verification: load `/`, open Progress tab for `cs101` (has real quiz history) and `psyc201` (no notes/quizzes yet), and for "All courses," confirming every number matches what's actually in `courses/*/quiz_history.json` and `courses/*/mastery_scores.json` on disk.
