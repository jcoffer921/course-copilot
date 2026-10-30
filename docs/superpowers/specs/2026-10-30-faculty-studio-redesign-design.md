# Faculty Studio Redesign — Design

Date: 2026-10-30
Status: Draft for review (not yet approved)
Builds on: `docs/superpowers/plans/2026-09-24-faculty-view-excel-import.md`

## 1. Intent

Faculty advisors use OnTrack for one job: **import the requirement files, then get a plan from the AI**. The current faculty area (Dashboard, Import Data, Cora, Templates) reuses the student app's shell and look, spreads that one job across four pages, and carries a dashboard of cards that do not support it. One of those pages, `/faculty/import/`, is a non-functional mockup.

The redesign gives faculty their own workspace with a distinct feel:

- **Studio:** the plan is the centerpiece, shown as a document, with Cora beside it.
- **Professional workspace:** denser and calmer than the student app.
- **OnTrack identity, advisor tone:** same product, with its own brand accent (deep teal) so faculty can tell at a glance which side of the app they are in.

### Success criteria

1. A faculty member can go from a requirements file to an exportable draft plan without leaving one screen (Workspace).
2. Faculty pages no longer look like the student app: own shell, own accent, no student dashboard cards.
3. Every control shown on a faculty page does something real. No mockup-only pages or hardcoded values (the "3" notification badge, the non-functional Import page).
4. Nothing student-specific is ever persisted. Existing privacy guarantees hold (see section 6).
5. No emoji anywhere. Icons are inline SVG (reusing the existing `ot-icon` sprite where an icon exists) or plain words.

### What the user said vs. what I am assuming

Said: studio split layout; mix of professional/studio/brand feel; a different brand color for faculty; "balance works"; the Programs and Templates mockups "look good"; templates mean both plan skeletons and export formats; build, then test the functionality.

Assumed (please correct):
- Faculty palette follows Penn State's official colors (decided by the user): Nittany Navy `#001E44` (rail, headings), Beaver Blue `#1E407C` (primary buttons, active states, links), Pugh Blue `#96BEE6` (highlights, borders on soft surfaces), on white and light neutral grays. Only the colors are used. No Penn State logo, wordmark, or other marks appear, since this is not an official Penn State product.
- Cora keeps her violet in both areas, so she reads as the same assistant.
- The user is meeting their professor next week and may change details afterwards. The design therefore keeps colors, labels, and layout proportions in tokens and templates, not hardcoded across files.

## 2. Information architecture

Three tabs in a slim left rail, replacing four pages:

| Tab | Route | Replaces | Purpose |
|---|---|---|---|
| Workspace | `/faculty/` | Dashboard, Cora planner, Import page | The studio: Sources, Draft plan, Cora |
| Programs | `/faculty/programs/` | Import page, dashboard "active file" card | Library of confirmed requirement sets |
| Templates | `/faculty/templates/` (unchanged) | Templates | Plan skeletons and export formats |

The top bar carries the FACULTY badge, current program context, actions, and the avatar menu (help, privacy/FERPA note, sign out, and the existing admin student/faculty view switch).

Route names: `/faculty/` is renamed from `faculty-dashboard` to `faculty-workspace`, with every reference updated (including the faculty access and Google callback redirects); `/faculty/programs/` is `faculty-programs`. `/faculty/import/` and `/faculty/cora/` keep their route names `faculty-import` and `faculty-planner` permanently as redirects to `/faculty/programs/` and `/faculty/`, so bookmarks keep working.

Removed: the dashboard's quick-action grid, the hardcoded notification badge, and the scattered privacy cards (consolidated into one privacy note in the avatar menu and the Sources panel footer).

## 3. Screens

### 3.1 Workspace (`/faculty/`)

Three panels in a grid (`270px | 1fr | 340px`; collapses to stacked tabs below ~1100px):

- **Sources (left):** the loaded program and any applied template; a drop zone to import a new requirements `.xlsx`; per-group requirement coverage bars computed from the current draft plan. Footer note: student details stay in this session only.
- **Draft plan (center):** the plan rendered as a document: header (student label, credits completed, target graduation), a summary strip (planned credits, number of terms, program credits required, items needing attention), then one table per term. "Credits remaining" from the mockup is dropped: a student's completed credits are free text in the session, not a structured field, so any remaining-credits figure would be a guess (course, title, type chip, credits). Rows with unmet prerequisites are highlighted. Actions: Regenerate term, Accept draft.
- **Cora (right):** the existing grounded planning chat. Each assistant message may carry an "issue" card with one-click fixes. Quick-prompt chips and an input.

