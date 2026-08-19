# Fixed grading categories — design

## Context

The Grade Calculator feature (shipped in `docs/superpowers/specs/2026-08-18-grade-calculator-design.md` / `docs/superpowers/plans/2026-08-18-grade-calculator.md`) lets a grading category's `component` name be arbitrary free text — set either by the LLM-based syllabus extraction (`agent/services/syllabus_extraction.py`, which uses whatever wording the syllabus itself uses, e.g. `"Homework (6 assignments)"`, `"Class Participation"`) or, as of Task 18, typed directly into the grading-setup form. This makes categories inconsistent across courses and gives the setup form an open-ended text field where a small fixed vocabulary would be simpler and less error-prone.

This design scopes `component` down to a fixed set of seven names — `Homework`, `Tests`, `Quizzes`, `Midterm`, `Final`, `Projects`, `Other` — enforced at the storage-validation layer, produced by extraction, and presented as a toggle list in the setup form, while leaving already-extracted courses untouched.

## Goals

- One canonical list of valid category names, defined once, consumed everywhere (extraction prompt, storage validation, CLI, frontend) — no duplicated/drifting copies.
- `storage.validate_grading_config` rejects any `component` outside the fixed set as a blocking error on writes going forward.
- `syllabus_extraction.py` maps syllabus wording onto the fixed set, merging same-bucket duplicates by summing their weights, and uses `Other` for real content that doesn't fit the six substantive categories — never dropping it, never force-fitting it into the wrong bucket.
- The grading-setup form (extending Task 18) presents all seven categories as a toggle list instead of free-text rows, pre-filled from real backend data (the canonical list), not a hardcoded frontend copy.
- Existing `syllabus.json` files are never touched by this change — enforcement is write-time only.

## Non-goals (explicitly out of scope)

- No migration of existing courses' syllabus data. `cs101`/`psyc201` keep their current free-text categories until someone opens and saves their grading-setup form.
- No change to `grades.add_item`'s validation — it already validates `component` against whatever's actually configured for that course (fixed-set or legacy free-text), which needs no change.
- No change to the Add-grade modal's category chips (`agent/templates/agent/ontrack.html`, Task 14) — already derived from the course's configured categories, so it automatically reflects whichever names are in play.
- No change to `grade_scale` (letter cutoffs, passing percentage) — unrelated to category naming.
- No backend endpoint or migration tool to bulk-remap an existing course's categories — the setup form's pre-fill heuristic (see Architecture) is a display convenience only, not a data migration.

## Architecture

### Canonical list (`agent/services/storage.py`)

```python
GRADING_CATEGORY_CHOICES = ["Homework", "Tests", "Quizzes", "Midterm", "Final", "Projects", "Other"]
```

Defined once, here, because `validate_grading_config` (which enforces it) already lives in this module. `agent/services/grades.py`, `agent/management/commands/grades.py`, and `agent/views.py` all already import `storage` — none need a new import path, they just reference `storage.GRADING_CATEGORY_CHOICES`.

### Storage-layer enforcement

`validate_grading_config(grading, grade_scale=None)` gains one more check per entry, alongside its existing `weight_pct`/`total_items`/`drop_lowest` checks:

```python
if g.get("component") not in GRADING_CATEGORY_CHOICES:
    errors.append(f"grading[{i}].component must be one of {GRADING_CATEGORY_CHOICES}: {g.get('component')!r}")
```

This is a **blocking** error (no `WARNING:` prefix), consistent with how `weight_pct`/`total_items` type errors already block. It fires on every write path: `PUT /api/courses/<id>/grading/` and `manage.py grades --set-grading`. It does **not** run against data already on disk — `read_syllabus`/`current_grade`/etc. never call `validate_grading_config`, so an old course's `"Homework (6 assignments)"` keeps rendering and calculating exactly as it does today. The very first time someone saves that course's grading-setup form again, the new entries must conform.

### Extraction (`agent/services/syllabus_extraction.py`)

`EXTRACTION_SYSTEM_PROMPT` gets a new "grading component mapping" section, added to the existing schema/rules text:

```
- Every grading[] entry's "component" MUST be exactly one of: Homework, Tests, Quizzes,
  Midterm, Final, Projects, Other. Map the syllabus's own wording onto these:
    - Homework: homework, assignments, problem sets, exercises
    - Tests: recurring or unlabeled tests/exams that are not specifically called out as
      "the midterm" or "the final" (e.g. "Test 1", "Unit Tests", "Chapter Quizzes" if the
      syllabus itself calls them tests rather than quizzes)
    - Quizzes: quizzes
    - Midterm: an exam explicitly labeled as the midterm
    - Final: an exam explicitly labeled as the final
    - Projects: projects, presentations, capstone work
    - Other: anything real that doesn't fit the six above (participation, attendance,
      lab reports, etc.) — use Other rather than dropping the entry or forcing it into
      the wrong bucket.
  If two or more syllabus lines map to the same bucket (e.g. "Problem Sets" 15% and "Lab
  Assignments" 10%, both Homework), merge them into ONE grading[] entry with the summed
  weight_pct — never emit two entries with the same component.
```

