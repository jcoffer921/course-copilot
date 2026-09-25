# Faculty View — Excel Import + AI Academic Planning

**Status doc**, not a pre-work plan — this records what was actually built
(Tasks 1-4 of the original 6-task plan) against the plan as given, including
deviations and what's still outstanding (Tasks 5-6, UI). See git log on
`feature/ontrack-mvp-expansion` for the four commits this describes.

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

## Test coverage added
`test_faculty_role.py`, `test_requirements_extraction.py`, `test_faculty_requirements_endpoints.py`, `test_academic_planner.py`, `test_faculty_plan_endpoints.py` — 33 new tests, all passing. Full suite: 976 passed, 2 pre-existing failures unrelated to this work (`test_course_overview.py::test_overview_endpoint_returns_full_payload_for_owned_course`, `test_materials.py::test_retry_reprocesses_failed_syllabus_material_in_place` — both fail identically on the commit before this work started).

## Not done yet

- **Task 5 — Templates.** `faculty_planner.html`, CSS reuse (`materials-upload-card-unified`, `materials-library`, `syllabus-review`/`review-row`, chat UI patterns), the `faculty_planner_page` view + `faculty-planner` URL name, and the sidebar nav entry. Also needs a small addition the original plan didn't spell out: a GET endpoint listing a faculty member's existing `ProgramRequirement` rows, for the "materials-library" selector — none of Tasks 1-4 added one since it wasn't in their explicit scope.
- **Task 6 — Export.** PDF/DOCX download of the session-only draft plan. Only relevant if Task 5 ships a planning UI to hang the download button off of.

Both are UI-heavy and lower-confidence to self-verify in this environment (no browser tool available in-session) — code-complete wouldn't mean visually-verified. Pick these up as a separate pass.
