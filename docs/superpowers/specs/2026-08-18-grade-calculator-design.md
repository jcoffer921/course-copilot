# Grade Calculator tab — design

## Context

OnTrack currently tracks two things that look like "grades" but aren't: `syllabus.json`'s `grading` array (category names and weights only — e.g. `{"component": "Homework", "weight_pct": 20}`, no actual scores), and `quiz_history.json` (the app's own AI-generated practice quizzes, which measure topic mastery, not real course performance). Nowhere does OnTrack know what you actually scored on a real homework, test, or quiz handed back by an instructor.

This design adds a **Grade Calculator** tab — a new sidebar entry directly under Quiz — that lets you record real scores against your syllabus's grading categories, see your current grade (per course and averaged across all courses), and answer two forward-looking questions: "what do I need to score on what's left to hit a target grade?" and "how many of what's left can I miss and still get there?"

## Goals

- Track real, manually-entered scores (score / max_points) against a course's existing syllabus grading categories — no duplicate category system.
- Compute a current grade (percentage + letter) per course, correctly excluding categories with no data yet rather than counting them as zero.
- Compute a simple average across all courses for a semester-level view.
- Answer "what average do I need on everything left to hit a target grade" and, per category, "how many of what's left can I miss and still hit that target."
- Support an optional "drop the lowest N" policy per category.
- Reuse the existing card/stat-tile visual language (Progress tab) and the existing course-selector (chip) mechanism — no new UI framework or navigation model.

## Non-goals (explicitly out of scope)

- Pulling scores automatically from anywhere (LMS import, OCR, etc.) — manual entry only, per the earlier decision in this conversation.
- Credit-hour-weighted GPA — the all-courses number is a plain average; `syllabus.json` gets no new `credits` field.
- Combined "you can miss N assignments total" math across categories — deliberately kept per-category (see Architecture) because blending a missed final exam with a missed homework into one number would misrepresent the actual stakes.
- What-if solving at the all-courses level — targets are inherently course-specific; the all-courses view is a rollup list only.
- Multi-item drop-lowest optimization (choosing *which* future items get dropped) — the calculator applies drop-lowest only to already-entered scores; projected future scores are never considered droppable.

## Architecture

### Data model

**Extend `syllabus.json`'s existing `grading` array** with two new optional fields per category, and add one new optional top-level field:

```json
{
  "grading": [
    {"component": "Homework", "weight_pct": 20, "total_items": 8, "drop_lowest": 1},
    {"component": "Midterm", "weight_pct": 30},
    {"component": "Final", "weight_pct": 30},
    {"component": "Quizzes", "weight_pct": 20, "total_items": 10}
  ],
  "grade_scale": {
    "passing_pct": 60,
    "cutoffs": [
      {"letter": "A", "min_pct": 93}, {"letter": "A-", "min_pct": 90},
      {"letter": "B+", "min_pct": 87}, {"letter": "B", "min_pct": 83}, {"letter": "B-", "min_pct": 80},
      {"letter": "C+", "min_pct": 77}, {"letter": "C", "min_pct": 73}, {"letter": "C-", "min_pct": 70},
      {"letter": "D+", "min_pct": 67}, {"letter": "D", "min_pct": 63}, {"letter": "D-", "min_pct": 60}
    ]
  }
}
```

`total_items` and `drop_lowest` are per-category and optional. `grade_scale` is course-level and optional — absent entirely means "use the default scale shown above" (same convention as `trusted_domains.json`: absence is a normal state, not an error). A category without `total_items` can still show a current average; it just can't participate in what-if projections (its current average is treated as final, per Architecture below).

**New `courses/<course_id>/grades.json`** — the entered scores, one file per course, direct CRUD (not an append-only log like `quiz_history.json`, since scores get corrected/edited):

```json
{
  "course_id": "cs101",
  "items": [
    {"id": "uuid", "component": "Homework", "title": "HW 3", "score": 92, "max_points": 100, "date": "2026-02-10"}
  ]
}
```

`component` must match a `component` string in that course's `syllabus.json` `grading` array (validated at write time — same spirit as notes chunks reusing syllabus topic strings). `score` may exceed `max_points` (extra credit); both must be non-negative.

### Calculation engine (`agent/services/grades.py`)

All functions are pure computation over `storage.read_syllabus()` + a new `storage.read_grades()`/`write_grades()` pair, mirroring `mastery.py`'s structure (no async/API calls in this file).

**`current_grade(course_id)`** — "what's my grade right now":
1. For each category with ≥1 entered item: convert each item to a percentage (`score / max_points * 100`), sort ascending, drop the lowest `min(drop_lowest, count - 1)` of them (never drop every item), average the rest → that category's `avg_pct`.
2. Categories with zero entered items are **excluded** from this computation entirely — not treated as 0%. This matches how people actually think about "my grade so far" (an ungraded final exam shouldn't crater today's number).
3. Overall = weighted average of `avg_pct` across only the categories with data, using their `weight_pct`, **renormalized** so those weights sum to 100 among themselves.
4. Returns `null` overall if no category has any data yet (empty state, not 0%).
5. Letter grade looked up from `grade_scale.cutoffs` (highest cutoff whose `min_pct` the overall meets), `"F"` below the lowest cutoff.

**`grade_needed(course_id, target_pct)`** — "what do I need on what's left":
This is a single linear equation in one unknown `p` (a flat score, applied uniformly to every remaining ungraded item across every category with `total_items` set):

- For each category: `kept_sum`/`kept_count` are the post-drop entered scores (from step 1 above). `remaining = max(total_items - entered_count, 0)` if `total_items` is set, else `0` (a category with no `total_items` is treated as **closed** — its current average, or `0` if it has no entries at all, is locked in as final; this is a real ceiling and the response flags it explicitly rather than silently capping the achievable grade).
- `projected_avg(p) = (kept_sum + remaining * p) / (kept_count + remaining)`.
- Overall becomes `A + B*p` where `A = Σ weight_pct * (kept_sum / denom) / total_weight` and `B = Σ weight_pct * (remaining / denom) / total_weight`.
- Solve `p = (target_pct - A) / B`.
  - `B == 0` (nothing left anywhere): report `locked_at: A`, no `p` — the grade can no longer change.
  - `p > 100`: not achievable; report the required `p` anyway (so the user sees *how* out of reach it is) plus the true ceiling (`A + B*100`, i.e. scoring 100 on everything left).
  - `p <= 0`: already guaranteed even at 0 on everything remaining; report `p: 0`.

**`missable_by_category(course_id, target_pct)`** — "how many can I miss, per category":
Scoped to one category at a time, independent of the other categories (deliberately — see Non-goals). For category `c` with `remaining` items left: find the largest `k` such that scoring `0` on `k` of the remaining items and `100` on the rest still keeps `c`'s own average at or above `target_pct`:

```
projected(k) = (kept_sum + (remaining - k) * 100) / (kept_count + remaining)
```

`k` is the largest value where `projected(k) >= target_pct`. Only computed for categories with `total_items` set and `remaining > 0`; categories without `total_items` are omitted from this list (with a note why), not shown as `0`.

**`all_courses_summary()`** — plain average of `current_grade()` across courses that have at least one graded item, following `dashboard.build_dashboard()`'s per-course try/except isolation (one corrupt course's `grades.json` doesn't break the rollup for the rest). Courses with no grades entered yet are listed but excluded from the average, with a count of how many were excluded.

### API (`agent/urls.py` / `agent/views.py`)

New endpoints, following the existing `courses/<id>/...` async-view convention:

- `GET/PUT /api/courses/<id>/grading/` — read/edit the `grading` array + `grade_scale` on `syllabus.json`
- `GET /api/courses/<id>/grades/` — entered items + `current_grade()` breakdown, one response
- `POST /api/courses/<id>/grades/items/` — add an item
- `PATCH/DELETE /api/courses/<id>/grades/items/<item_id>/` — edit/remove an item
- `GET /api/courses/<id>/grades/whatif/?target=90` — `grade_needed` + `missable_by_category`
- `GET /api/grades/summary/` — all-courses rollup

### CLI

`agent/management/commands/grades.py`, wrapping the same service functions (`--add`, `--list`, `--whatif`), matching every other service's CLI-mirrors-API convention (`extract_syllabus.py`, `quiz.py`, etc.).

### Frontend (`agent/templates/agent/ontrack.html`)

New sidebar button "Grade Calculator" under Quiz, `tab: 'grades'`. **Unlike Quiz/Progress/Chat, this tab does not bounce to Dashboard when "All Courses" is selected** — it renders the all-courses view instead, since a semester-wide view is the whole point.

**Per-course view** (specific course selected), matching Progress tab's card/stat-tile language:
- 3-card stat grid: current grade (big % + letter), categories graded (`3 of 4`), items entered.
- "Grading breakdown" card: one row per category — weight%, avg%, `entered/total_items` (or just entered count if no total set), drop-lowest note if configured.
- "Grades" card: list of entered items (component tag, title, score, date) with inline edit/delete; "Add grade" button opens a modal, same pattern as the existing "Upload notes" modal.
- "What-if" card: target-grade input (defaults to `grade_scale.passing_pct`, with a "Set to passing" quick button), shows the flat score needed on everything remaining (or the locked/impossible states from `grade_needed`), plus the per-category missable list. If no category has `total_items` set, this card shows a setup prompt instead of blank/broken math.
- Empty state: course has no `grading` array yet → prompt to set up categories (links to the grading-setup form) instead of a broken/zero grade.

**All-courses view**: header stat with the blended average (and count of courses excluded for having no grades yet), then a simple list of every course with its grade % and letter. No what-if here.

## Alternatives considered

- **A single blended "you can miss N assignments" number across all categories.** Rejected: a missed final-exam item and a missed homework item aren't comparable in impact, and collapsing them into one number would misrepresent risk. Per-category is more code but honest.
- **Credit-weighted all-courses average.** Rejected for now: requires adding a `credits` field the user would have to fill in for every course, for a single-user semester tracker where a plain average is good enough (matches the earlier decision in this conversation).
- **Duplicate category/weight config inside `grades.json` instead of extending `syllabus.json`.** Rejected: `syllabus.json.grading` already exists and is already shown elsewhere (Dashboard course cards); extending it avoids two sources of truth for the same weights.

## Edge cases

- **Category with entered items but `drop_lowest` ≥ item count**: clamp to `count - 1`, always keep at least one item contributing.
- **Category with `total_items` set lower than items already entered** (user over-entered, or lowered the total after the fact): `remaining` clamps to `0`; the category is treated as closed for projection purposes, current average stands.
- **Course with a `grading` array that doesn't sum to 100%**: `storage.validate_syllabus()` already warns (non-blocking) on this — `current_grade()` renormalizes using the categories' actual weights regardless, so a syllabus with a data-entry typo in its weights doesn't produce a silently wrong-scale grade.
- **`score` for an item exceeds `max_points`** (extra credit): allowed, not clamped.
- **All-courses view where every course has zero grades entered**: average is `null`, shown as an empty state ("No grades entered yet"), not `0%`.
- **A category has neither `total_items` nor any entered items**: `grade_needed` locks its contribution at `0` and flags it explicitly in the response (`"Homework has no items entered and no total set — its 0% is currently capping your achievable grade"`) rather than letting it silently suppress the ceiling.

## Testing

- New `agent/tests/test_grades.py` (pytest, following `test_dashboard.py`'s `isolated_courses_dir` fixture convention):
  - `current_grade`: empty course (no items) → `null`; single category with data renormalizes correctly excluding empty categories; drop-lowest clamps at `count - 1`; letter-grade lookup at cutoff boundaries.
  - `grade_needed`: straightforward case with remaining items in multiple categories; `B == 0` locked case; `p > 100` unachievable case (and its reported ceiling); category without `total_items` treated as closed.
  - `missable_by_category`: standard case; `k = 0` case (must ace everything left); category omitted when `total_items` unset.
  - `all_courses_summary`: average excludes courses with no grades; corrupt course isolation (same pattern as `test_build_dashboard_isolates_corrupt_course`).
- Manual verification: add real scores for `cs101` across at least two categories (one with `total_items` set, one without), confirm the per-course view's numbers match hand-calculated expectations, confirm the what-if card's "needed" and "missable" numbers against a hand-solved example, then check the all-courses view reflects the same course correctly alongside a course with zero grades entered.
