# Faculty Studio Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four-page faculty area with a three-tab, Penn State-branded studio (Workspace, Programs, Templates) that takes a faculty member from an imported requirements file to an exportable AI draft plan on one screen.

**Architecture:** A new `faculty_base.html` shell (slim rail, top bar, token-driven `faculty_studio.css`) replaces the student sidebar for faculty pages. Workspace reuses the existing grounded chat/reset/export endpoints; pure plan-analysis functions live in one testable JS module. Programs adds list/detail/delete to the existing `program_requirements` service. Export formats extend `plan_export` with a layout allow-list. No new tables.

**Tech Stack:** Django 6 + DRF (adrf async views), pytest + pytest-django, vanilla ES modules, `node --test` for pure JS, python-docx.

**Spec:** `docs/superpowers/specs/2026-10-30-faculty-studio-redesign-design.md`

## Global Constraints

- Run Python tests with `venv/Scripts/python -m pytest <path> -v`; JS tests with `node --test agent/tests/js/`.
- Palette (spec section 4): Nittany Navy `#001E44` (`--rail`, `--accent-ink`), Beaver Blue `#1E407C` (`--accent`), Pugh Blue `#96BEE6` (`--accent-line`, never as text on white), `--accent-soft` about `#EAF2FB`. Cora stays violet `#5b3fc4`. No Penn State logo or wordmark.
- No emoji anywhere. Icons are inline SVG via the existing `ot-icon` sprite (`<svg class="ot-icon"><use href="#ot-icon-NAME"/></svg>`) or plain words.
- Student-specific state stays in `request.session["faculty_plan_session"]` and `sessionStorage`. Nothing student-specific goes to the DB, disk, or `localStorage`.
- Faculty API views use `permission_classes = [IsAuthenticated, ActiveAccessPermission, FacultyPermission]`; every query is scoped to `request.user`; foreign and missing IDs return identical `404`.
- Destructive writes require an explicit confirmation (project plan-then-pause rule).
- Commits: do NOT add a Co-Authored-By trailer (CLAUDE.md).
- Route names: `/faculty/` is `faculty-workspace`; `/faculty/programs/` is `faculty-programs`; `faculty-import` and `faculty-planner` stay as redirect routes.

## Review Focus

- A `?program=` value (page) or `<requirement_id>` (API) belonging to another faculty member, or malformed: Workspace silently shows no program; API returns `404`, indistinguishable from missing. (Tasks 3, 6)
- A program with zero categories or zero courses (the normalizer allows it): Programs detail and Workspace render, coverage is empty, nothing throws. (Tasks 2, 6, 7)
- Prerequisite conflict semantics: prerequisite in the same or a later term is flagged; prerequisite absent from the draft is not; a draft course missing from the program is ignored. (Task 2)
- Deleting the program an active planning session points at: session is cleared, and a later chat call returns the existing `404` without crashing the UI. (Tasks 6, 4)
- Export `format` omitted, unknown, or a draft plan with an empty `semesters` list: falls back to `term_table`, still returns a valid DOCX. (Task 10)

## File Structure

| File | Responsibility |
|---|---|
| `agent/templates/agent/faculty_base.html` (new) | Faculty shell: rail, top bar, avatar menu, shared includes. No page logic. |
| `agent/static/agent/css/faculty_studio.css` (new) | Tokens under `body[data-area="faculty"]`, shell, panels, tables, chips. |
| `agent/templates/agent/faculty_workspace.html`, `static/agent/js/faculty_workspace.js` (new) | Studio page; session store, chat, plan render, export/reset. |
| `agent/static/agent/js/faculty_plan_model.js` (new) | Pure functions over `(draft, program)`; no DOM. |
| `agent/static/agent/js/faculty_import_flow.js` (new) | Shared extract → review → confirm dialog. |
| `agent/templates/agent/faculty_programs.html`, `static/agent/js/faculty_programs.js` (new) | Programs list/detail/delete. |
| `agent/services/program_requirements.py` | Adds `list_for_user`, `get_for_user`, `delete_for_user`. |
| `agent/services/plan_export.py` | Adds layout parameter. |
| Removed in Task 12 | `faculty_dashboard.html`, `faculty_import.html`, `faculty_planner.html`, `faculty.js`, `faculty_planner.js`, `faculty.css`. |

---

## Milestone 1: Shell and Workspace

