# Faculty View — Excel Import + AI Academic Planning

**Status doc**, not a pre-work plan — this records what was actually built
against the original 6-task plan, including deviations. All six tasks are
now complete. See git log on `feature/ontrack-mvp-expansion` for the commits
this describes.

**Goal (unchanged from the original plan):** faculty upload a program-
requirements Excel file, review/confirm the extracted structure, then use
Cora in a chat interface to draft an academic plan for a student's intended
major and supplied academic details. Student-specific data is never
persisted to disk or the database — everything Cora learns about a specific
student during planning lives only in the faculty member's session.

## What's done

### Task 1 — Role field + `FacultyPermission` (commit: "Add faculty role and FacultyPermission")
- `UserSettings.role` (`student`/`faculty`, default `student`) — migration `0034_add_user_role`.
- `agent.authentication.is_faculty()` / `FacultyPermission`, same shape as `is_pilot_owner`/`PilotOwnerPermission` (404-on-deny, not 403 — conceals the surface rather than just blocking it).
- **Deviation:** the plan's Step 4 asked for a `faculty_planner_page` view/URL gated the same way as `analytics-page`, built *now*. Skipped — there's no template yet (that's Task 5), and `_render_page` needs a real `PAGE_SCRIPTS` JS asset per page name, so a stub would either 500 or need throwaway files deleted a task later. Instead, `FacultyPermission` is tested directly against a DRF request/view (`agent/tests/test_faculty_role.py`), including a role-flip-mid-session case mirroring `test_suspended_mid_session_is_rejected_on_next_request`. The exact gate to replicate in Task 5 is confirmed: `agent/page_views.py`'s `analytics_page` does `if not is_pilot_owner(request.user): raise Http404()` before rendering.

### Task 2 — Program-requirements schema + extraction service (commit: "Add program requirements Excel extraction service")
- `agent/services/requirements_extraction.py`: `extract_requirements_async(source_bytes, filename, user=None) -> dict`, same async/JSON-envelope shape and never-fabricate prompt discipline as `syllabus_extraction.py`. `MalformedRequirementsSourceError` covers unreadable/empty `.xlsx`/`.xlsm`.
- Added `openpyxl` to `requirements.txt` (new dependency).
- CLI harness: `manage.py extract_requirements <path>`.
- **Deviation:** the plan asked for "2-3 real program-requirements Excel files" as fixtures. None were available, so two synthetic ones were built instead (`test-programs/bscs_clean.xlsx`, `test-programs/psyc_messy.xlsx`) and run for real through the CLI harness against the live Anthropic key already configured in `.env`. Clean sheet extracted perfectly; messy sheet correctly dropped a course row with no code and left `catalog_year`/`total_credits_required` unset rather than guessing where the source said "TBD". **This has not been validated against an actual departmental requirements spreadsheet** — real ones may have layouts (merged cells, multi-row headers, footnotes) the synthetic fixtures don't exercise. Worth running a real one through the CLI command before trusting this further.

### Task 3 — `ProgramRequirement` model + import/confirm endpoints (commit: "Add ProgramRequirement model and import/confirm endpoints")
- `ProgramRequirement` model — migration `0035_add_program_requirement`. Unique on `(user, program_name, catalog_year)`.
- `POST /api/faculty/requirements/import/` (extract only, writes nothing) and `POST /api/faculty/requirements/confirm/` (create, or 409-with-summary-then-`overwrite: true` on a collision).
- **Deviation:** the plan's model used a field named `owner`. Renamed to `user` — every other model in `agent/models.py` with a FK to the user uses `user`, not `owner`; matching that convention seemed more valuable than following the plan's literal field name.

### Task 4 — Academic planner service + chat endpoint (commit: "Add academic planner chat, session-only student state")
- `agent/services/academic_planner.py`: `plan_chat_async(program_requirement, student_details, conversation, message, user=None) -> {"reply", "student_details", "draft_plan"}`. Refuses to draft until major + completed coursework are known; a post-response grounding check drops any model-proposed course not present in the `ProgramRequirement`'s `categories[].courses[]`, logging when it happens rather than surfacing a fabricated course.
- `POST /api/faculty/plan/chat/` and `POST /api/faculty/plan/reset/`, both `FacultyPermission`-gated. All student-specific state lives in `request.session["faculty_plan_session"]` only — verified with a test asserting the `ProgramRequirement` DB row is unchanged (no student name leaking into it) after a chat turn.
- Note for whoever builds Task 5's chat UI: session access from these async views is wrapped in `sync_to_async` (`_read_faculty_plan_session`/`_write_faculty_plan_session`/`_clear_faculty_plan_session` in `agent/views.py`) — the db-backed session store does a synchronous DB read/write, which raises `SynchronousOnlyOperation` if touched directly from `async def` view methods. Follow that pattern for any new session-touching view rather than accessing `request.session` directly.

### One assumption worth flagging
The original plan's framing said this feature applies "the same rule already applied to grades and chat transcripts elsewhere in OnTrack" (i.e. never persisted). That's not accurate for this repo as it stands: `GradeItem` and `SessionMessage` are both ordinary DB-persisted models today. This didn't change anything here — the session-only design for faculty planning stands on its own reasoning regardless — but it's worth knowing that assumption doesn't hold if it mattered for a decision elsewhere.

### Task 5 — Templates
- `faculty_planner_page` (`/faculty/cora/`, URL name `faculty-planner`) — the working planner UI: reuses `materials-upload-card-unified` for the Excel import, `materials-library`-style rows for a faculty member's own confirmed `ProgramRequirement`s (loaded server-side via `_render_page`'s `program_requirements` context, scoped to `request.user`), `syllabus-review`/`review-row` styling for the editable extraction review (add/remove category and course rows, all client-side state collected back into the schema shape before POSTing to confirm), a 409-collision "Overwrite confirmed version" flow, and a two-pane chat + live draft-plan preview wired to the Task 4 endpoints. New CSS lives in `app.css` under a "Faculty planner" section (reuses existing tokens/classes rather than a parallel design system).
- `faculty_dashboard_page` (`/faculty/`, name `faculty-dashboard`) and `faculty_import_page` (`/faculty/import/`, name `faculty-import`) — an entry-point dashboard and a second "Import Data" page. Faculty accounts are redirected from `dashboard-page` to `faculty-dashboard` instead of seeing the student dashboard, and the sidebar swaps to a faculty-only nav (Dashboard/Import Data/Cora/Templates/Settings) that hides every student nav item, consistent with role being a hard either/or rather than a toggle.
- Page gating replicates `analytics_page`'s exact pattern as anticipated in Task 1: `if not is_faculty(request.user): raise Http404()`.
- Added `POST-review` note: `_render_page` now fetches `UserSettings` once per request and passes it to both `_enabled_features` and `is_faculty(user, settings_row=...)`, rather than each doing its own `get_or_create` — see "Review findings" below.