Empty state (no program loaded): the center panel becomes the home screen, with a large drop zone and a list of the faculty member's recent programs. This replaces the old dashboard.

Header actions: New session (existing reset), Export DOCX (existing export), Save as template (writes structure only, see 3.3).

Behavior is unchanged from today's planner: `POST /api/faculty/plan/chat/`, `.../plan/reset/`, `.../plan/export/`, with all student-specific state in `request.session["faculty_plan_session"]` and the browser's `sessionStorage`. The redesign changes layout and presentation, and adds a structured render of the draft plan (summary strip, prerequisite flags). Prerequisite flags are derived from the grounded `ProgramRequirement` data already available to the planner, not from model output. A course is flagged only when one of its listed prerequisites is itself in the draft plan in the same or a later term (a definite conflict). A prerequisite absent from the draft is never flagged, because the student may already have completed it.

The extract → review → confirm import flow has no working UI today (the planner links to the mockup Import page). It is built as one shared module used by both the Workspace drop zone and the Programs page.

### 3.2 Programs (`/faculty/programs/`)

A table of the faculty member's confirmed `ProgramRequirement` rows (program, catalog year, credits, status chip, updated date) with a detail panel: requirement groups with credit totals, and a prerequisite check: "Prerequisites resolved: X of Y", where Y is the number of prerequisite references across all courses and X is how many of those match a course code in the same program.