### Task 1: Faculty shell, routes, and navigation

**Files:**
- Create: `agent/templates/agent/faculty_base.html`, `agent/static/agent/css/faculty_studio.css`, `agent/templates/agent/faculty_programs.html` (placeholder heading only), `agent/tests/test_faculty_studio_pages.py`
- Modify: `agent/page_views.py` (PAGE_SCRIPTS, `modern_page_names`, `page_asset_version`, faculty views, `switch_view_page`), `agent/page_urls.py`, `agent/auth_views.py`, `agent/templates/agent/faculty_templates.html` (extend `faculty_base.html`, drop old header and bell), `agent/templates/agent/partials/sidebar.html` (remove faculty block), `agent/tests/test_faculty_access.py`, `agent/tests/test_admin_view_switch.py`, `agent/tests/test_faculty_templates_ui.py`
- Test: `agent/tests/test_faculty_studio_pages.py`

**Interfaces:**
- Produces: URL names `faculty-workspace` (`/faculty/`), `faculty-programs` (`/faculty/programs/`), `faculty-templates`; redirect names `faculty-import`, `faculty-planner`. Template `faculty_base.html` with blocks `faculty_title`, `faculty_actions`, `faculty_content`. View functions `faculty_workspace_page`, `faculty_programs_page` in `page_views.py`. `page_name` values `faculty-workspace`, `faculty-programs`, `faculty-templates`.

- [ ] **Step 1: Write failing tests** in `test_faculty_studio_pages.py` using the `client`, `faculty_user`, `student_user` fixtures pattern from `test_faculty_planner_ui_export.py`:
  - `test_workspace_programs_templates_are_faculty_only`: parametrized over the three names; anonymous → 302 to login; student → 404; faculty → 200.
  - `test_faculty_shell_has_faculty_identity`: response contains `data-area="faculty"`, `>FACULTY<`, `faculty_studio.css`; lacks `app-sidebar`, `>Courses<`, `>Calendar<`, `>Study<`, and the string `faculty-notification`.
  - `test_rail_lists_exactly_three_tabs_and_marks_active`: `>Workspace<`, `>Programs<`, `>Templates<` present; on the programs page the programs link carries `aria-current="page"`; the other two do not.
  - `test_old_urls_redirect`: `/faculty/import/` → 302 `reverse("faculty-programs")`; `/faculty/cora/` → 302 `reverse("faculty-workspace")`.
  - `test_no_emoji_in_faculty_shell`: no character above U+1F000 in any of the three pages' HTML.