This composes with the prompt's existing anti-fabrication rules (drop the entry if a required field can't be determined) — mapping is about *renaming* a category that's genuinely present, never about inventing one that isn't.

### Grading-setup form (`agent/templates/agent/ontrack.html`, extends Task 18)

**`GradingConfigView.get`** (already built, Task 8) gains one more field in its response:

```python
return Response({
    "grading": syllabus.get("grading", []),
    "grade_scale": syllabus.get("grade_scale") or grades.DEFAULT_GRADE_SCALE,
    "category_choices": storage.GRADING_CATEGORY_CHOICES,
}, status=status.HTTP_200_OK)
```

The frontend never hardcodes the 7 names — it renders the toggle list from `category_choices` in whatever `loadGrades`/`loadGradesConfig`-equivalent call already surfaces the grading config (Task 18's `openGradingSetup()` currently seeds rows from `s.gradesBreakdown.categories`; it will additionally need the full `category_choices` list to know what to render as *unchecked* rows).

**Form structure** changes from Task 18's dynamic add/remove-row array to a fixed 7-row toggle list (per the approved mockup): each row is `[checkbox] CategoryName   weight% / total items / drop-lowest fields (shown only when checked)`. This removes `addGradingSetupCategory`/`removeGradingSetupCategory` entirely (no longer meaningful once the row set is fixed) and replaces the free-text `component` input with the fixed label. `updateGradingSetupField`/`submitGradingSetup` keep the same shape, just keyed by category name instead of array index, and `submitGradingSetup` only includes checked rows in the `grading` array it PUTs.

**Legacy pre-fill heuristic**: when `openGradingSetup()` runs for a course whose current categories aren't in `GRADING_CATEGORY_CHOICES` (an old free-text course), a small client-side keyword match (case-insensitive substring against each bucket's synonym list — the same synonyms the extraction prompt uses, kept as a JS constant) suggests which toggle to pre-check, defaulting to **Other** if nothing matches. This is purely a convenience for populating the form the first time; it does not call any API. If the guess is wrong, the user just checks a different box — saving replaces the old name entirely, and the already-built orphan-warning (`grades.find_orphaned_components`, wired into `GradingConfigView.put`) tells them exactly which previously-entered items stopped counting toward the grade.

## Alternatives considered

- **Enforce only in the frontend, leave the backend/CLI accepting any string.** Rejected: the CLI (`--set-grading`) is documented as mirroring the API exactly: allowing the CLI to write categories the UI can't create would immediately produce data the setup form can't cleanly re-open, and the fixed set exists specifically so `component` values are predictable everywhere, not just in one entry point.
- **Force-fit every extracted category into the closest of the 6 real buckets, no `Other`.** Rejected per your answer — risks misrepresenting syllabus content the app doesn't have license to reinterpret that aggressively (CLAUDE.md's non-fabrication rule is about content, and silently relabeling "Attendance" as "Homework" is a content misrepresentation in spirit even if not a literal date/fact).
- **Auto-migrate existing courses' `syllabus.json` now.** Rejected per your answer — bigger, riskier scope (touches already-entered grade data's component links across every course) for a change whose actual ask was about new data going forward.

## Edge cases

- **A syllabus with no clearly-labeled midterm/final, only "Test 1", "Test 2".** Both map to `Tests` and merge into one entry (summed weight) — `Midterm`/`Final` simply don't appear in that course's `grading[]`, which is already how `current_grade()` handles a category with zero entered items (excluded, not zero).
- **A syllabus with genuinely nothing that maps to a substantive bucket except participation.** Extraction emits a single `Other` entry — not dropped, not force-fit.
- **Saving the setup form with zero categories checked.** Same as today's existing empty-grading-array case (already handled — the empty-state card in the Grade Calculator tab already covers "no grading categories set up yet").
- **A course already has `Other` as a category from a previous save, and the user later re-derives a real bucket for that content.** No special handling needed — it's just editing which toggles are checked, like any other category change; the orphan-warning covers anything that stops matching.

## Testing

- `agent/tests/test_storage_grades.py`: extend `validate_grading_config` tests — a `component` outside `GRADING_CATEGORY_CHOICES` is a blocking error (not a warning); all 7 valid names pass.
- `agent/tests/test_views.py`: `GradingConfigView.get` response includes `category_choices` equal to `storage.GRADING_CATEGORY_CHOICES`; `PUT` with an invalid category name 422s with a blocking error (not silently accepted, not merely warned).
- Extraction: this codebase's syllabus-extraction tests are live-API and skip without `ANTHROPIC_API_KEY` (per existing convention) — no new automated coverage beyond confirming the prompt constant compiles/loads; verify the mapping/merge behavior manually against `test-syllabi/cs101_clean.txt` and `test-syllabi/psyc201_messy.txt`, checking the extracted `grading[]` only contains names from the fixed set and no duplicate component names.
- Manual verification: open the grading-setup form for a legacy course (free-text categories) and confirm the pre-fill heuristic checks a reasonable box (or `Other`) per existing category; save and confirm the orphan-warning appears for any item whose old category name no longer matches.