Actions: **Plan** (loads the program into Workspace), **Import requirements** (opens the existing extract → review → confirm flow, now with a proper home), **Re-import (overwrite)** (existing 409-then-overwrite collision flow), **Delete** (confirmation required; this is a destructive write, so it follows the project's plan-then-pause rule).

New backend (none of this exists today; only import and confirm do):

- `GET /api/faculty/requirements/` — list the signed-in faculty member's programs.
- `GET /api/faculty/requirements/<requirement_id>/` — detail with structure and derived checks.
- `DELETE /api/faculty/requirements/<requirement_id>/` — delete one owned program.

All three use `[IsAuthenticated, ActiveAccessPermission, FacultyPermission]` and scope every query to `request.user`. Foreign and missing IDs return the same `404`. Business logic lives in `agent/services/program_requirements.py`, which already owns writes, not in the views.

### 3.3 Templates (`/faculty/templates/`)

A "structure only" notice and a two-part toggle:

- **Plan skeletons** (existing behavior, restyled): 4-year, transfer, major exploration, graduation check, advising notes, plus user-created skeletons. "Use in Workspace" applies a skeleton to the Workspace session. User-created skeletons are stored in the browser's `localStorage` today (key `ontrack.facultyTemplates`) with a client-side blocklist of student fields; that stays as-is (see open questions).
- **Export formats** (new): selectable DOCX layouts for the exported plan: term-by-term table (today's layout), year-at-a-glance grid, plan plus advising notes. One can be marked default. The Workspace export honors the chosen format.

Export formats require a change to `agent/services/plan_export.py` and `FacultyPlanExportView` (accept a `format` value from a fixed allow-list). This is the only new capability beyond a redesign, so it is its own milestone and can be dropped without affecting the rest.

## 4. Visual system

- A faculty scope (`body[data-area="faculty"]`) defines CSS custom properties: ink, muted, line, background, panel, accent, accent-soft, accent-ink, plus status colors (ok, warn, bad). `faculty.css` is rewritten around these tokens; the current hardcoded green/purple/ivory values are removed.
- Token mapping: `--rail` = Nittany Navy `#001E44`; `--accent` = Beaver Blue `#1E407C` (white text, about 10:1 contrast); `--accent-ink` = Nittany Navy; `--accent-line` = Pugh Blue `#96BEE6`; `--accent-soft` = a light tint of Pugh Blue (about `#EAF2FB`, verified against text contrast at build time). Pugh Blue is never used as a text color on white, since it fails contrast; it is used for borders, fills, and focus rings only.
- Status colors stay distinct from the brand blues so state is never conveyed by hue alone: each status chip also carries a word ("Confirmed", "Needs attention").
- Layout: left rail 64px, top bar 56px, panels 12px radius with 1px borders, no heavy shadows.
- Shell: faculty pages get their own base template (`faculty_base.html`) with the rail and top bar, instead of the student `app_base.html` sidebar. Shared pieces that remain shared: auth/CSRF/API JS modules, the toast and modal helpers, and the `ot-icon` sprite.
- Accessibility: visible focus rings, 4.5:1 text contrast on the accent, keyboard-operable panels and tabs, `aria-current` on the active rail item, labels on all icon-only buttons.

## 5. Components and boundaries

- `faculty_base.html` — shell only (rail, top bar, avatar menu). No page logic.
- `faculty_workspace.html` + `faculty_workspace.js` — the studio. Splits into small modules: `sources`, `plan-view`, `cora-panel`, `session-store` (sessionStorage), each testable alone.
- `faculty_programs.html` + `faculty_programs.js` — list/detail/import/delete, talks only to the requirements API.
- `faculty_templates.html` + `faculty_templates.js` — kept and restyled; gains the export-formats section.
- `agent/services/program_requirements.py` — gains `list_for_user`, `get_for_user`, `delete_for_user`.
- `agent/services/plan_export.py` — gains a layout parameter (milestone 3).

## 6. Data and privacy

- No new tables are required. `ProgramRequirement` is unchanged.
- Student-specific state (details, conversation, draft plan) remains session-only. Nothing in this redesign writes it to the database, a file, or `localStorage`.
- `ProductMetric` events, if any are added for the new screens, use only the existing allow-listed metadata fields.
- Delete removes only the signed-in user's own `ProgramRequirement` row.

## 7. Delivery in milestones

Each milestone ships and is testable on its own.

1. **Shell and Workspace.** `faculty_base.html`, tokens, the Workspace studio on top of the existing chat/reset/export endpoints, the empty-state home, route changes and redirects, sidebar changes. No backend changes.
2. **Programs.** List/detail/delete service functions and endpoints, the Programs page, and wiring "Plan" into Workspace. Retires the mockup Import page.
3. **Templates.** Restyle plan skeletons; add Export formats and the `format` option on plan export.

## 8. Testing

Automated (pytest, matching the existing faculty test files):

- **Routes and permissions:** `/faculty/`, `/faculty/programs/`, `/faculty/templates/` render for faculty, redirect or forbid students and anonymous users; old URLs redirect correctly; the admin view-switch still works.
- **Two-user ownership (per the `ontrack-two-user-test` convention):** faculty A cannot list, read, or delete faculty B's programs; foreign and missing IDs return identical `404`s.
- **Programs API:** list ordering, detail structure and derived checks, delete removes exactly one row, delete requires a valid owned ID.
- **Export:** `format` accepts only allow-listed values and falls back safely; DOCX contains the plan only and no session metadata beyond today's behavior.
- **Privacy regression:** a test that exercises chat and export and asserts no student fields appear in any persisted table or `ProductMetric`.
- **Existing suites updated:** `test_faculty_planner_ui_export.py`, `test_faculty_templates_ui.py`, `test_faculty_access.py`, `test_admin_view_switch.py`.

Manual / browser, run against the dev server after each milestone:

1. Sign in as faculty, land on the Workspace, confirm the teal faculty shell and no student sidebar.
2. Import a real requirements `.xlsx`, review, confirm; see it appear in Programs.
3. Click Plan on that program, chat with Cora, check that a draft plan renders, that a deliberately bad prerequisite is flagged, and that a model-proposed course not in the program is dropped.
4. Reset, export DOCX, open it, and verify contents (and each export format in milestone 3).
5. Re-import the same program and confirm the overwrite prompt; delete a program and confirm the prompt.
6. Resize to a narrow width and check keyboard-only navigation.
7. Switch to a student account and confirm the faculty pages are not reachable.

## 9. Out of scope

- Any change to the student-facing app.
- Moving user-created templates from `localStorage` to the database.
- Saving student plans, notes, or advising history.
- Rubric critique mode or other deferred items.

## 10. Open questions for review

All four were resolved in review on 2026-10-30:

1. **Accent color:** Penn State colors (Nittany Navy, Beaver Blue, Pugh Blue). See section 4.
2. **Uncommitted work:** commit the existing faculty work first so the redesign diff is clean. Done as a separate commit before milestone 1.
3. **Export formats:** stay as milestone 3, after Programs.
4. **Template storage:** browser-only (`localStorage`) is acceptable for user-created skeletons for now.
