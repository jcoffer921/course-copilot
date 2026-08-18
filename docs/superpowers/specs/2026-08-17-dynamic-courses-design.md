# Dynamic courses: add a class, upload notes anywhere — design

## Context

OnTrack's frontend (`agent/templates/agent/ontrack.html`) hardcodes exactly two courses everywhere: `const COURSE_IDS = ['cs101', 'psyc201'];` (line 543), two duplicated sidebar chip blocks (lines 64-75), two duplicated "Your courses" dashboard card blocks (lines 160-195), and two dedicated upload-trigger functions (`openUploadCs101`/`openUploadPsyc201`, lines 1117-1118). The backend, by contrast, is already course-agnostic: `POST /api/courses/<course_id>/syllabus/extract/` (`agent/views.py:21`) will create a syllabus — and therefore a course — for *any* new `course_id` slug, and `reminders.list_courses()` (`agent/services/reminders.py:14`) already scans `courses/` on disk rather than reading a fixed list. This pass removes the frontend's two-course assumption and adds a way to create a new class and upload notes for any class from the UI.

One real constraint shapes the design: note uploads already hard-require a syllabus (`chunk_notes.py:191-193` raises `CourseNotFoundError` if `syllabus.json` is missing, because it classifies notes against the syllabus's topic list). Confirmed with the user: a class can be created with just a name, syllabus added later, and until that syllabus exists the class can't accept notes, be quizzed, or be chatted about — it sits in a "syllabus pending" state, exactly mirroring how a real course with zero notes already shows an empty state today.

## What changes and why

### 1. Backend — draft courses (`storage.py`, `reminders.py`, new view, new URL, `dashboard.py`)

A class created with just a name is a **draft**: a `courses/<course_id>/course.json` file (`{"course_id", "course_name", "created_at"}`) that exists independently of `syllabus.json`. This is deliberately isolated from every existing course-facing service — dashboard, quiz, chat, mastery, notes — none of which change, because they already require `syllabus.json` and already isolate a single bad course's data (`dashboard.build_dashboard()`'s per-course try/except, `dashboard.py:70-76`). A draft simply doesn't exist as far as those services are concerned until it graduates.

**`agent/services/storage.py`** (new, alongside the existing `write_syllabus`/`read_syllabus` at lines 288-296 and 476-489):
- `class CourseAlreadyExistsError(Exception)` — raised when a `course_id` already has either `course.json` or `syllabus.json`.
- `write_course_draft(course_id: str, course_name: str) -> Path` — same shape as `write_syllabus`: resolves via `_course_dir` (so `InvalidCourseIdError` is raised for a bad slug, exactly as today), raises `CourseAlreadyExistsError` if `course.json` or `syllabus.json` already exists at that path, otherwise creates the directory and writes `course.json` with `course_id`, `course_name`, and `created_at` (ISO timestamp, matching the timestamp style already used in `sessions.py`).
- `read_course_draft(course_id: str)` — returns the parsed dict or `None`, mirroring `read_syllabus`'s shape exactly (including raising a storage error on corrupt JSON).

**`agent/services/reminders.py`** (new function, alongside `list_courses()` at line 14 — same file because both are "which course_ids exist" scans, not per-course-content reads):
- `list_draft_courses() -> list` — iterates `storage.COURSES_DIR` the same way `list_courses()` does, returning `[{"course_id", "course_name", "created_at"}, ...]` (sorted by `course_id`) for every directory that has `course.json` but does **not** have `syllabus.json`. The moment a syllabus is extracted for that `course_id`, it stops appearing here and starts appearing in `list_courses()` — no explicit "promote" step, no new state machine.

