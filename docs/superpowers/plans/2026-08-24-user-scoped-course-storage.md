# User-Scoped Course Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every piece of course *content* (syllabus, notes, references, trusted domains, grading config) user-scoped on disk, so two students can each have their own `cs101` without colliding or seeing each other's data — the multi-tenancy gap needed before piloting OnTrack to a department.

**Architecture:** `agent/services/storage.py`'s `_course_dir(course_id)` is the single chokepoint every file-based course-content function resolves through. Changing it to `_course_dir(course_id, user)` — resolving `courses/<user.pk>/<course_id>/` instead of `courses/<course_id>/` — and threading `user` through every caller (service layer → views.py → CLI) closes the gap with one structural change plus a mechanical propagation pass. Mutable per-user state (grades, mastery, quiz history, sessions, custom events, flashcards, notifications, saved sites) is **already** correctly scoped via Django ORM models with a `user` FK — this plan does not touch those data models, only the 15 places they call `_course_dir(course_id)` purely to validate the string (their return value is discarded today).

**Tech Stack:** Django 6.x, DRF/adrf (async views), pytest + pytest-django + pytest-asyncio, Python `pathlib`.

## Global Constraints

- MVP scope: **everything** becomes user-scoped now. No shared/global course content in this pass — a shared course/lecture DB across students is explicitly deferred to a later version (do not build it here).
- New on-disk path convention: `courses/<user.pk>/<course_id>/...` (integer primary key, not username/email — stable, no path-unsafe characters).
- The 9 CLI management commands (`extract_syllabus`, `chunk_notes`, `ask`, `quiz`, `mastery`, `references`, `reminders`, `sessions`, `domains`, `grades`) stay scoped to a single designated **owner** account — dev/debug tools only, never used by real students. They resolve the owner via a new `CLI_OWNER_EMAIL` env var (consistent with the project's existing email-based identity model — see `README.md`'s `ALLOWED_GOOGLE_EMAILS`), not a `--user` flag.
- Every changed function signature makes `user` a **required** parameter (no `user=None` default) for the file-based content family — a missing user must fail loudly with `TypeError` at the call site, not silently write to a wrong/shared location. This matches CLAUDE.md's "fails loudly" convention.
- Do **not** change the already-correct DB-scoped functions' `user=None` semantics (they intentionally support `user=None` to mean "legacy/anonymous rows" via `_scope_user_queryset`) — only replace their discarded `_course_dir(course_id)` validation call with a new lightweight `_validate_course_id(course_id)` that has no user requirement.
- Never commit without running the full test suite (`venv/Scripts/python.exe -m pytest agent/tests/ -q`) green first.

---

## File Structure

| File | Change |
|---|---|
| `agent/services/storage.py` | Core path-resolution plumbing; 11 content read/write functions; 5 course-management functions; `delete_course_state` bug fix |
| `agent/services/reminders.py` | `list_courses`, `list_draft_courses`, `upcoming_deadlines` gain required/threaded `user` |
| `agent/services/dashboard.py` | `_note_topics`, `_course_summary`, `build_dashboard` thread `user` |
| `agent/services/grades.py` | `_require_syllabus` gains `user`; 5 callers pass it; `all_courses_summary` threads `user` into `list_courses` |
| `agent/services/streak.py` | `current_streak` threads `user` into `list_courses` |
| `agent/services/chunk_notes.py` | `chunk_notes_async` gains `user`, threads to internal `read_syllabus` |
| `agent/services/references.py` | `ingest_reference` gains `user`, threads to internal `read_reference` |
| `agent/services/domain_suggestions.py` | `suggest_domains` gains `user`, threads to internal `read_syllabus` |
| `agent/services/ask.py` | `ask_async`'s 4 internal content-read calls gain `user=user` |
| `agent/services/quiz.py` | `_all_chunks` gains `user`; `generate_flashcards_async`/`generate_assessment_question_async` thread it |
| `agent/services/sessions.py` | `create_session`'s internal `read_syllabus` call gains `user=user` |
| `agent/views.py` | ~23 call sites gain `user=request.user` |
| `agent/services/cli_owner.py` (new) | `resolve_owner_user()` helper shared by all 9 CLI commands |
| `agent/management/commands/*.py` (9 files) | Resolve owner, thread through every content-family call |
| `agent/management/commands/migrate_course_ownership.py` (new) | One-time on-disk migration: `courses/<course_id>/` → `courses/<owner.pk>/<course_id>/` |
| `agent/tests/*.py` | Every test that calls a changed function directly gains a `user=` argument |

---

### Task 1: Core path-resolution plumbing in storage.py

**Files:**
- Modify: `agent/services/storage.py:127-160` (`_course_dir`, `_lecture_path`, `_reference_path`)
- Test: `agent/tests/test_storage_path_resolution.py` (new file)

**Interfaces:**
- Produces: `_validate_course_id(course_id: str) -> None` (raises `InvalidCourseIdError`), `_course_dir(course_id: str, user) -> Path` (raises `ValueError` if `user is None`, `InvalidCourseIdError` for a bad slug), `_lecture_path(course_id: str, lecture_id: str, user) -> Path`, `_reference_path(course_id: str, reference_id: str, user) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
"""New tests for storage.py's user-scoped path resolution (Task 1 of the
user-scoped-course-storage plan)."""
import pytest

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_course_dir_nests_under_user_pk(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    course_dir = storage._course_dir("cs101", user)
    assert course_dir == isolated_courses_dir / str(user.pk) / "cs101"


def test_course_dir_requires_a_user(isolated_courses_dir):
    with pytest.raises(ValueError):
        storage._course_dir("cs101", None)


@pytest.mark.django_db
def test_course_dir_rejects_invalid_course_id(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    with pytest.raises(storage.InvalidCourseIdError):
        storage._course_dir("../../etc", user)


@pytest.mark.django_db
def test_lecture_path_nests_under_user_and_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    path = storage._lecture_path("cs101", "lec1", user)
    assert path == isolated_courses_dir / str(user.pk) / "cs101" / "notes" / "lec1.json"


@pytest.mark.django_db
def test_reference_path_nests_under_user_and_course(isolated_courses_dir, django_user_model):
    user = django_user_model.objects.create_user(username="u1", email="u1@example.com")
    path = storage._reference_path("cs101", "ref1", user)
    assert path == isolated_courses_dir / str(user.pk) / "cs101" / "references" / "ref1.json"


def test_validate_course_id_has_no_user_requirement():
    storage._validate_course_id("cs101")
    with pytest.raises(storage.InvalidCourseIdError):
        storage._validate_course_id("../../etc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_path_resolution.py -v`
Expected: FAIL — `_course_dir() takes 1 positional argument but 2 were given` (and `_validate_course_id` not defined).

- [ ] **Step 3: Replace the three path helpers in storage.py**

Replace lines 127-160 (`_course_dir`, `_lecture_path`, `_reference_path`) with:

```python
def _validate_course_id(course_id: str) -> None:
    """Raises InvalidCourseIdError if course_id isn't a safe slug. Shared by
    _course_dir (which also resolves a per-user filesystem path) and every
    DB-scoped function below that only ever needed course_id validated, not
    a directory resolved — they called _course_dir(course_id) purely for
    this check and discarded its return value."""
    if not COURSE_ID_RE.fullmatch(course_id):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")


def _course_dir(course_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>, guarding against path
    traversal. `user` is required — course content has no valid unowned
    state now that storage is per-user; a missing user is a caller bug, not
    a runtime condition to handle gracefully (fails loudly per CLAUDE.md)."""
    if user is None:
        raise ValueError("_course_dir requires a user — course content is always user-scoped")
    _validate_course_id(course_id)
    resolved_courses_dir = COURSES_DIR.resolve()
    course_dir = (COURSES_DIR / str(user.pk) / course_id).resolve()
    if not course_dir.is_relative_to(resolved_courses_dir):
        raise InvalidCourseIdError(f"invalid course_id: {course_id!r}")
    return course_dir


def _lecture_path(course_id: str, lecture_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/notes/<lecture_id>.json,
    guarding against path traversal via lecture_id the same way _course_dir
    does for course_id."""
    if not LECTURE_ID_RE.fullmatch(lecture_id):
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    notes_dir = _course_dir(course_id, user) / "notes"
    path = (notes_dir / f"{lecture_id}.json").resolve()
    if path.parent != notes_dir.resolve():
        raise InvalidLectureIdError(f"invalid lecture_id: {lecture_id!r}")
    return path


def _reference_path(course_id: str, reference_id: str, user) -> Path:
    """Resolves courses/<user.pk>/<course_id>/references/<reference_id>.json,
    guarding against path traversal via reference_id the same way
    _lecture_path does for lecture_id."""
    if not REFERENCE_ID_RE.fullmatch(reference_id):
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    references_dir = _course_dir(course_id, user) / "references"
    path = (references_dir / f"{reference_id}.json").resolve()
    if path.parent != references_dir.resolve():
        raise InvalidReferenceIdError(f"invalid reference_id: {reference_id!r}")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_path_resolution.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite to see the blast radius**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: many FAILs (every caller of the three helpers is now broken) — this is the expected starting point for Tasks 2-9, which fix them family by family. Note the failure count so Task 9's final green run is verifiable progress, not a guess.

- [ ] **Step 6: Commit**

```bash
git add agent/services/storage.py agent/tests/test_storage_path_resolution.py
git commit -m "feat: make _course_dir and friends resolve a per-user path"
```

---

### Task 2: Thread `user` through storage.py's content read/write functions

**Files:**
- Modify: `agent/services/storage.py` — 11 functions: `read_syllabus` (459), `read_notes` (470), `read_lecture` (487), `write_notes` (498), `read_references` (513), `read_reference` (530), `write_reference` (542), `read_trusted_domains` (558), `write_trusted_domains` (580), `write_syllabus` (1153), `write_grading_config` (1168)
- Modify: `agent/services/storage.py` — the 15 DB-scoped functions whose discarded `_course_dir(course_id)` validation call must become `_validate_course_id(course_id)` (unrelated to this task's `user` requirement, but breaks today from Task 1 — fix here since it's a one-line swap per function): `read_quiz_history` (597), `append_quiz_attempt` (618), `read_flashcard_progress` (680), `write_flashcard_progress` (695), `read_saved_flashcards` (743), `remember_generated_flashcards` (773), `update_flashcard_progress` (834), `reset_flashcard_progress` (878), `read_calendar_sync` (891), `append_calendar_sync_record` (908), `read_mastery_scores` (923), `write_mastery_scores` (947), `read_grades` (972), `write_grades` (993), `list_saved_sites` (1042), `save_site` (1050)

**Interfaces:**
- Consumes: `_course_dir(course_id, user)`, `_validate_course_id(course_id)`, `_lecture_path(course_id, lecture_id, user)`, `_reference_path(course_id, reference_id, user)` from Task 1.
- Produces: `read_syllabus(course_id, user)`, `read_notes(course_id, user) -> list`, `read_lecture(course_id, lecture_id, user)`, `write_notes(course_id, lecture_id, data, user, overwrite=False) -> Path`, `read_references(course_id, user) -> list`, `read_reference(course_id, reference_id, user)`, `write_reference(course_id, reference_id, data, user, overwrite=False) -> Path`, `read_trusted_domains(course_id, user) -> list`, `write_trusted_domains(course_id, domains, user) -> Path`, `write_syllabus(course_id, data, user, overwrite=False) -> Path`, `write_grading_config(course_id, grading, user, grade_scale=None) -> Path`. `user` is always a required positional parameter placed immediately after the existing positional args (before any keyword-defaulted arg like `overwrite`).

- [ ] **Step 1: Update the two path-building call patterns first (mechanical, no test needed on their own — Task 1's tests already cover the underlying helpers)**

In each of the 15 DB-scoped functions listed above, replace the bare validation statement with `_validate_course_id(course_id)`. Example for `read_quiz_history` (line ~597):

```python
# Before:
def read_quiz_history(course_id: str, user=None) -> dict:
    _course_dir(course_id)
    ...

# After:
def read_quiz_history(course_id: str, user=None) -> dict:
    _validate_course_id(course_id)
    ...
```

Apply the identical `_course_dir(course_id)` → `_validate_course_id(course_id)` swap to all 15 functions listed in Files above — every one currently has that exact single-argument call as its first statement (confirmed during research; grep to double check before editing: `grep -n "    _course_dir(course_id)$" agent/services/storage.py` should show exactly these 15 lines plus none from the 11 content functions being changed in Step 3, since those call `_course_dir(course_id, user)` there instead).

- [ ] **Step 2: Run the full suite to confirm this sub-step introduced no new breakage in the DB-scoped family**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_storage_grades.py agent/tests/test_storage_flashcards.py agent/tests/test_storage_calendar_sync.py -q`
Expected: PASS (these test files exercise the DB-scoped functions and don't touch the content family, so they should be unaffected by Task 1's breakage and green again now)

- [ ] **Step 3: Update the 11 content functions' signatures and bodies**