- [ ] **Step 2: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py -v`. Expected: FAIL (`NoReverseMatch: faculty-workspace`).
- [ ] **Step 3: Implement.** `faculty_workspace_page(request)` and `faculty_programs_page(request)` follow `faculty_templates_page`'s `acts_as_faculty` → `Http404` gate and call `_render_page(... page_name="faculty-workspace" | "faculty-programs")`. `faculty_workspace_page` renders `faculty_workspace.html` (Task 3 creates it; here point it at a stub template extending `faculty_base.html` with a one-line heading so Task 1 is green). `faculty_import_page` and `faculty_planner_page` become `redirect(...)` views. Replace the `faculty-dashboard` route and rename every reference (`grep -rn "faculty-dashboard" agent config`): `dashboard_page`, `switch_view_page`, `auth_views.py`, the three test files. Add the new names to `PAGE_SCRIPTS` (`faculty_workspace.js`, `faculty_programs.js`; create empty placeholder files) and to `modern_page_names`. `faculty_base.html` includes `icon_symbols.html`, `{% csrf_token %}`, `toast_region.html`, `action_dialog.html`, loads the design-system CSS and `app.css` (needed by the shared toast/dialog partials), then `faculty_studio.css` last, and sets `<body data-page=... data-area="faculty">`. Rail items are `<a>` elements with `aria-label`, an `ot-icon` SVG, and `aria-current="page"` when active. `faculty_studio.css` defines the tokens from Global Constraints plus ok/warn/bad status tokens and the rail/top-bar/panel/chip/button base styles from the approved mockup (`studio-split-full.html`).
- [ ] **Step 4: Update the three existing test files** for renamed routes and the new shell (templates test: nav assertions now target the rail labels; drop the `app-nav-link` and `pwilliamson` assertions).
- [ ] **Step 5: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py agent/tests/test_faculty_access.py agent/tests/test_admin_view_switch.py agent/tests/test_faculty_templates_ui.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `git add -A agent && git commit -m "Add faculty studio shell, routes, and Penn State tokens"`

### Task 2: Plan analysis module (pure JS)

**Files:**
- Create: `agent/static/agent/js/faculty_plan_model.js`, `agent/tests/js/faculty_plan_model.test.mjs`

**Interfaces:**
- Produces (ES exports, no DOM, no imports). `program` is a `ProgramRequirement.requirements` object (`categories[].courses[]` with `code`, `credits`, `prerequisites`); `draft` is `{semesters:[{label, courses:[{code,title,credits}]}], total_credits, notes, student_major}`:
  - `courseCategoryMap(program) -> Object<code, categoryName>`
  - `categoryCoverage(draft, program) -> [{name, plannedCredits, creditsRequired}]` (one entry per program category, in order; `plannedCredits` sums the program's own credit values for draft courses in that category)
  - `prerequisiteConflicts(draft, program) -> [{code, semesterLabel, prerequisite}]`
  - `planSummary(draft, program) -> {plannedCredits, termCount, programCredits, issueCount}`

- [ ] **Step 1: Write failing tests** (load the module the way `calendar_layout.test.mjs` does, via a `data:` URL). Tests: `courseCategoryMap maps every code`, `categoryCoverage sums program credits per category and lists empty categories at zero`, `prerequisiteConflicts flags a prerequisite in the same semester`, `... flags a prerequisite in a later semester`, `... ignores a prerequisite absent from the draft`, `... ignores draft courses missing from the program`, `planSummary counts conflicts as issueCount`, `all functions accept a program with no categories and an empty semesters list` (assert `[]`/zeros, no throw).
- [ ] **Step 2: Run** `node --test agent/tests/js/faculty_plan_model.test.mjs`. Expected: FAIL (cannot read module).
- [ ] **Step 3: Implement** the four functions. Term order is array order; a conflict exists when the prerequisite's semester index is `>=` the course's.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add agent/static/agent/js/faculty_plan_model.js agent/tests/js && git commit -m "Add pure plan analysis module for faculty workspace"`

### Task 3: Workspace page, program selection, and Sources panel

**Files:**
- Create: `agent/templates/agent/faculty_workspace.html`, `agent/static/agent/js/faculty_workspace.js`
- Modify: `agent/page_views.py` (`faculty_workspace_page`), `agent/static/agent/css/faculty_studio.css`
- Test: `agent/tests/test_faculty_studio_pages.py`

**Interfaces:**
- Consumes: Task 1 shell blocks; `program_requirements.serialize`, `serialize_summary` (existing).
- Produces: template context `programs` (list of `serialize_summary` dicts for the signed-in user, ordered by name then catalog year) and `active_program` (`serialize(row)` dict or `None`), resolved from `?program=<uuid>` only if owned. DOM hooks used by Task 4: `#fw-root` with `data-chat-url`, `data-reset-url`, `data-export-url`, `data-import-url`, `data-confirm-url`; `#fw-active-program` (json_script of `active_program`); regions `[data-fw="sources"]`, `[data-fw="plan"]`, `[data-fw="cora"]`; `[data-fw="home"]` empty state.