**New view** (`agent/views.py`, alongside `ExtractSyllabusView`): `CourseDraftCreateView` — `POST /api/courses/<course_id>/`, body `{"course_name": "..."}` via a new `CreateCourseDraftRequestSerializer` (`agent/serializers.py`, mirroring the existing serializers' style: `course_name = serializers.CharField(allow_blank=False)`). Calls `storage.write_course_draft`; maps `InvalidCourseIdError` → 400, `CourseAlreadyExistsError` → 409 (with a `detail` message naming whether the conflict is with an existing draft or an existing real course), success → 201 `{"course_id", "course_name"}`.

**New URL** (`agent/urls.py`): `path("courses/<slug:course_id>/", views.CourseDraftCreateView.as_view(), name="course-create-draft")`. This is a distinct pattern from every existing `courses/<slug:course_id>/<sub-resource>/` route (syllabus, notes, quiz, etc.), so it doesn't conflict or need reordering.

**`agent/services/dashboard.py`**: `build_dashboard()` (line 65) gains one additive field: `"drafts": reminders.list_draft_courses()`, alongside the existing `"deadlines"`, `"streak"`, `"courses"` keys. The `"courses"` dict and `_course_summary()` (line 41) are completely unchanged — real courses behave exactly as they do today.

**Continuity**: when a syllabus is later extracted for a `course_id` that has an existing draft, the frontend passes the draft's stored `course_name` as `ExtractSyllabusRequestSerializer`'s existing optional `course_name` hint (`agent/views.py:35`) — no backend change needed for this, `ExtractSyllabusView` already accepts and forwards it. The leftover `course.json` after graduation is harmless and not cleaned up (nothing reads it once `syllabus.json` exists).

### 2. Frontend — dynamic course list

`ontrack.html`'s hardcoded two-course assumption is replaced everywhere by data already available from `/api/dashboard/` (extended above): `state.courseMeta` (unchanged — the `courses` dict, real courses only) plus a new `state.courseDrafts` (the `drafts` array). `COURSE_IDS`/`FALLBACK_COURSE` (lines 543-544) are removed; every place that reads them switches to a computed `realCourseIds` (sorted `Object.keys(state.courseMeta || {})`) and a computed fallback (first `realCourseIds` entry, or `null` if there are none — see empty states below).

- **Sidebar chips** (lines 64-75): the two hardcoded chip `<div>`s become one `sc-for` over a `courseChips` list built in `renderVals()` — one entry per real course (cycling the existing accent/accent-2 dot colors by index, exactly the CS101/PSYC201 split today) plus one per draft (dimmer/neutral dot, label suffixed `· pending`). Clicking a draft chip navigates the same way a real course chip does; the tabs handle the "no syllabus yet" state (below).
- **Dashboard "Your courses" grid** (lines 160-195): the two duplicated card blocks become one `sc-for` over `yourCoursesCards`. A real course's card is today's existing content (kicker, name, summary, tags, "Upload notes" button) unchanged in substance, just templated once instead of twice. A draft's card shows the class name, a "Syllabus pending" kicker, and an "Upload syllabus" button in place of the tags/grading rows.
- **"All courses" aggregation** (weak topics/deadlines, e.g. line 918): switches from iterating `COURSE_IDS` to `realCourseIds` — drafts have no quiz/deadline data to aggregate, so they're excluded, same as a real course with zero notes already contributes nothing here.
- **`openUpload(courseId)`** (line 767) is already course-id-generic — no change needed. Each dynamic course card's "Upload notes" button calls it with the loop's `courseId` instead of a dedicated `openUploadCs101`/`openUploadPsyc201` wrapper, which are deleted.

### 3. "Add a class"

Sidebar, directly under the dynamic course-chip list (matching the "+ New chat" button already in the Chat tab). New state: `addClassOpen`, `addClassName`, `addClassId` (derived), `addClassFile`, `addClassLoading`, `addClassError`. Modal fields: class name (required) and syllabus file (optional, same `.pdf/.txt/.md` accept as the existing upload-notes modal). The `course_id` is derived client-side by slugifying the typed name (lowercase, spaces → hyphens, strip anything outside `[a-z0-9_-]`, truncate to 64 chars, matching `storage.py`'s `COURSE_ID_RE` exactly) and shown read-only under the name field so the user can see what it'll be before submitting.

- File attached → `POST /api/courses/<id>/syllabus/extract/` directly (existing endpoint, multipart with `file`, `course_name` set from the typed name, `overwrite` omitted/false) — the course is real immediately, no draft ever created. If `<id>` happens to already exist, the existing endpoint's own 409 conflict handling (`agent/views.py:44-52`) fires unchanged — nothing new to build there.
- No file → `POST /api/courses/<id>/` (new draft endpoint) — the course appears as a draft.
- A 409 (id collision with either an existing draft or real course) surfaces `addClassError` with the endpoint's `detail` message; the user edits the name and retries.
- On success, close the modal and reload the dashboard (`loadDashboard()`, already exists) so the new chip/card appears immediately.

### 4. "Upload notes" — generalized + new entry point

The existing per-card button is generalized as described in §2. Additionally, a second sidebar entry next to "+ Add class": **"Upload notes"**, which opens a small picker modal (new state: `uploadPickerOpen`) listing every *real* course by name (drafts excluded — they can't accept notes yet, per the constraint above). Selecting a course calls the existing `openUpload(courseId)` and closes the picker, landing in the exact same upload-notes modal the per-card button already opens — no new upload logic, just a second way to reach the same flow without first navigating to a specific course's card.

### 5. Empty states for draft courses

Quiz, Chat, and Progress currently distinguish only "has notes" vs. "no notes yet" (`courseHasNotes`/`showNoNotesEmptyState`, e.g. lines 131/149). This gains a third state for the selected course being a draft (no syllabus at all): a new computed `courseIsDraft` (true when the selected course id appears in `state.courseDrafts` rather than `state.courseMeta`) drives a distinct empty-state message — "This class doesn't have a syllabus yet. Add one from the sidebar to start tracking it." — reusing the existing empty-state card markup, just with different copy and no "Upload notes" CTA (a draft's only next action is uploading a syllabus, which happens from the sidebar/dashboard card, not from inside Quiz/Chat/Progress).

## Explicitly out of scope for this pass

- Renaming or deleting a course or a draft.
- Editing a draft's name before its syllabus is uploaded.
- Allowing notes to be uploaded before a syllabus exists (explicitly declined — would require reworking `chunk_notes.py`'s topic-classification logic, a separate design question).
- Any change to `chunk_notes.py`, `quiz.py`, `ask.py`, `mastery.py`, or `sessions.py` — all already gate on `syllabus.json` existing and are unaffected by drafts.
- Course icons/avatars beyond the existing two-accent-color dot cycling.
- Cleaning up a draft's `course.json` after it graduates to a real course.
- A course-picker beyond the two new entry points (e.g. no changes to the Quiz/Chat/Progress course-selection flow beyond the new draft empty state).

## Verification

- `python manage.py check`.
- `write_course_draft`/`read_course_draft`/`list_draft_courses` unit-level checks (new tests alongside the existing `agent/tests/test_domains.py`-style storage tests): creating a draft, reading it back, confirming it appears in `list_draft_courses()` and not in `reminders.list_courses()`; confirming `CourseAlreadyExistsError` fires against both an existing draft and an existing real course; confirming a draft disappears from `list_draft_courses()` once a syllabus is written for the same `course_id` (and appears in `list_courses()` instead).
- `POST /api/courses/<id>/` integration test: 201 on success, 400 for an invalid slug, 409 for a colliding draft and a colliding real course.
- `GET /api/dashboard/` test: `"drafts"` key present and correctly populated alongside the unchanged `"courses"`/`"deadlines"`/`"streak"` shape.
- Manual: load `/`, use "+ Add class" with no file → new dimmer chip and "Syllabus pending" card appear; select it in Quiz/Chat/Progress → draft empty-state copy shows, no crash. Use "+ Add class" with a syllabus file attached → course appears as a normal (non-pending) chip/card immediately. Use the new "Upload notes" sidebar entry → picker excludes drafts, selecting a real course opens the existing upload modal and a subsequent upload succeeds exactly as the per-card button does today.