```python
def read_syllabus(course_id: str, user):
    course_dir = _course_dir(course_id, user)
    syllabus_path = course_dir / "syllabus.json"
    if not syllabus_path.exists():
        return None
    try:
        return json.loads(syllabus_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise SyllabusStorageError(f"existing syllabus.json for '{course_id}' is corrupt: {e}")


def read_notes(course_id: str, user) -> list:
    notes_dir = _course_dir(course_id, user) / "notes"
    if not notes_dir.exists():
        return []
    lectures = []
    for path in sorted(notes_dir.glob("*.json")):
        try:
            lectures.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise SyllabusStorageError(f"notes file '{path.name}' for '{course_id}' is corrupt: {e}")
    return lectures


def read_lecture(course_id: str, lecture_id: str, user):
    path = _lecture_path(course_id, lecture_id, user)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise NotesStorageError(f"lecture '{lecture_id}' for '{course_id}' is corrupt: {e}")


def write_notes(course_id: str, lecture_id: str, data: dict, user, overwrite: bool = False) -> Path:
    course_dir = _course_dir(course_id, user)
    notes_dir = course_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = _lecture_path(course_id, lecture_id, user)
    if path.exists() and not overwrite:
        raise FileExistsError(f"notes for lecture '{lecture_id}' already exist for '{course_id}'")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def read_references(course_id: str, user) -> list:
    references_dir = _course_dir(course_id, user) / "references"
    if not references_dir.exists():
        return []
    refs = []
    for path in sorted(references_dir.glob("*.json")):
        try:
            refs.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise ReferencesStorageError(f"reference file '{path.name}' for '{course_id}' is corrupt: {e}")
    return refs


def read_reference(course_id: str, reference_id: str, user):
    path = _reference_path(course_id, reference_id, user)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise ReferencesStorageError(f"reference '{reference_id}' for '{course_id}' is corrupt: {e}")


def write_reference(course_id: str, reference_id: str, data: dict, user, overwrite: bool = False) -> Path:
    course_dir = _course_dir(course_id, user)
    references_dir = course_dir / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    path = _reference_path(course_id, reference_id, user)
    if path.exists() and not overwrite:
        raise FileExistsError(f"reference '{reference_id}' already exists for '{course_id}'")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def read_trusted_domains(course_id: str, user) -> list:
    course_dir = _course_dir(course_id, user)
    path = course_dir / "trusted_domains.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise TrustedDomainsStorageError(f"trusted_domains.json for '{course_id}' is corrupt: {e}")
    return data.get("domains", [])


def write_trusted_domains(course_id: str, domains: list, user) -> Path:
    course_dir = _course_dir(course_id, user)
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "trusted_domains.json"
    path.write_text(
        json.dumps({"course_id": course_id, "domains": domains}, indent=2),
        encoding="utf-8",
    )
    return path


def write_syllabus(course_id: str, data: dict, user, overwrite: bool = False) -> Path:
    out_dir = _course_dir(course_id, user)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "syllabus.json"
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"syllabus.json already exists for '{course_id}'")
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path


def write_grading_config(course_id: str, grading: list, user, grade_scale: dict = None) -> Path:
    data = read_syllabus(course_id, user)
    if data is None:
        raise CourseNotFoundError(f"no syllabus found for '{course_id}'")
    data["grading"] = grading
    if grade_scale is not None:
        data["grade_scale"] = grade_scale
    return write_syllabus(course_id, data, user, overwrite=True)
```

Note: keep each function's original docstring and error-handling bodies exactly as they exist today (elided above only where the body is a straightforward line-for-line carryover) — the only structural change is the new required `user` param and passing it into `_course_dir`/`_lecture_path`/`_reference_path`. Read the current body of each function in `agent/services/storage.py` before editing to confirm you're preserving every existing docstring, corruption message, and exception type — do not paraphrase real behavior differences away.

- [ ] **Step 4: Update this file's own direct tests**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q -k "syllabus or notes or reference or domain" 2>&1 | tail -40`

For each failure, the error will be one of:
- `TypeError: read_syllabus() missing 1 required positional argument: 'user'` (or similar for the other 10 functions) — fix by adding a `user` argument to the call. If the test already has a Django user fixture in scope (look for `django_user_model.objects.create_user(...)` earlier in the same test), reuse it. If not, add one: `user = django_user_model.objects.create_user(username="<test-specific-unique-name>", email="<same>@example.com")` right before the failing call, and add the `django_user_model` fixture to the test function's parameter list if it isn't already there. Add `@pytest.mark.django_db` to the test if it isn't already marked (creating a `User` row requires DB access).
- Path-shape assertion failures (a test asserting a literal `courses/<course_id>/...` path string) — update the expected path to `courses/<user.pk>/<course_id>/...` using the same `user` object the test now creates.

Repeat `pytest ... -k "syllabus or notes or reference or domain"` after each fix until this filtered run is fully green. Do not move to Step 5 with any of these failing.

- [ ] **Step 5: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: fewer failures than Task 1's Step 5 baseline (storage.py's own direct tests now pass; failures remaining are all downstream callers not yet updated — service layer, views, CLI — which Tasks 4-8 fix)

- [ ] **Step 6: Commit**

```bash
git add agent/services/storage.py agent/tests/
git commit -m "feat: require user on storage.py's content read/write functions"
```

---

### Task 3: Thread `user` through course-management functions, fix the cross-user delete bug