- [ ] **Step 1: Write failing tests:** `test_workspace_context_lists_only_own_programs`; `test_active_program_resolves_when_owned`; `test_active_program_ignores_foreign_and_malformed_ids` (foreign uuid, `"not-a-uuid"` → `active_program is None`, status 200); `test_workspace_home_state_when_no_program` (contains `data-fw="home"` and the drop-zone label "Drop a requirements file"); `test_workspace_renders_three_panels_when_program_active` (contains the three `data-fw` regions and the program name); `test_workspace_has_privacy_note` ("Student details stay in this session only").
- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. Layout grid `270px | 1fr | 340px`, stacked below 1100px. Sources panel: program card, program picker (`<select>` of `programs`, changing it navigates to `?program=<id>`), an import drop zone button (wired in Task 5), and a "Requirement coverage" list placeholder filled by Task 4. Home state replaces the center panel when `active_program` is `None`: large drop zone plus up to five recent programs as links. `faculty_workspace.js` for now only wires the picker.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -am "Add faculty workspace page with program selection"` (plus `git add` of new files).

### Task 4: Draft plan view, Cora panel, reset and export

**Files:**
- Modify: `agent/static/agent/js/faculty_workspace.js`, `agent/templates/agent/faculty_workspace.html`, `agent/static/agent/css/faculty_studio.css`
- Test: `agent/tests/test_faculty_studio_pages.py`

**Interfaces:**
- Consumes: Task 2 exports; `POST data-chat-url` body `{program_requirement_id, message}` → `{reply, draft_plan}`; `POST data-reset-url`; `POST data-export-url` (DOCX blob; Task 11 adds the `format` field). Session store keys: `sessionStorage["ontrack.facultySession"]` holding `{chatMessages, generatedPlan, programId}`; template handoff key `sessionStorage["ontrack.selectedFacultyTemplate"]` (existing contract from `faculty_templates.js`: `{name, terms, creditMin, creditMax}`).
- Produces: exported function `renderPlanDocument(container, draft, program)` (uses Task 2 functions) and a `session-store` object `{read, write, clear}` inside `faculty_workspace.js`.

- [ ] **Step 1: Write failing tests** (Django page tests on markup contracts, since DOM behavior is covered by the manual walkthrough in Task 12): `test_workspace_exposes_plan_and_cora_hooks` asserts the rendered HTML contains `data-fw-summary`, `data-fw-term-list`, `data-fw-issues`, `data-fw-chat-form`, `data-fw-export`, `data-fw-reset`, `data-fw-template-banner`, and `ontrack.facultySession`; `test_workspace_script_uses_module_exports` asserts the served `faculty_workspace.js` source imports `./faculty_plan_model.js` and contains no `localStorage` (Task 11 relaxes this to allow only the `ontrack.facultyExportFormat` key).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Center panel: header (program, student label), summary strip from `planSummary` (labels: Planned credits, Terms, Program credits, Needs attention), one table per semester (Course, Title, Type chip from `courseCategoryMap`, Credits), conflict rows highlighted with a text chip "Prereq: CODE" (state is never color-only). Left coverage bars from `categoryCoverage`. Right panel: message list, an "issue" card per conflict with a "Dismiss" action (client-side only), prompt chips, composer. On submit POST to chat with the active program id (if none, show a message telling the user to pick or import a program, no request). On success store `generatedPlan` and re-render. Reset clears the store and calls the reset URL. Export downloads `academic-plan.docx` and shows a toast on failure. Template banner reads `ontrack.selectedFacultyTemplate` and prefills the composer, same behavior as the old planner. Escape all inserted text via `textContent`.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py -v` and `node --test agent/tests/js/`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -am "Render draft plan, coverage, and Cora panel in faculty workspace"`

### Task 5: Shared import flow (extract, review, confirm)

**Files:**
- Create: `agent/static/agent/js/faculty_import_flow.js`
- Modify: `agent/static/agent/js/faculty_workspace.js`, `agent/templates/agent/faculty_workspace.html`, `agent/static/agent/css/faculty_studio.css`
- Test: `agent/tests/test_faculty_studio_pages.py`, `agent/tests/test_faculty_requirements_endpoints.py` (already covers the API)

**Interfaces:**
- Consumes: `POST /api/faculty/requirements/import/` (multipart `file`) → `{requirements, source_filename}`; `POST /api/faculty/requirements/confirm/` body `{confirm:true, requirements, overwrite, source_filename}` → `201|200 {program_requirement}`, or `409 {detail, existing:{program_name, catalog_year, category_count, course_count, updated_at}}`.
- Produces: `export async function runImportFlow({file, importUrl, confirmUrl}) -> Promise<object|null>` resolving to the confirmed `program_requirement` or `null` if cancelled. Opens a native `<dialog>` showing program name, catalog year, total credits, and each category with credits and course count, with Confirm and Cancel; on `409` shows the existing program summary and an explicit "Overwrite" button that re-posts with `overwrite:true`.

- [ ] **Step 1: Write failing test** `test_workspace_wires_import_flow`: HTML contains `data-fw-import-input` (file input accepting `.xlsx,.csv`) and the served workspace script imports `./faculty_import_flow.js`.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement** `runImportFlow` using `apiRequest` from `core/api.js` (it already handles `FormData` and CSRF). After a confirmed import the workspace navigates to `?program=<requirement_id>`. Errors from the import call surface as a toast and never leave a half-open dialog. Dialog is focus-trapped by `<dialog>.showModal()` and closes on Escape.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py agent/tests/test_faculty_requirements_endpoints.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Add shared faculty requirements import flow"`