### Task 6 — Export
- `agent/services/plan_export.py`: `render_plan_docx(draft_plan)` renders the session-only draft plan (major, semester tables, total credits, notes) as a DOCX via `python-docx`; `plan_filename()` slugifies the major for the download name.
- `POST /api/faculty/plan/export/`, `FacultyPermission`-gated, reads `draft_plan` from `request.session["faculty_plan_session"]` only (never a stored record — there isn't one) and streams the file with `Cache-Control: private, no-store`. 400s with a clear message if no draft exists yet.
- Verified by test that the exported DOCX contains the draft plan's real content but never the session's `student_details`/`conversation` fields — the export surface can't leak what the session already isn't supposed to persist.

## Review findings

Ran `/code-review` (medium effort) against the full Task 5-6 diff before writing this update. Findings:

1. **Fixed** — `agent/page_views.py`'s `_render_page` was doing two separate `UserSettings.objects.get_or_create()` queries per page load (`_enabled_features(request.user)` and `is_faculty(request.user)`, called one line apart), on every page render for every signed-in user, not just faculty. Fixed by fetching the row once (`_user_settings_row`) and threading it into both `_enabled_features(settings_row)` and `authentication.is_faculty(user, settings_row=...)` (the new `settings_row` param is optional, so `FacultyPermission` and every other existing caller of `is_faculty` are unaffected). Caught a real bug while fixing this: the first attempt put `from .models import UserSettings` inside `is_faculty`'s `if settings_row is None:` branch, which makes `UserSettings` a function-local name in Python regardless of which branch actually runs — `UnboundLocalError` on the branch where `settings_row` was already provided. Moved the import unconditionally to the top of the function. Full suite went 913 passed → 985 passed after the fix (74 tests had been failing on `page_views.py` calls generally, all from this one bug).
2. **Not fixed, flagging for a decision** — `faculty_import.html`/`faculty.js` (the "Import Data" page, linked prominently from the sidebar and the dashboard's quick-actions) is a non-functional mockup: the dropzone validates the file extension/size client-side and shows a filename, but never uploads anywhere — no `fetch`/`apiRequest` call exists in `faculty.js`. Its "Download sample file" button has no click handler at all. Meanwhile the *actual* working Excel import already lives one click away, inside `faculty_planner.html`'s Step 1 ("Import program requirements"), which really does call `/api/faculty/requirements/import/`. As shipped, a faculty member who clicks the prominent "Import Data" nav item lands on a page that looks functional and does nothing, while the real import is under a different label ("Cora") elsewhere. Worth deciding before this goes live: either wire `faculty_import.html` to the same import/confirm endpoints (duplicating Step 1's logic) and reroute it into the planner's review step, or drop the page and point "Import Data" straight at the planner.
3. **Minor, cosmetic** — `faculty_dashboard.html`'s "Try a prompt" links pass a `?q=...` query param to `faculty-planner`, but `faculty_planner.js` never reads `location.search` — clicking a suggested prompt opens the planner with an empty chat input, not the prompt pre-filled. The notification bell's "3" badge is also hardcoded, not backed by real data. Neither breaks anything; both read as unfinished polish on an otherwise-working page.

## Test coverage
`test_faculty_role.py`, `test_requirements_extraction.py`, `test_faculty_requirements_endpoints.py`, `test_academic_planner.py`, `test_faculty_plan_endpoints.py`, `test_faculty_planner_ui_export.py` — 42 new tests, all passing. Full suite: 985 passed, 8 skipped, 2 pre-existing failures unrelated to this work (`test_course_overview.py::test_overview_endpoint_returns_full_payload_for_owned_course`, `test_materials.py::test_retry_reprocesses_failed_syllabus_material_in_place` — both fail identically on the commit before this work started).

## Remaining before shipping
- Decide what to do about finding #2 above (the non-functional Import Data page) before faculty accounts are provisioned for real use.
- Extraction quality (Task 2) has still only been verified against synthetic fixtures, not a real departmental requirements spreadsheet — see Task 2's note above.
- No browser-visual verification was done in this environment (no browser tool available in-session); all verification here is via Django's test client (HTTP status, rendered HTML content, DOCX bytes) plus a manual code read-through, not an actual rendered page in a browser.