**Files:**
- Modify: `agent/services/storage.py:1187-1296` (`write_course_draft`, `course_exists`, `course_or_draft_exists`, `delete_course`, `delete_course_state`, `rename_course`)
- Test: existing course-management tests (`grep -rl "write_course_draft\|course_exists\|course_or_draft_exists\|delete_course\|rename_course" agent/tests/` to find them — `test_course_drafts.py` is the primary one per the codebase's naming convention)

**Interfaces:**
- Consumes: `_course_dir(course_id, user)`, `_flashcard_user_filter(user) -> dict` (already defined at storage.py:642, returns `{"user": user}` for an authenticated user).
- Produces: `write_course_draft(course_id, course_name, user) -> Path`, `course_exists(course_id, user) -> bool`, `course_or_draft_exists(course_id, user) -> bool`, `delete_course(course_id, user) -> None`, `delete_course_state(course_id, user) -> None`, `rename_course(course_id, course_name, user) -> None`.

- [ ] **Step 1: Update the six functions**

```python
def write_course_draft(course_id: str, course_name: str, user) -> Path:
    """Writes course.json — a class that has a name but no syllabus yet.
    Raises InvalidCourseIdError (via _course_dir) for a bad slug, and
    CourseAlreadyExistsError if course_id already has course.json or
    syllabus.json for this user — a draft can't collide with itself or a
    real course belonging to the same user."""
    out_dir = _course_dir(course_id, user)
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


def course_exists(course_id: str, user) -> bool:
    """True if course_id is a real (syllabus'd) course for this user — the
    same definition reminders.list_courses() uses, so this matches exactly
    what the UI already offers as a selectable course. False (never raises)
    for a draft-only course, a missing course, or an unsafe/invalid
    course_id — callers doing input validation want a plain reject, not an
    exception for the common case of a client-supplied string."""
    try:
        course_dir = _course_dir(course_id, user)
    except InvalidCourseIdError:
        return False
    return (course_dir / "syllabus.json").exists()


def course_or_draft_exists(course_id: str, user) -> bool:
    """True if course_id exists as either a real course or a draft class for
    this user."""
    try:
        course_dir = _course_dir(course_id, user)
    except InvalidCourseIdError:
        return False
    return (course_dir / "syllabus.json").exists() or (course_dir / "course.json").exists()


def delete_course(course_id: str, user) -> None:
    """Deletes courses/<user.pk>/<course_id>/ entirely — syllabus, notes,
    references, sessions, quiz history, mastery scores, grades, calendar
    sync records, flashcard progress, custom events, and notifications, all
    scoped to this user. Raises CourseNotFoundError if course_id exists as
    neither a draft nor a real course for this user. Irreversible; callers
    are responsible for confirming with the user before calling this
    (plan-then-pause per CLAUDE.md)."""
    course_dir = _course_dir(course_id, user)
    if not (course_dir / "course.json").exists() and not (course_dir / "syllabus.json").exists():
        raise CourseNotFoundError(f"no course '{course_id}' found")
    shutil.rmtree(course_dir)
    delete_course_state(course_id, user)


def delete_course_state(course_id: str, user) -> None:
    from django.db import transaction
    from agent.models import (
        CalendarSyncRecord,
        CourseSession,
        CustomEvent,
        FlashcardProgress,
        GradeItem,
        MasteryScore,
        Notification,
        QuizAttempt,
        SavedSite,
    )

    user_filter = _flashcard_user_filter(user)
    with transaction.atomic():
        FlashcardProgress.objects.filter(course_id=course_id, **user_filter).delete()
        GradeItem.objects.filter(course_id=course_id, **user_filter).delete()
        CalendarSyncRecord.objects.filter(course_id=course_id, **user_filter).delete()
        CustomEvent.objects.filter(course_id=course_id, **user_filter).delete()
        Notification.objects.filter(course_id=course_id, **user_filter).delete()
        QuizAttempt.objects.filter(course_id=course_id, **user_filter).delete()
        MasteryScore.objects.filter(course_id=course_id, **user_filter).delete()
        CourseSession.objects.filter(course_id=course_id, **user_filter).delete()
        SavedSite.objects.filter(course_id=course_id, **user_filter).delete()


def rename_course(course_id: str, course_name: str, user) -> None:
    """Updates course_name in place — course.json for a draft, syllabus.json
    for a real course, whichever exists for this user. Raises
    CourseNotFoundError if neither exists."""
    course_dir = _course_dir(course_id, user)
    course_path = course_dir / "course.json"
    syllabus_path = course_dir / "syllabus.json"

    if course_path.exists():
        data = json.loads(course_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        course_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return

    if syllabus_path.exists():
        data = json.loads(syllabus_path.read_text(encoding="utf-8"))
        data["course_name"] = course_name
        syllabus_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return

    raise CourseNotFoundError(f"no course '{course_id}' found")
```

This also fixes the pre-existing bug (found during research) where `delete_course_state` filtered every DB model only by `course_id`, with no `user` filter at all — meaning deleting one user's `cs101` would have silently wiped every other user's grades/flashcards/etc. for any course sharing that `course_id` string. That bug was latent (harmless) under the old single-owner model and becomes a real cross-student data-loss risk the moment storage is user-scoped, so it must be fixed in this same task, not deferred.

- [ ] **Step 2: Fix this file's own direct tests**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_course_drafts.py -v`

Fix each failure using the same pattern as Task 2 Step 4 (add/reuse a `django_user_model`-created `user`, pass it as the new required argument, mark `@pytest.mark.django_db` if needed). Repeat until green.

- [ ] **Step 3: Add a regression test for the delete_course_state cross-user fix**

```python
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
```

Add this to `agent/tests/test_course_drafts.py`.

- [ ] **Step 4: Run it**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_course_drafts.py -v`
Expected: PASS, including the new regression test.

- [ ] **Step 5: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: fewer failures than Task 2's baseline.

- [ ] **Step 6: Commit**

```bash
git add agent/services/storage.py agent/tests/test_course_drafts.py
git commit -m "fix: scope course-management functions and delete_course_state by user"
```

---

### Task 4: Thread `user` through course-listing and its dependents

**Files:**
- Modify: `agent/services/reminders.py:19-98` (`list_courses`, `list_draft_courses`, `upcoming_deadlines`, `list_all_deadlines`)
- Modify: `agent/services/dashboard.py:55-144` (`_note_topics`, `_course_summary`, `build_dashboard`)
- Modify: `agent/services/grades.py:26-30,270-290` (`_require_syllabus` and its 5 callers, `all_courses_summary`)
- Modify: `agent/services/streak.py:35-50` (`current_streak`)
- Test: `agent/tests/test_reminders.py`, `agent/tests/test_dashboard.py`, `agent/tests/test_grades.py`, `agent/tests/test_streak.py`

**Interfaces:**
- Consumes: `_course_dir(course_id, user)` is no longer used directly here, but `storage.read_syllabus(course_id, user)`, `storage.read_notes(course_id, user)` (from Task 2) are.
- Produces: `list_courses(user) -> list`, `list_draft_courses(user) -> list`, `upcoming_deadlines(user, within_days=None, course_ids=None) -> list`, `list_all_deadlines(user=None, course_id=None)` (signature unchanged — already had `user`, only its body changes to thread it further).

- [ ] **Step 1: Update reminders.py**

```python
def list_courses(user) -> list:
    """Returns every course_id that has a syllabus.json for this user, sorted."""
    user_dir = storage.COURSES_DIR / str(user.pk)
    if not user_dir.exists():
        return []
    return sorted(
        p.name for p in user_dir.iterdir()
        if p.is_dir() and (p / "syllabus.json").exists()
    )


def list_draft_courses(user) -> list:
    """Returns every course as {"course_id", "course_name", "created_at"}
    for this user that has course.json but not syllabus.json — a class
    with a name but no syllabus uploaded yet — sorted by course_id. A
    course.json that fails to parse is skipped rather than raising,
    matching list_courses()'s "never fail the whole scan over one bad
    entry" shape."""
    user_dir = storage.COURSES_DIR / str(user.pk)
    if not user_dir.exists():
        return []
    drafts = []
    for p in sorted(user_dir.iterdir(), key=lambda p: p.name):
        if not p.is_dir():
            continue
        if (p / "syllabus.json").exists():
            continue
        course_json = p / "course.json"
        if not course_json.exists():
            continue
        try:
            parsed = json.loads(course_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(parsed, dict) or "course_id" not in parsed:
            continue
        drafts.append(parsed)
    return drafts
```

Update `upcoming_deadlines` (keep everything else in the function body identical — only the signature and the two lines shown change):

```python
def upcoming_deadlines(user, within_days: int = None, course_ids: list = None) -> list:
    """Returns [{"course_id", "date", "title", "type"}, ...] across all (or
    the given) of this user's courses, sorted by date. Only today-or-later
    dates are included; within_days caps how far into the future, or None
    for no cap."""
    today = date.today()
    cutoff = today + timedelta(days=within_days) if within_days is not None else None

    courses = course_ids if course_ids is not None else list_courses(user)

    deadlines = []
    for course_id in courses:
        syllabus = storage.read_syllabus(course_id, user)
        # ... rest of the loop body is unchanged from the current implementation
```

Update `list_all_deadlines`'s one call site (around line 113, inside the function body — keep the rest unchanged):

```python
    course_ids = [course_id] if course_id else None
    syllabus_deadlines = upcoming_deadlines(user, within_days=None, course_ids=course_ids)
```

- [ ] **Step 2: Update dashboard.py**

```python
def _note_topics(course_id: str, user) -> list:
    seen = set()
    topics = []
    for lecture in storage.read_notes(course_id, user):
        for chunk in lecture.get("chunks", []):
            topic = str(chunk.get("topic") or "").strip()
            if topic and topic not in seen:
                seen.add(topic)
                topics.append(topic)
    return topics
```

In `_course_summary(course_id: str, user=None)` (line 95), find its calls to `storage.read_syllabus(course_id)` (line 96), `storage.read_notes(course_id)` (line 105), and `_note_topics(course_id)` if present, and change each to pass `user`: `storage.read_syllabus(course_id, user)`, `storage.read_notes(course_id, user)`, `_note_topics(course_id, user)`.

In `build_dashboard(user=None)` (line 120), change the `for course_id in reminders.list_courses():` loop (line 126) to `for course_id in reminders.list_courses(user):`, and the `"drafts": reminders.list_draft_courses(),` call (line 144) to `"drafts": reminders.list_draft_courses(user),`.

- [ ] **Step 3: Update grades.py**

```python
def _require_syllabus(course_id: str, user) -> dict:
    syllabus = storage.read_syllabus(course_id, user)
    if syllabus is None:
        raise storage.CourseNotFoundError(f"no syllabus found for '{course_id}'")
    return syllabus
```

Update its 5 call sites (lines 50, 89, 109, 154, 217 — inside `current_grade`, `add_item`, `update_item`, `grade_needed`, `missable_by_category`, all of which already accept `user=None`) from `syllabus = _require_syllabus(course_id)` to `syllabus = _require_syllabus(course_id, user)`.

In `all_courses_summary(user=None)` (line 270), change `for course_id in reminders.list_courses():` (line 279) to `for course_id in reminders.list_courses(user):`, and the internal `syllabus = storage.read_syllabus(course_id)` (line 282) to `syllabus = storage.read_syllabus(course_id, user)`.

- [ ] **Step 4: Update streak.py**

In `current_streak(user=None)` (line 35), change `for course_id in reminders.list_courses():` (line 43) to `for course_id in reminders.list_courses(user):`.

- [ ] **Step 5: Fix these four files' own direct tests**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_reminders.py agent/tests/test_dashboard.py agent/tests/test_grades.py agent/tests/test_streak.py -v`

Fix each failure with the same pattern as Task 2 Step 4. Repeat until this filtered run is green.

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: fewer failures than Task 3's baseline.

- [ ] **Step 7: Commit**

```bash
git add agent/services/reminders.py agent/services/dashboard.py agent/services/grades.py agent/services/streak.py agent/tests/
git commit -m "feat: scope course listing, dashboard, and streak by user"
```

---

### Task 5: Thread `user` through the LLM-calling service layer

**Files:**
- Modify: `agent/services/chunk_notes.py:178-186` (`chunk_notes_async`)
- Modify: `agent/services/references.py:32,38` (`ingest_reference`)
- Modify: `agent/services/domain_suggestions.py:51-52` (`suggest_domains`)
- Modify: `agent/services/ask.py:376,415,416,421` (`ask_async`'s internal reads — `user` param already exists on this function)
- Modify: `agent/services/quiz.py:130-142,195-224,275-290` (`_all_chunks`, `generate_flashcards_async`, `generate_assessment_question_async`)
- Modify: `agent/services/sessions.py:127-131` (`create_session`'s internal read — `user` param already exists)
- Test: `agent/tests/test_syllabus_extraction.py`, `agent/tests/test_references.py`, `agent/tests/test_domain_suggestions.py`, `agent/tests/test_quiz.py`, plus `agent/tests/test_ask.py`/`test_ask_grounding.py` (already exercised in the earlier prompt-caching change and should mostly still pass — rerun to confirm)

**Interfaces:**
- Consumes: `storage.read_syllabus(course_id, user)`, `storage.read_notes(course_id, user)`, `storage.read_reference(course_id, reference_id, user)`, `storage.read_references(course_id, user)`, `storage.read_trusted_domains(course_id, user)` from Task 2.
- Produces: `chunk_notes_async(course_id, lecture_id, source_text, source_type, lecture_date=None, user=None) -> dict`, `ingest_reference(course_id, file_bytes, filename, user, title=None) -> dict`, `suggest_domains(course_id, user) -> list[str]`, `_all_chunks(course_id, user) -> list`.

- [ ] **Step 1: chunk_notes.py**

Change the signature (line 178) to add `user=None` as the last parameter, and change the internal call (line 186) from `storage.read_syllabus(course_id)` to `storage.read_syllabus(course_id, user)`. Both calls are inside `await sync_to_async(...)`, so the wrapped function receives `user` as a normal closure argument — no `sync_to_async` signature change needed.

- [ ] **Step 2: references.py**

`ingest_reference` (line 38) generates a unique `reference_id` by looping `while storage.read_reference(course_id, candidate) is not None:` (line 32) — this needs `user` in scope before that loop runs. Add `user` as a required parameter (placed after `filename`, before the keyword-defaulted `title`): `async def ingest_reference(course_id: str, file_bytes: bytes, filename: str, user, title: str = None) -> dict:`, and change line 32 to `storage.read_reference(course_id, candidate, user)`.

- [ ] **Step 3: domain_suggestions.py**

Add `user` as a required parameter to `suggest_domains` (line 51): `async def suggest_domains(course_id: str, user) -> list[str]:`, and change line 52 to `storage.read_syllabus(course_id, user)`.

- [ ] **Step 4: ask.py**

`ask_async` already has `user=None`. Change its four internal content reads:
- Line 376: `syllabus = await sync_to_async(storage.read_syllabus)(course_id)` → `storage.read_syllabus)(course_id, user)`
- Line 415: `notes = await sync_to_async(storage.read_notes)(course_id)` → `storage.read_notes)(course_id, user)`
- Line 416: `references = await sync_to_async(storage.read_references)(course_id)` → `storage.read_references)(course_id, user)`
- Line 421: `approved_domains = await sync_to_async(storage.read_trusted_domains)(course_id)` → `storage.read_trusted_domains)(course_id, user)`

- [ ] **Step 5: quiz.py**

```python
def _all_chunks(course_id: str, user) -> list:
    """Returns [{"lecture_id", "chunk_id", "topic", "text"}, ...] flattened
    across every lecture's chunked notes for this course."""
    chunks = []
    for lecture in storage.read_notes(course_id, user):
        for c in lecture.get("chunks", []):
            chunks.append({
                "lecture_id": lecture.get("lecture_id"),
                "chunk_id": c.get("id"),
                "topic": c.get("topic"),
                "text": c.get("text"),
            })
    return chunks
```

In `generate_flashcards_async` (already has `user=None`), update its three content calls: `storage.read_syllabus(course_id)` → `storage.read_syllabus(course_id, user)`, `_all_chunks(course_id)` → `_all_chunks(course_id, user)`, `storage.read_trusted_domains(course_id)` → `storage.read_trusted_domains(course_id, user)`.

In `generate_assessment_question_async` (already has `user=None`), update its calls the same way: `storage.read_syllabus(course_id)` → `storage.read_syllabus(course_id, user)`, and its own `_all_chunks(course_id)` call → `_all_chunks(course_id, user)`. Also check `pick_chunk(course_id, topic, user=user)` (already passes `user`) — open `quiz.py` and confirm `pick_chunk`'s own body calls `_all_chunks(course_id)`; if so, update that internal call to `_all_chunks(course_id, user)` too (its signature already accepts `user`, per the CLI-inventory research).

- [ ] **Step 6: sessions.py**

In `create_session(course_id: str, user=None)` (already has `user`), change line 131 from `syllabus = storage.read_syllabus(course_id)` to `syllabus = storage.read_syllabus(course_id, user)`. Grep this file for any other bare `storage.read_syllabus(course_id)` / `storage.read_notes(course_id)` calls beyond the one found during research (line 131) and apply the same fix if any exist: `grep -n "storage\.read_" agent/services/sessions.py`.

- [ ] **Step 7: Fix these files' own direct tests**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_syllabus_extraction.py agent/tests/test_references.py agent/tests/test_domain_suggestions.py agent/tests/test_quiz.py agent/tests/test_ask.py agent/tests/test_ask_grounding.py -v`

Fix each failure with the same pattern as Task 2 Step 4. Repeat until this filtered run is green.

- [ ] **Step 8: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: only `agent/views.py` and CLI-command-dependent tests still failing (Tasks 6-7 fix those).

- [ ] **Step 9: Commit**

```bash
git add agent/services/chunk_notes.py agent/services/references.py agent/services/domain_suggestions.py agent/services/ask.py agent/services/quiz.py agent/services/sessions.py agent/tests/
git commit -m "feat: thread user through the LLM-calling service layer's content reads"
```

---

### Task 6: Thread `request.user` through views.py

**Files:**
- Modify: `agent/views.py` — 23 call sites across `ExtractSyllabusView`, `CourseView`, `ChunkNotesView`, `ReferencesView`, `DomainSuggestionsView`, `DomainsView`, `GradingConfigView`, `FlashcardProgressView`, `FlashcardProgressResetView`, `SyllabusDetailView`, `DeadlinesView`, `CustomEventDetailView`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: every content-family function signature from Tasks 2, 3, and 5.

- [ ] **Step 1: Apply the following exact call-site changes**

| # | Line | View | Before | After |
|---|---|---|---|---|
| 1 | 137 | `ExtractSyllabusView.post` | `await sync_to_async(storage.read_syllabus)(course_id)` | `await sync_to_async(storage.read_syllabus)(course_id, request.user)` |
| 2 | 159 | `ExtractSyllabusView.post` | `data = await extract_syllabus_async(text, course_id, course_name_hint)` | unchanged — `extract_syllabus_async` has no internal storage call (confirmed during research); leave as-is |
| 3 | 173 | `ExtractSyllabusView.post` | `await sync_to_async(storage.write_syllabus)(course_id, data, overwrite=True)` | `await sync_to_async(storage.write_syllabus)(course_id, data, request.user, overwrite=True)` |
| 4 | 211 | `CourseView.post` | `await sync_to_async(storage.write_course_draft)(course_id, course_name)` | `await sync_to_async(storage.write_course_draft)(course_id, course_name, request.user)` |
| 5 | 230 | `CourseView.patch` | `await sync_to_async(storage.rename_course)(course_id, course_name)` | `await sync_to_async(storage.rename_course)(course_id, course_name, request.user)` |
| 6 | 240 | `CourseView.delete` | `await sync_to_async(storage.delete_course)(course_id)` | `await sync_to_async(storage.delete_course)(course_id, request.user)` |
| 7 | 278 | `ChunkNotesView.post` | `await sync_to_async(storage.read_lecture)(course_id, lecture_id)` | `await sync_to_async(storage.read_lecture)(course_id, lecture_id, request.user)` |
| 8 | 300 | `ChunkNotesView.post` | `data = await chunk_notes.chunk_notes_async(course_id, lecture_id, text, source_type, lecture_date)` | `data = await chunk_notes.chunk_notes_async(course_id, lecture_id, text, source_type, lecture_date, user=request.user)` |
| 9 | 316 | `ChunkNotesView.post` | `await sync_to_async(storage.write_notes)(course_id, lecture_id, data, overwrite=True)` | `await sync_to_async(storage.write_notes)(course_id, lecture_id, data, request.user, overwrite=True)` |
| 10 | 346 | `ReferencesView.post` | `data = await references.ingest_reference(course_id, upload.read(), upload.name, title=title)` | `data = await references.ingest_reference(course_id, upload.read(), upload.name, request.user, title=title)` |
| 11 | 358 | `ReferencesView.post` | `await sync_to_async(storage.write_reference)(course_id, data["reference_id"], data)` | `await sync_to_async(storage.write_reference)(course_id, data["reference_id"], data, request.user)` |
| 12 | 369 | `ReferencesView.get` | `data = await sync_to_async(storage.read_references)(course_id)` | `data = await sync_to_async(storage.read_references)(course_id, request.user)` |
| 13 | 388 | `DomainSuggestionsView.post` | `domains = await domain_suggestions.suggest_domains(course_id)` | `domains = await domain_suggestions.suggest_domains(course_id, request.user)` |
| 14 | 410 | `DomainsView.get` | `domains = await sync_to_async(storage.read_trusted_domains)(course_id)` | `domains = await sync_to_async(storage.read_trusted_domains)(course_id, request.user)` |
| 15 | 432 | `DomainsView.put` | `await sync_to_async(storage.write_trusted_domains)(course_id, domains)` | `await sync_to_async(storage.write_trusted_domains)(course_id, domains, request.user)` |
| 16 | 497 | `GradingConfigView.get` | `syllabus = await sync_to_async(storage.read_syllabus)(course_id)` | `syllabus = await sync_to_async(storage.read_syllabus)(course_id, request.user)` |
| 17 | 528 | `GradingConfigView.put` | `await sync_to_async(storage.write_grading_config)(course_id, grading, grade_scale)` | `await sync_to_async(storage.write_grading_config)(course_id, grading, request.user, grade_scale=grade_scale)` |
| 18 | 774 | `FlashcardProgressView.patch` | `if await sync_to_async(storage.read_syllabus)(course_id) is None:` | `if await sync_to_async(storage.read_syllabus)(course_id, request.user) is None:` |
| 19 | 803 | `FlashcardProgressResetView.post` | `if await sync_to_async(storage.read_syllabus)(course_id) is None:` | `if await sync_to_async(storage.read_syllabus)(course_id, request.user) is None:` |
| 20 | 952 | `DeadlinesView.get` | `not await sync_to_async(storage.course_or_draft_exists)(course_id)` | `not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user)` |
| 21 | 956 | `DeadlinesView.get` | `reminders.list_all_deadlines)(user=request.user, course_id=course_id)` | unchanged — already passes `user`; its internals were fixed in Task 4 |
| 22 | 967 | `DeadlinesView.post` | `not await sync_to_async(storage.course_exists)(d["course_id"])` | `not await sync_to_async(storage.course_exists)(d["course_id"], request.user)` |
| 23 | 1016 | `CustomEventDetailView.patch` | `not await sync_to_async(storage.course_exists)(fields["course_id"])` | `not await sync_to_async(storage.course_exists)(fields["course_id"], request.user)` |
| 24 | 1098 | `SyllabusDetailView.get` | `data = await sync_to_async(storage.read_syllabus)(course_id)` | `data = await sync_to_async(storage.read_syllabus)(course_id, request.user)` |

Rows 2 and 21 are listed for completeness (confirmed no change needed) — do not skip re-reading them, since a stale assumption here would silently leave a call broken.

Also verify (do not skip): `AskView` (already passes `user=request.user` to `ask_async` — Task 5 made `ask_async`'s internals use it, no view change needed) and `FlashcardsGenerateView` (already passes `user=request.user` to `quiz.generate_flashcards_async` — Task 5 made its internals use it, no view change needed).

- [ ] **Step 2: Run the view tests**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_views.py -v`

Fix any remaining failures using the same pattern as Task 2 Step 4 — `test_views.py`'s failures will mostly be missing test fixtures for authenticated users, which this test file likely already has a pattern for (check the top of the file for an existing `authenticated_client` or similar fixture before inventing a new one).

- [ ] **Step 3: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: only CLI-command tests (if any exist) still failing.

- [ ] **Step 4: Commit**

```bash
git add agent/views.py agent/tests/test_views.py
git commit -m "feat: thread request.user through views.py's content-family calls"
```

---

### Task 7: CLI owner resolution + update all 9 management commands

**Files:**
- Create: `agent/services/cli_owner.py`
- Modify: `agent/management/commands/extract_syllabus.py`, `sessions.py`, `ask.py`, `chunk_notes.py`, `mastery.py`, `quiz.py`, `reminders.py`, `domains.py`, `references.py`, `grades.py`
- Modify: `.env.example` (document the new `CLI_OWNER_EMAIL` var)
- Test: `agent/tests/test_cli_owner.py` (new)

**Interfaces:**
- Produces: `resolve_owner_user() -> django.contrib.auth.models.User` — raises `CommandError` with a clear message if `CLI_OWNER_EMAIL` is unset or no matching `User` exists.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for agent/services/cli_owner.py's owner-resolution helper."""
import pytest
from django.core.management.base import CommandError

from agent.services import cli_owner


@pytest.mark.django_db
def test_resolve_owner_user_finds_user_by_email(monkeypatch, django_user_model):
    django_user_model.objects.create_user(username="abc123", email="dev@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "dev@example.com")
    user = cli_owner.resolve_owner_user()
    assert user.email == "dev@example.com"


def test_resolve_owner_user_raises_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("CLI_OWNER_EMAIL", raising=False)
    with pytest.raises(CommandError, match="CLI_OWNER_EMAIL"):
        cli_owner.resolve_owner_user()


@pytest.mark.django_db
def test_resolve_owner_user_raises_when_no_matching_user(monkeypatch):
    monkeypatch.setenv("CLI_OWNER_EMAIL", "nobody@example.com")
    with pytest.raises(CommandError, match="nobody@example.com"):
        cli_owner.resolve_owner_user()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_cli_owner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.services.cli_owner'`

- [ ] **Step 3: Write `agent/services/cli_owner.py`**

```python
"""Resolves the single 'owner' Django user the 9 CLI management commands
operate as. These commands are dev/debug tools only — real students always
go through the web API, where request.user comes from an authenticated
session. The CLI has no such session, so it needs one designated account
instead, chosen the same way the rest of the app identifies people: by
email (CLAUDE.md/README's existing ALLOWED_GOOGLE_EMAILS convention), not
username or a --user flag."""

import os

from django.contrib.auth.models import User
from django.core.management.base import CommandError


def resolve_owner_user() -> User:
    """Returns the User whose email matches CLI_OWNER_EMAIL. Raises
    CommandError (not a raw exception) if the env var is unset or no
    matching user exists yet — fails loudly with an actionable message,
    per CLAUDE.md's "fails loudly" convention, since a silent fallback here
    would write CLI output into the wrong (or a newly-created) user's
    course directory."""
    email = os.environ.get("CLI_OWNER_EMAIL")
    if not email:
        raise CommandError(
            "CLI_OWNER_EMAIL environment variable is not set — the CLI commands need "
            "one designated owner account to operate as. Set it to the email of your "
            "own Google-signed-in account, e.g.: set CLI_OWNER_EMAIL=you@example.com"
        )
    try:
        return User.objects.get(email=email)
    except User.DoesNotExist:
        raise CommandError(
            f"no user found with email '{email}' — sign in through the web UI with "
            "this Google account at least once first, so its User row exists."
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_cli_owner.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update each of the 9 commands**

Add `from agent.services.cli_owner import resolve_owner_user` to each file's imports, and `owner = resolve_owner_user()` as the first line of `handle()` (or of each helper method that makes a content-family call, for commands like `sessions.py`/`mastery.py`/`domains.py`/`grades.py` that dispatch to per-flag helper methods). Then thread `owner` into every call listed below (grouped by file):

**`extract_syllabus.py`** — in `handle()`:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    source_path = Path(options["source"])
    ...
    try:
        data = asyncio.run(
            extract_syllabus_async(text, options["course_id"], options["course_name"])
        )
    ...
    try:
        existing = storage.read_syllabus(options["course_id"], owner)
    ...
    out_path = storage.write_syllabus(options["course_id"], data, owner, overwrite=True)
```

**`sessions.py`** — pass `owner` into `_create`/`_list`/`_show`:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_id = options["course_id"]
    if options["create"]:
        self._create(course_id, owner)
    elif options["list"]:
        self._list(course_id, owner)
    else:
        self._show(course_id, options["show"], owner)

def _create(self, course_id, owner):
    try:
        session = sessions.create_session(course_id, user=owner)
    ...

def _list(self, course_id, owner):
    try:
        summaries = sessions.list_sessions(course_id, user=owner)
    ...

def _show(self, course_id, session_id, owner):
    try:
        session = sessions.get_session(course_id, session_id, user=owner)
    ...
```

**`ask.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    try:
        result = asyncio.run(
            ask_async(options["course_id"], options["question"], session_id=options["session_id"], user=owner)
        )
```

**`chunk_notes.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    ...
    data = asyncio.run(
        chunk_notes.chunk_notes_async(
            options["course_id"], options["lecture_id"], text, source_type, options["date"], user=owner,
        )
    )
    ...
    existing = storage.read_lecture(options["course_id"], options["lecture_id"], owner)
    ...
    out_path = storage.write_notes(options["course_id"], options["lecture_id"], data, owner, overwrite=True)
```

**`mastery.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_id = options["course_id"]
    if options["rebuild"]:
        self._rebuild(course_id, owner)
    else:
        self._weak_topics(course_id, options["limit"], owner)

def _rebuild(self, course_id, owner):
    data = mastery.rebuild_scores(course_id, user=owner)
    ...

def _weak_topics(self, course_id, limit, owner):
    scores = mastery.weak_topics(course_id, limit=limit, user=owner)
    ...
```

**`quiz.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_id = options["course_id"]
    q = asyncio.run(
        quiz.generate_question_async(course_id, topic=options["topic"], chunk_id=options["chunk_id"], user=owner)
    )
    ...
    result = quiz.record_attempt(
        course_id, q["lecture_id"], q["chunk_id"], q["topic"],
        q["question"], q["correct_answer"], user_answer, user=owner,
    )
```

**`reminders.py`** — this command calls `upcoming_deadlines(within_days=..., course_ids=...)`, whose Task 4 signature became `upcoming_deadlines(user, within_days=None, course_ids=None)`:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_ids = [options["course_id"]] if options["course_id"] else None
    deadlines = reminders.upcoming_deadlines(owner, within_days=options["within_days"], course_ids=course_ids)
```

**`domains.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_id = options["course_id"]
    if options["suggest"]:
        self._suggest(course_id, owner)
    else:
        self._approve(course_id, options["approve"], owner)

def _suggest(self, course_id, owner):
    domains = asyncio.run(domain_suggestions.suggest_domains(course_id, owner))
    ...

def _approve(self, course_id, raw_domains, owner):
    ...
    out_path = storage.write_trusted_domains(course_id, domains, owner)
```

**`references.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    ...
    data = asyncio.run(
        references.ingest_reference(
            options["course_id"], source_path.read_bytes(), source_path.name, owner, title=options["title"],
        )
    )
    ...
    out_path = storage.write_reference(options["course_id"], data["reference_id"], data, owner)
```

**`grades.py`**:
```python
def handle(self, *args, **options):
    owner = resolve_owner_user()
    course_id = options["course_id"]

    if options["set_grading"]:
        ...
        storage.write_grading_config(course_id, grading, owner, grade_scale=grade_scale)
        ...

    if options["add"]:
        component, title, score, max_points = options["add"]
        item = grades.add_item(course_id, component, title, float(score), float(max_points), options["date"], user=owner)
        ...

    if options["list"]:
        grade = grades.current_grade(course_id, user=owner)
        for item in storage.read_grades(course_id, user=owner)["items"]:
            ...

    if options["whatif"] is not None:
        needed = grades.grade_needed(course_id, options["whatif"], user=owner)
        missable = grades.missable_by_category(course_id, options["whatif"], user=owner)
```

- [ ] **Step 6: Add `.env.example` documentation**

Add this line to `.env.example` near the existing `ALLOWED_GOOGLE_EMAILS` entry:
```
# Email of the Django user the CLI management commands (extract_syllabus, chunk_notes,
# ask, quiz, mastery, references, reminders, sessions, domains, grades) operate as.
# These commands are dev/debug tools only, not used by real students. Must match a
# user who has already signed in through the web UI at least once.
CLI_OWNER_EMAIL=you@example.com
```

- [ ] **Step 7: Manual smoke test (no automated test harness exists for CLI commands per the research — confirm by hand)**

```bash
set CLI_OWNER_EMAIL=<your real signed-in email>
venv/Scripts/python.exe manage.py extract_syllabus test-syllabi/cs101_clean.txt cs101-cli-smoke-test --course-name "CLI Smoke Test" --force
```
Expected: succeeds and prints `Wrote <...>\courses\<your user id>\cs101-cli-smoke-test\syllabus.json` — confirming the new nested path.

- [ ] **Step 8: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: green, or only Task 8's migration command (not yet written) missing.

- [ ] **Step 9: Commit**

```bash
git add agent/services/cli_owner.py agent/management/commands/ agent/tests/test_cli_owner.py .env.example
git commit -m "feat: resolve a designated owner user for the CLI management commands"
```

---

### Task 8: One-time on-disk migration for existing course data

**Files:**
- Create: `agent/management/commands/migrate_course_ownership.py`
- Test: `agent/tests/test_migrate_course_ownership.py` (new)

**Interfaces:**
- Produces: a `migrate_course_ownership` management command, idempotent, dry-run by default.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the one-time migrate_course_ownership command that moves
existing flat courses/<course_id>/ directories into the new
courses/<owner.pk>/<course_id>/ layout."""
import json

import pytest
from django.core.management import call_command

from agent.services import cli_owner, storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


@pytest.mark.django_db
def test_migrate_moves_flat_course_dir_under_owner(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text(
        json.dumps({"course_id": "cs101", "course_name": "Intro to CS", "dates": [], "grading": [], "topics": []}),
        encoding="utf-8",
    )

    call_command("migrate_course_ownership", "--apply")

    new_path = isolated_courses_dir / str(owner.pk) / "cs101" / "syllabus.json"
    assert new_path.exists()
    assert not old_course_dir.exists()


@pytest.mark.django_db
def test_migrate_is_a_dry_run_by_default(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership")

    assert old_course_dir.exists()
    assert not (isolated_courses_dir / str(owner.pk)).exists()


@pytest.mark.django_db
def test_migrate_skips_a_non_course_top_level_file(isolated_courses_dir, monkeypatch, django_user_model):
    django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    (isolated_courses_dir / "custom_events.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership", "--apply")

    assert (isolated_courses_dir / "custom_events.json").exists()


@pytest.mark.django_db
def test_migrate_is_idempotent(isolated_courses_dir, monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(username="owner", email="owner@example.com")
    monkeypatch.setenv("CLI_OWNER_EMAIL", "owner@example.com")

    old_course_dir = isolated_courses_dir / "cs101"
    old_course_dir.mkdir()
    (old_course_dir / "syllabus.json").write_text("{}", encoding="utf-8")

    call_command("migrate_course_ownership", "--apply")
    call_command("migrate_course_ownership", "--apply")  # should no-op the second time, not error

    assert (isolated_courses_dir / str(owner.pk) / "cs101" / "syllabus.json").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_migrate_course_ownership.py -v`
Expected: FAIL — command not found.

- [ ] **Step 3: Write the command**

```python
"""One-time migration: moves each existing flat courses/<course_id>/
directory (from before storage became user-scoped) into
courses/<owner.pk>/<course_id>/. Safe to re-run — already-migrated or
non-course entries are skipped, not errored on. Dry-run by default; pass
--apply to actually move directories."""

from django.core.management.base import BaseCommand

from agent.services import storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Moves existing flat courses/<course_id>/ directories under courses/<owner.pk>/<course_id>/."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually move directories (default: dry-run preview only).")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        courses_dir = storage.COURSES_DIR
        if not courses_dir.exists():
            self.stdout.write("courses/ does not exist yet — nothing to migrate.")
            return

        owner_dir = courses_dir / str(owner.pk)
        to_move = []
        for entry in sorted(courses_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                self.stdout.write(f"skip (not a directory): {entry.name}")
                continue
            if entry == owner_dir or entry.name.isdigit():
                self.stdout.write(f"skip (already looks migrated): {entry.name}")
                continue
            if not (entry / "syllabus.json").exists() and not (entry / "course.json").exists():
                self.stdout.write(f"skip (not a course directory): {entry.name}")
                continue
            to_move.append(entry)

        if not to_move:
            self.stdout.write(self.style.SUCCESS("Nothing to migrate."))
            return

        for entry in to_move:
            destination = owner_dir / entry.name
            if options["apply"]:
                owner_dir.mkdir(parents=True, exist_ok=True)
                entry.rename(destination)
                self.stdout.write(self.style.SUCCESS(f"moved {entry.name} -> {destination}"))
            else:
                self.stdout.write(f"would move: {entry.name} -> {destination}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nDry run only — re-run with --apply to actually move these directories."))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_migrate_course_ownership.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run it for real against this project's actual `courses/` directory**

```bash
set CLI_OWNER_EMAIL=<your real signed-in email>
venv/Scripts/python.exe manage.py migrate_course_ownership
```
Review the dry-run output — it should list `computer-graphics-algorithms`, `formal-languages`, `privacy-in-data-science`, `software-engineering-and-design` as "would move", and `custom_events.json` as "skip (not a directory)". Confirm this matches expectations, then:
```bash
venv/Scripts/python.exe manage.py migrate_course_ownership --apply
```

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: fully green.

- [ ] **Step 7: Commit**

```bash
git add agent/management/commands/migrate_course_ownership.py agent/tests/test_migrate_course_ownership.py
git commit -m "feat: add one-time migration command for the new per-user course layout"
```

---

### Task 9: Full regression pass and manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite one more time from a clean state**

Run: `venv/Scripts/python.exe -m pytest agent/tests/ -q`
Expected: `N passed, M skipped` with zero failures (compare `N` to the pre-refactor baseline of 322 passed, 9 skipped noted earlier in this project's history — the count should be equal or higher, never lower, since Tasks 1-8 only added tests).

- [ ] **Step 2: Manual smoke test via the running server, as two different signed-in users**

```bash
./scripts/run_server.sh
```
In a browser, sign in as your real Google account, create a course `cs101`, upload a syllabus, and confirm it appears. Then sign in as a *second* allowed Google account (add a second email to `ALLOWED_GOOGLE_EMAILS` temporarily if needed), also create a course `cs101` with different content, and confirm:
- The second account's `cs101` does not show the first account's syllabus/notes/grades.
- Both accounts' `courses/<their own pk>/cs101/` directories exist independently on disk.
- Deleting the second account's `cs101` does not remove the first account's grades (regression-tests Task 3's bug fix end-to-end, not just at the unit level).

- [ ] **Step 3: Report findings**

If the manual smoke test surfaces anything the automated suite didn't catch, add a regression test for it before considering this plan complete — do not fix silently without a test, per this project's TDD convention (see `superpowers:test-driven-development`).