---

## Milestone 2: Programs

### Task 6: Programs service functions and API

**Files:**
- Modify: `agent/services/program_requirements.py`, `agent/views.py`, `agent/urls.py`, `agent/serializers.py`
- Create: `agent/tests/test_faculty_programs_api.py`

**Interfaces:**
- Produces in `program_requirements.py`:
  - `list_for_user(user) -> list[dict]`: each item is `serialize_summary(row)` plus `total_credits_required: int`, ordered by `program_name`, `catalog_year`.
  - `get_for_user(user, requirement_id) -> dict | None`: `serialize(row)` plus `categories: [{name, credits_required, course_count}]` and `checks: {"prerequisites_total": int, "prerequisites_resolved": int}` (resolved = prerequisite strings that equal some course `code` in the same program); `None` if not owned or missing.
  - `delete_for_user(user, requirement_id) -> bool`: deletes only an owned row; `True` if a row was deleted.
- Endpoints: `GET /api/faculty/requirements/` → `{"programs": [...]}`; `GET /api/faculty/requirements/<uuid:requirement_id>/` → `{"program": {...}}`; `DELETE` same path with body `{"confirm": true}` → `204`; missing/foreign → `404 {"detail": "Program requirement not found."}`; `confirm` absent or not `true` → `400`. Views `FacultyRequirementsListView`, `FacultyRequirementDetailView`; serializer `DeleteRequirementRequestSerializer(confirm=BooleanField)` rejecting non-true.

- [ ] **Step 1: Write failing tests** (fixtures copied from `test_faculty_requirements_endpoints.py`, plus a second faculty fixture `other_faculty_client`):
  - `test_list_returns_only_own_programs_sorted`
  - `test_detail_returns_structure_and_prerequisite_checks` (program with 3 prerequisite refs, 2 resolvable → `prerequisites_total == 3`, `prerequisites_resolved == 2`)
  - `test_detail_and_delete_foreign_id_match_missing_id_404` (same status and body for foreign, missing, and random uuid)
  - `test_two_faculty_cannot_delete_each_others_program` (row still exists afterward)
  - `test_delete_requires_explicit_confirm` (no body → 400, row still exists)
  - `test_delete_removes_exactly_one_row`
  - `test_delete_clears_matching_plan_session` (seed `client.session["faculty_plan_session"]` with that program's id; after delete it is absent; a session for a different program is untouched)
  - `test_empty_program_detail_and_list_do_not_error` (`categories: []`)
  - `test_student_gets_404_on_all_three`
- [ ] **Step 2: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_programs_api.py -v`. Expected: FAIL (404 on routes).
- [ ] **Step 3: Implement** the three service functions (ORM calls wrapped with `sync_to_async` in the views, matching `FacultyRequirementsConfirmView`), views, serializer, and `urls.py` entries. `FacultyRequirementDetailView.delete` also pops `faculty_plan_session` when its `program_requirement_id` equals the deleted id (reuse `_read_faculty_plan_session` / `_clear_faculty_plan_session`).
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Add faculty programs list, detail, and delete API"`

### Task 7: Programs page

**Files:**
- Modify: `agent/templates/agent/faculty_programs.html`, `agent/static/agent/js/faculty_programs.js`, `agent/page_views.py` (`faculty_programs_page` context), `agent/static/agent/css/faculty_studio.css`
- Test: `agent/tests/test_faculty_studio_pages.py`

**Interfaces:**
- Consumes: Task 6 endpoints; Task 5 `runImportFlow`; `faculty-workspace` URL for the Plan action.
- Produces: context `programs` (from `list_for_user`); DOM hooks `data-fp-row`, `data-fp-detail`, `data-fp-import`, `data-fp-delete`, `data-fp-reimport`, `data-fp-plan`.

- [ ] **Step 1: Write failing tests:** `test_programs_page_lists_only_own_programs`; `test_programs_page_empty_state` (text "No programs yet" and an import button); `test_programs_plan_link_targets_workspace` (each row's Plan link equals `reverse("faculty-workspace") + "?program=<id>"`); `test_programs_page_exposes_hooks`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Two-column layout (table, detail panel). Selecting a row fetches the detail endpoint and fills the panel (categories with credits, "Prerequisites resolved: X of Y"). Import button and re-import both call `runImportFlow`; the confirm step's 409 path handles overwrite. Delete opens the shared `action_dialog` confirmation naming the program, then sends `DELETE` with `{confirm:true}` and removes the row; failures show a toast and leave the row.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_studio_pages.py agent/tests/test_faculty_programs_api.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Add faculty Programs page"`

---

## Milestone 3: Templates and export formats

### Task 8: Restyle Templates and add the Plan skeletons / Export formats toggle

**Files:**
- Modify: `agent/templates/agent/faculty_templates.html`, `agent/static/agent/js/faculty_templates.js`, `agent/static/agent/css/faculty_studio.css`, `agent/tests/test_faculty_templates_ui.py`
- Test: `agent/tests/test_faculty_templates_ui.py`

**Interfaces:**
- Consumes: existing `systemTemplates`, `localStorage["ontrack.facultyTemplates"]`, `sessionStorage["ontrack.selectedFacultyTemplate"]` contracts (unchanged).
- Produces: DOM hooks `data-ft-tab="skeletons"|"formats"`, `data-ft-panel="skeletons"|"formats"`; the "Use in Workspace" action sets the selection key then navigates to `reverse("faculty-workspace")`.

- [ ] **Step 1: Write failing tests:** `test_templates_page_has_structure_only_notice` ("Structure only"); `test_templates_page_has_two_tabs` (both `data-ft-tab` values); `test_use_in_workspace_links_to_workspace` (script source contains the workspace URL constant, not `faculty-planner`); update the old assertions in this file that referenced `faculty-notification` and the old header.
- [ ] **Step 2: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_templates_ui.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Move template markup onto `faculty_studio.css` tokens; keep the existing library, detail, search, builder, and the student-field blocklist untouched. Add the notice and tab toggle. The formats panel is static in this task (Task 11 fills it).
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Restyle faculty templates and add plan skeleton and export format tabs"`

### Task 9: Export layouts in `plan_export`

**Files:**
- Modify: `agent/services/plan_export.py`
- Create: `agent/tests/test_faculty_export_formats.py`

**Interfaces:**
- Produces: `EXPORT_LAYOUTS = ("term_table", "year_grid", "plan_notes")`; `DEFAULT_LAYOUT = "term_table"`; `render_plan_docx(draft_plan: dict, layout: str = DEFAULT_LAYOUT) -> BytesIO` (unknown layout behaves as `DEFAULT_LAYOUT`). `term_table` is today's output unchanged. `year_grid` puts each pair/triple of consecutive semesters side by side in a table (one column per semester). `plan_notes` is `term_table` followed by a "Flagged issues and follow-ups" heading, then the draft's `notes` and an empty "Action items" list.

- [ ] **Step 1: Write failing tests** reading the DOCX XML the way `test_faculty_planner_ui_export.py` does: `test_term_table_matches_existing_output` (same text as before for a fixed draft); `test_year_grid_places_semesters_in_one_table` (one table whose first row holds two semester labels); `test_plan_notes_includes_followup_section`; `test_unknown_layout_falls_back_to_term_table`; `test_empty_semesters_still_produces_valid_docx` (each layout; reopen with `Document(BytesIO)`).
- [ ] **Step 2: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_export_formats.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Extract the current body into a private `_render_term_table(document, draft_plan)` helper; the two new layouts compose it.
- [ ] **Step 4: Run** the same command plus `venv/Scripts/python -m pytest agent/tests/test_faculty_planner_ui_export.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Add selectable DOCX export layouts"`

### Task 10: Export endpoint `format` option

**Files:**
- Modify: `agent/views.py` (`FacultyPlanExportView`), `agent/serializers.py`
- Test: `agent/tests/test_faculty_export_formats.py`

**Interfaces:**
- Consumes: Task 9 `render_plan_docx(draft_plan, layout)`, `plan_export.EXPORT_LAYOUTS`.
- Produces: `POST /api/faculty/plan/export/` body `{"format": "<layout>"}` optional; absent, empty, or unknown → `term_table`. Serializer `PlanExportRequestSerializer(format=CharField(required=False, allow_blank=True))`. A missing draft still returns the existing `400` message.

- [ ] **Step 1: Write failing tests:** `test_export_defaults_to_term_table_without_body`; `test_export_honors_year_grid` (table count assertion differs from term_table); `test_export_unknown_format_falls_back_and_returns_200`; `test_export_without_draft_still_400`; `test_export_contains_no_session_metadata` (conversation text and `student_details` values absent from the document XML).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** by validating the optional body, then passing the layout to `render_plan_docx`.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_export_formats.py agent/tests/test_faculty_planner_ui_export.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Accept export format on faculty plan export"`

### Task 11: Export formats UI and default

**Files:**
- Modify: `agent/templates/agent/faculty_templates.html`, `agent/static/agent/js/faculty_templates.js`, `agent/static/agent/js/faculty_workspace.js`, `agent/static/agent/css/faculty_studio.css`
- Test: `agent/tests/test_faculty_templates_ui.py`, `agent/tests/test_faculty_studio_pages.py`

**Interfaces:**
- Produces: `localStorage["ontrack.facultyExportFormat"]` holding one of `EXPORT_LAYOUTS` (a preference, not student data). The formats panel renders three cards (term-by-term table, year-at-a-glance grid, plan plus advising notes) with a "Set default" button and a "Default" chip; the Workspace export sends `{format: <stored value or "term_table">}`.

- [ ] **Step 1: Write failing tests:** `test_formats_panel_lists_three_layouts` (all three layout ids appear as `data-format="..."`); `test_workspace_export_sends_format` (served `faculty_workspace.js` contains `ontrack.facultyExportFormat` and a `format` body key); `test_export_format_preference_is_not_student_data` (the key name is not in `forbiddenStudentFields` and the script writes only a layout id).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the cards, the preference read/write wrapped in try/catch (storage can throw), and the export body. Update Task 4's `test_workspace_script_uses_module_exports` so `localStorage` is allowed only when the only key it touches is `ontrack.facultyExportFormat`.
- [ ] **Step 4: Run** `venv/Scripts/python -m pytest agent/tests/test_faculty_templates_ui.py agent/tests/test_faculty_studio_pages.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add -A agent && git commit -m "Add export format selection to faculty templates and workspace"`

### Task 12: Retire old pages, update docs, full verification

**Files:**
- Delete: `agent/templates/agent/faculty_dashboard.html`, `faculty_import.html`, `faculty_planner.html`, `agent/static/agent/js/faculty.js`, `faculty_planner.js`, `agent/static/agent/css/faculty.css`
- Modify: `agent/templates/agent/app_base.html` (remove the `faculty.css` include), `agent/tests/test_faculty_planner_ui_export.py` (delete assertions about the removed pages; keep the export API tests), `CLAUDE.md` (Faculty planning paragraph: new tabs/routes, `faculty_base.html`, Programs API, export formats; remove the "Known gap" sentence), `docs/superpowers/plans/2026-09-24-faculty-view-excel-import.md` status note if it exists
- Test: full suites

- [ ] **Step 1: Add** `test_removed_pages_have_no_template_or_script_references`: grep-style assertion that no file under `agent/` references `faculty_dashboard.html`, `faculty_import.html`, `faculty_planner.html`, `faculty.js`, `faculty_planner.js`, or `faculty.css` (excluding this test and docs). Run it; expected FAIL.
- [ ] **Step 2: Delete and edit** the files above; remove their `PAGE_SCRIPTS` and asset-version leftovers.
- [ ] **Step 3: Run the whole suite:** `venv/Scripts/python -m pytest -q` and `node --test agent/tests/js/`. Expected: all PASS. Any failure is fixed in this task, not skipped.
- [ ] **Step 4: Privacy regression:** add `test_chat_and_export_persist_no_student_state_to_database` to `test_faculty_studio_pages.py`: run a mocked chat turn with student details, then export; assert row counts of every model with a `user` FK are unchanged except `LlmUsage`, and no `ProductMetric.metadata` contains the student text.
- [ ] **Step 5: Manual browser walkthrough** (dev server on port 8001, Google redirect URIs already registered): run the seven checks in spec section 8, noting results in the PR description or this plan. Check specifically: Penn State navy/blue palette on every faculty page, no emoji, avatar menu (help, privacy note, sign out, admin view switch), keyboard-only navigation of rail and dialogs, narrow-width layout.
- [ ] **Step 6: Commit** `git add -A && git commit -m "Retire legacy faculty pages and document the faculty studio"`
