# Fixed Grading Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope grading category names (`component`) down to a fixed set of seven — `Homework`, `Tests`, `Quizzes`, `Midterm`, `Final`, `Projects`, `Other` — enforced at the storage-validation layer, produced by syllabus extraction, and presented as a toggle list in the grading-setup form, without touching any already-extracted course's data.

**Architecture:** One canonical list (`storage.GRADING_CATEGORY_CHOICES`) becomes the single source of truth, consumed by `validate_grading_config` (blocking enforcement on writes), by `GradingConfigView.get` (surfaced to the frontend), and by the extraction prompt (documented inline, not imported — the LLM only sees prompt text). The grading-setup form (built in the prior plan's Task 18) is rewritten from a dynamic add/remove-row list to a fixed 7-row toggle list.

**Tech Stack:** Django + DRF (adrf async views), pytest + pytest-django, the Anthropic Messages API (syllabus extraction), the same hand-rolled `sc-if`/`sc-for` template DSL used throughout `ontrack.html` — no new dependencies.

## Global Constraints

- The fixed list is defined exactly once, in `agent/services/storage.py`, as `GRADING_CATEGORY_CHOICES = ["Homework", "Tests", "Quizzes", "Midterm", "Final", "Projects", "Other"]`. Every other place that needs it (views, CLI, frontend) reads it from there — never a second hardcoded copy.
- Enforcement is write-time only. Nothing in this plan re-validates or migrates data already on disk. An existing `syllabus.json` with `"Homework (6 assignments)"` keeps rendering and calculating exactly as it does today until someone saves its grading-setup form again.
- No fabrication: syllabus content that doesn't fit the six substantive categories goes to `Other`, never dropped, never force-fit into the wrong bucket, never invented. Grading lines that map to the same bucket get merged (summed weight) rather than duplicated — `current_grade()`/`grade_needed()` assume at most one entry per `component` name.
- No `<select>` element anywhere in `ontrack.html` (still true after this plan) — this file's established convention for picking from a small fixed set is chip buttons or, as introduced in this plan, plain checkboxes; never a native `<select>`.

---

## Task 1: `storage.py` — `GRADING_CATEGORY_CHOICES` + enforcement in `validate_grading_config`

**Files:**
- Modify: `agent/services/storage.py`
- Test: `agent/tests/test_storage_grades.py`

**Interfaces:**
- Produces: `storage.GRADING_CATEGORY_CHOICES: list[str]` (module-level constant)
- Modifies existing behavior: `storage.validate_grading_config(grading, grade_scale=None)` now also rejects a `component` outside `GRADING_CATEGORY_CHOICES` as a blocking (non-`WARNING`) error

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_storage_grades.py`:

```python
def test_validate_grading_config_rejects_invalid_component_name():
    grading = [{"component": "Class Participation", "weight_pct": 100}]

    errors = storage.validate_grading_config(grading)

    assert any("component" in e and "must be one of" in e for e in errors)
    assert not any(e.startswith("WARNING") for e in errors)  # blocking, not a warning


def test_validate_grading_config_accepts_every_fixed_category_name():
    grading = [
        {"component": name, "weight_pct": 100 / len(storage.GRADING_CATEGORY_CHOICES)}
        for name in storage.GRADING_CATEGORY_CHOICES
    ]

    errors = storage.validate_grading_config(grading)

    blocking = [e for e in errors if not e.startswith("WARNING")]
    assert blocking == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest agent/tests/test_storage_grades.py -k "invalid_component_name or accepts_every_fixed" -v`
Expected: FAIL — `test_validate_grading_config_rejects_invalid_component_name` fails because no such error is produced yet (`"Class Participation"` is currently accepted); `test_validate_grading_config_accepts_every_fixed_category_name` fails with `AttributeError: module 'agent.services.storage' has no attribute 'GRADING_CATEGORY_CHOICES'`

- [ ] **Step 3: Implement in `agent/services/storage.py`**

Add the constant near the top of the file, alongside the other module-level constants (`VALID_DATE_TYPES`, `VALID_NOTE_SOURCES`, currently at lines 19-21):

```python
GRADING_CATEGORY_CHOICES = ["Homework", "Tests", "Quizzes", "Midterm", "Final", "Projects", "Other"]
```

In `validate_grading_config` (currently starting at line 339), add the component-name check right after the existing `weight_pct` numeric check inside the per-entry loop:

```python
    for i, g in enumerate(grading):
        if not isinstance(g, dict) or "component" not in g or "weight_pct" not in g:
            errors.append(f"grading[{i}] missing 'component' or 'weight_pct': {g}")
            continue
        if not isinstance(g["weight_pct"], (int, float)):
            errors.append(f"grading[{i}].weight_pct must be numeric: {g['weight_pct']!r}")
        if g["component"] not in GRADING_CATEGORY_CHOICES:
            errors.append(f"grading[{i}].component must be one of {GRADING_CATEGORY_CHOICES}: {g['component']!r}")

        total_items = g.get("total_items")
        # ... (rest of the function unchanged)
```

(Only the new `if g["component"] not in GRADING_CATEGORY_CHOICES:` block is new — everything else in the function stays exactly as it is.)

- [ ] **Step 4: Run the file-scoped tests, then the full suite**

Run: `pytest agent/tests/test_storage_grades.py -v`
Expected: PASS (21 passed — the 19 pre-existing plus these 2 new ones)

Now run the full suite — this Task's change affects `component` validation everywhere `validate_grading_config` is called, not just this file, so it needs a full-suite check before moving on:

Run: `pytest agent/tests/ -v`
Expected: **one failure** — `agent/tests/test_views.py::test_grading_config_put_warns_about_orphaned_grades`, because that pre-existing test (added in the prior plan's final-review fix pass) PUTs `{"component": "Assignments", ...}`, and `"Assignments"` is not one of the 7 fixed names this task just started enforcing. This is expected and is fixed in the next step — do not treat it as a regression to investigate.

- [ ] **Step 5: Fix the one pre-existing test this task's enforcement breaks**

In `agent/tests/test_views.py`, find `test_grading_config_put_warns_about_orphaned_grades` and change its PUT body's `component` from `"Assignments"` to `"Projects"` (still a different category from the seeded `"Homework"`, so it still exercises the same orphan-detection behavior — just with a name that's valid under the new taxonomy):

```python
def test_grading_config_put_warns_about_orphaned_grades(isolated_courses_dir, api_client):
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Test", "dates": [],
        "grading": [{"component": "Homework", "weight_pct": 100}], "topics": [],
    })
    storage.write_grades("cs101", {"course_id": "cs101", "items": [
        {"id": "1", "component": "Homework", "title": "HW1", "score": 90, "max_points": 100},
    ]})

    response = api_client.put(
        "/api/courses/cs101/grading/",
        {"grading": [{"component": "Projects", "weight_pct": 100}]},
        format="json",
    )

    assert response.status_code == 200
    assert any("Homework" in w for w in response.data["warnings"])
```

This is the ONLY place in the test suite affected — already checked via `grep -n '"component":' agent/tests/test_views.py agent/tests/test_storage_grades.py`: every other test either uses a valid fixed-set name already (overwhelmingly `"Homework"`), or writes directly through `storage.write_syllabus`/`storage.write_grading_config`/`storage.write_grades`, none of which call `validate_grading_config`.

Run: `pytest agent/tests/ -v`
Expected: all tests PASS, zero failures — confirms this task leaves the full suite green before Task 2 begins.

- [ ] **Step 6: Commit**

```bash
git add agent/services/storage.py agent/tests/test_storage_grades.py agent/tests/test_views.py
git commit -m "feat: enforce a fixed grading-category taxonomy in validate_grading_config"
```

---

## Task 2: `views.py` — `GradingConfigView.get` returns `category_choices`

**Files:**
- Modify: `agent/views.py`
- Test: `agent/tests/test_views.py`

**Interfaces:**
- Consumes: `storage.GRADING_CATEGORY_CHOICES` (Task 1)
- Modifies existing behavior: `GET /api/courses/<course_id>/grading/`'s response gains a `"category_choices"` key

Task 1 already fixed the one pre-existing test its enforcement broke (`test_grading_config_put_warns_about_orphaned_grades`) and left the full suite green — this task starts from a clean baseline.

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_views.py`:

```python
def test_grading_config_get_includes_category_choices(isolated_courses_dir, api_client):
    _seed_syllabus("cs101")

    response = api_client.get("/api/courses/cs101/grading/")

    assert response.status_code == 200
    assert response.data["category_choices"] == storage.GRADING_CATEGORY_CHOICES
```

Run: `pytest agent/tests/test_views.py -k category_choices -v`
Expected: FAIL — `KeyError: 'category_choices'`

- [ ] **Step 2: Implement in `agent/views.py`**

In `GradingConfigView.get` (currently lines 350-357), add the new key:

```python
    async def get(self, request, course_id):
        syllabus = await sync_to_async(storage.read_syllabus)(course_id)
        if syllabus is None:
            return Response({"detail": f"no syllabus found for '{course_id}'"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "grading": syllabus.get("grading", []),
            "grade_scale": syllabus.get("grade_scale") or grades.DEFAULT_GRADE_SCALE,
            "category_choices": storage.GRADING_CATEGORY_CHOICES,
        }, status=status.HTTP_200_OK)
```

- [ ] **Step 3: Run tests to verify they pass, then run the full suite**

Run: `pytest agent/tests/test_views.py -v`
Expected: PASS (all tests including the new `test_grading_config_get_includes_category_choices`)

Run: `pytest agent/tests/ -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 4: Commit**

```bash
git add agent/views.py agent/tests/test_views.py
git commit -m "feat: expose category_choices from GradingConfigView.get"
```

---

## Task 3: `syllabus_extraction.py` — map syllabus wording onto the fixed category set

**Files:**
- Modify: `agent/services/syllabus_extraction.py`

**Interfaces:**
- No new functions — this task only changes the text of `EXTRACTION_SYSTEM_PROMPT`, which `extract_syllabus_async` already sends to the model unchanged.

This codebase has no automated test for syllabus extraction (it's a live LLM call; there is no `test_syllabus_extraction.py`, and extraction has always been verified manually per `README.md`'s existing "Test checklist before moving to Step 2" section). This task follows that same convention: no new automated test, manual verification against the existing sample syllabi.

- [ ] **Step 1: Update the schema line and add mapping guidance**

In `agent/services/syllabus_extraction.py`, find the `EXTRACTION_SYSTEM_PROMPT` constant. Change the schema block's `"grading"` line from:

```python
  "grading": [{"component": "string", "weight_pct": 0}],
```

to (matching the existing convention already used for `"type"` on the line above it, which inlines its enum choices directly into the schema string):

```python
  "grading": [{"component": "Homework|Tests|Quizzes|Midterm|Final|Projects|Other", "weight_pct": 0}],
```

Then, in the "Notes on fields" section, find this existing bullet:

```python
- "weight_pct" is a number (e.g. 20 for 20%). If weights aren't given, drop that \
whole grading[] entry — never emit {"component": ...} with no "weight_pct".
```

Add a new bullet immediately after it (before the `"topics"` bullet):

```python
- "component" MUST be exactly one of: Homework, Tests, Quizzes, Midterm, Final, \
Projects, Other. Map the syllabus's own wording onto these:
    - Homework: homework, assignments, problem sets, exercises
    - Tests: recurring or unlabeled tests/exams not specifically called out as \
"the midterm" or "the final"
    - Quizzes: quizzes
    - Midterm: an exam explicitly labeled as the midterm
    - Final: an exam explicitly labeled as the final
    - Projects: projects, presentations, capstone work
    - Other: anything real that doesn't fit the six above (participation, \
attendance, lab reports, etc.) — use Other rather than dropping the entry or \
forcing it into the wrong bucket.
  If two or more syllabus lines map to the same bucket (e.g. "Problem Sets" 15% \
and "Lab Assignments" 10%, both Homework), merge them into ONE grading[] entry \
with the summed weight_pct — never emit two entries with the same component.
```

The full "Notes on fields" section should now read, in order: the `"date"`/year-inference bullet (unchanged), the `"type"` bullet (unchanged), the `"weight_pct"` bullet (unchanged), the new `"component"` bullet (above), the `"topics"` bullet (unchanged).

- [ ] **Step 2: Manually verify against the existing sample syllabi**

Requires `ANTHROPIC_API_KEY` set. Run:

```bash
python manage.py extract_syllabus test-syllabi/cs101_clean.txt cs101test --course-name "CS101 Test" --force
python manage.py extract_syllabus test-syllabi/psyc201_messy.txt psyc201test --course-name "PSYC201 Test" --force
```

For each, inspect the written `courses/cs101test/syllabus.json` / `courses/psyc201test/syllabus.json` and confirm:
- Every `grading[].component` is exactly one of the 7 fixed names (no free text like `"Homework (6 assignments)"` or `"Class Participation"` verbatim from the syllabus).
- No two entries share the same `component` value (if the source syllabus has, say, two separate homework-like lines, confirm they were merged into one entry with the summed weight, not left as two).
- Nothing that was clearly a real grading line in the syllabus is missing — cross-check against the raw `test-syllabi/*.txt` file by eye. If a category doesn't map cleanly to the six substantive buckets, confirm it landed in `"Other"` rather than being silently dropped.
- The rest of the extraction (dates, topics) is unaffected — this change only touches `grading[]` mapping.

Delete the test courses afterward so they don't pollute the repo's course data:

```bash
python manage.py shell -c "from agent.services import storage; storage.delete_course('cs101test'); storage.delete_course('psyc201test')"
```

(If `storage.delete_course` isn't importable that way in your shell, delete the `courses/cs101test/` and `courses/psyc201test/` directories directly instead — either way, confirm `git status` shows no leftover test course data before moving on.)

- [ ] **Step 3: Commit**

```bash
git add agent/services/syllabus_extraction.py
git commit -m "feat: map syllabus grading components onto the fixed category taxonomy"
```

---

## Task 4: `ontrack.html` — rewrite the grading-setup form as a fixed toggle list

**Files:**
- Modify: `agent/templates/agent/ontrack.html`

**Interfaces:**
- Consumes: `GET /api/courses/<id>/grading/` (now includes `category_choices`, Task 2), `PUT /api/courses/<id>/grading/` (unchanged shape, Task 8 of the prior plan)
- Replaces: Task 18's `gradingSetupCategories` array-based state/methods with a fixed-shape `gradingSetupChecked`/`gradingSetupFields` map, keyed by category name
- Removes: `addGradingSetupCategory()`, `removeGradingSetupCategory(index)` (no longer meaningful — the row set is fixed at 7, nothing to add or remove)
- Produces: `openGradingSetup()` (now async, fetches fresh config on open), `closeGradingSetup()`, `toggleGradingSetupCategory(category)`, `updateGradingSetupField(category, field, value)`, `submitGradingSetup()`, `_guessCategoryForLegacyName(name, choices)`

**This is the first checkbox input (`<input type="checkbox">`) anywhere in this file.** Every other picker in this file is either a text input or a button-chip (this file has no `<select>` anywhere and that stays true here). Text inputs' `value="{{ }}"` binding is proven to work correctly across many prior tasks in this file; a checkbox's `checked="{{ }}"` binding has no precedent here to compare against, so this task's manual verification step below specifically calls out testing that toggling actually updates and persists — treat this the way Task 16 treated its `sc-if` tag-balance risk and Task 17 treated live interaction: don't assume it works from reading the markup, click it in a real browser.

- [ ] **Step 1: Read the current code before editing**

Read the following in `agent/templates/agent/ontrack.html` before making any change (search by content — do not trust the line numbers below once you've made earlier edits in this task, since each edit shifts what follows):
- The state initializer's `gradingSetupOpen: false, gradingSetupCategories: [], ...` line (currently line 1037)
- `openGradingSetup()` through `submitGradingSetup()`'s closing `}` (currently lines 1435-1508)
- The `gradingSetupRows` computed var in `renderVals()` (currently lines 1738-1745)
- The returned-object lines for `gradingSetupOpen`/`gradingSetupRows`/`addGradingSetupCategory`/etc. (currently lines 2217-2222)
- The modal markup, `<sc-if value="{{ gradingSetupOpen }}" ...>` through its closing `</sc-if>` (currently lines 593-628)

- [ ] **Step 2: Replace the state initializer**

Change:
```javascript
    gradingSetupOpen: false, gradingSetupCategories: [], gradingSetupLoading: false, gradingSetupError: null,
```
to:
```javascript
    gradingSetupOpen: false, gradingSetupCategoryChoices: [], gradingSetupChecked: {}, gradingSetupFields: {},
    gradingSetupLoading: false, gradingSetupError: null,
```

- [ ] **Step 3: Replace the six `gradingSetup*` methods**

Replace `openGradingSetup()` through `submitGradingSetup()`'s closing `}` (everything from `openGradingSetup() {` up to and including the `}` that closes `submitGradingSetup`) with:

```javascript
  openGradingSetup() {
    const s = this.state;
    const courseId = s.course;
    const seq = ++this._gradingSetupSeq;
    fetch(`/api/courses/${courseId}/grading/`)
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradingSetupSeq) return;
        if (!ok) { this.setState({ gradesError: data.detail || 'Could not load grading categories.' }); return; }

        const choices = data.category_choices || [];
        const checked = {};
        const fields = {};
        choices.forEach(name => {
          checked[name] = false;
          fields[name] = { weight_pct: '', total_items: '', drop_lowest: '' };
        });

        (data.grading || []).forEach(entry => {
          const target = choices.includes(entry.component)
            ? entry.component
            : this._guessCategoryForLegacyName(entry.component, choices);
          checked[target] = true;
          fields[target] = {
            weight_pct: String(entry.weight_pct),
            total_items: entry.total_items != null ? String(entry.total_items) : '',
            drop_lowest: entry.drop_lowest ? String(entry.drop_lowest) : '',
          };
        });

        this.setState({
          gradingSetupOpen: true, gradingSetupCategoryChoices: choices,
          gradingSetupChecked: checked, gradingSetupFields: fields,
          gradingSetupError: null, gradingSetupLoading: false,
        });
      })
      .catch(e => {
        if (seq !== this._gradingSetupSeq) return;
        this.setState({ gradesError: 'Network error: ' + e.message });
      });
  }

  _guessCategoryForLegacyName(name, choices) {
    const lower = (name || '').toLowerCase();
    const synonyms = {
      Homework: ['homework', 'assignment', 'problem set', 'exercise'],
      Tests: ['test'],
      Quizzes: ['quiz'],
      Midterm: ['midterm'],
      Final: ['final'],
      Projects: ['project', 'presentation', 'capstone'],
    };
    for (const category of choices) {
      const keywords = synonyms[category];
      if (keywords && keywords.some(k => lower.includes(k))) return category;
    }
    return choices.includes('Other') ? 'Other' : (choices[0] || 'Other');
  }

  closeGradingSetup() {
    this._gradingSetupSeq++;
    this.setState({
      gradingSetupOpen: false, gradingSetupCategoryChoices: [], gradingSetupChecked: {}, gradingSetupFields: {},
      gradingSetupError: null, gradingSetupLoading: false,
    });
  }

  toggleGradingSetupCategory(category) {
    this.setState({
      gradingSetupChecked: Object.assign({}, this.state.gradingSetupChecked, {
        [category]: !this.state.gradingSetupChecked[category],
      }),
    });
  }

  updateGradingSetupField(category, field, value) {
    const fields = Object.assign({}, this.state.gradingSetupFields, {
      [category]: Object.assign({}, this.state.gradingSetupFields[category], { [field]: value }),
    });
    this.setState({ gradingSetupFields: fields });
  }

  submitGradingSetup() {
    const s = this.state;
    const courseId = s.course;
    const grading = [];
    for (const category of s.gradingSetupCategoryChoices) {
      if (!s.gradingSetupChecked[category]) continue;
      const f = s.gradingSetupFields[category];
      const weight = parseFloat(f.weight_pct);
      if (isNaN(weight)) { this.setState({ gradingSetupError: `Enter a weight % for ${category}.` }); return; }
      const entry = { component: category, weight_pct: weight };
      if (f.total_items.trim()) {
        const totalItems = parseInt(f.total_items, 10);
        if (isNaN(totalItems) || totalItems < 1) { this.setState({ gradingSetupError: `Total items for ${category} must be a positive whole number.` }); return; }
        entry.total_items = totalItems;
      }
      if (f.drop_lowest.trim()) {
        const dropLowest = parseInt(f.drop_lowest, 10);
        if (isNaN(dropLowest) || dropLowest < 0) { this.setState({ gradingSetupError: `Drop-lowest for ${category} must be a non-negative whole number.` }); return; }
        entry.drop_lowest = dropLowest;
      }
      grading.push(entry);
    }

    const seq = ++this._gradingSetupSeq;
    this.setState({ gradingSetupLoading: true, gradingSetupError: null });
    fetch(`/api/courses/${courseId}/grading/`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      body: JSON.stringify({ grading: grading })
    })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (seq !== this._gradingSetupSeq) return;
        if (!ok) {
          const blocking = (data.errors || []).filter(e => !e.startsWith('WARNING'));
          this.setState({ gradingSetupLoading: false, gradingSetupError: blocking.join('; ') || data.detail || 'Could not save grading setup.' });
          return;
        }
        this.closeGradingSetup();
        this.loadGrades(courseId);
      })
      .catch(e => {
        if (seq !== this._gradingSetupSeq) return;
        this.setState({ gradingSetupLoading: false, gradingSetupError: 'Network error: ' + e.message });
      });
  }
```

Note `_gradingSetupSeq` itself needs no change — it's already correctly declared as a class field (`_gradingSetupSeq = 0;`) from the prior plan's Task 18, and every increment site above uses the same plain `this._gradingSetupSeq++`/`++this._gradingSetupSeq` convention already established. Do not introduce a second counter or a lazy-init guard.

- [ ] **Step 4: Replace the `gradingSetupRows` computed var**

Change:
```javascript
    const gradingSetupRows = s.gradingSetupCategories.map((c, i) => ({
      component: c.component, weight_pct: c.weight_pct, total_items: c.total_items, drop_lowest: c.drop_lowest,
      onComponentChange: (e) => this.updateGradingSetupField(i, 'component', e.target.value),
      onWeightChange: (e) => this.updateGradingSetupField(i, 'weight_pct', e.target.value),
      onTotalItemsChange: (e) => this.updateGradingSetupField(i, 'total_items', e.target.value),
      onDropLowestChange: (e) => this.updateGradingSetupField(i, 'drop_lowest', e.target.value),
      onRemove: () => this.removeGradingSetupCategory(i),
    }));
```
to:
```javascript
    const gradingSetupRows = s.gradingSetupCategoryChoices.map(category => ({
      category: category,
      checked: !!s.gradingSetupChecked[category],
      onToggle: () => this.toggleGradingSetupCategory(category),
      weight_pct: (s.gradingSetupFields[category] || {}).weight_pct || '',
      total_items: (s.gradingSetupFields[category] || {}).total_items || '',
      drop_lowest: (s.gradingSetupFields[category] || {}).drop_lowest || '',
      onWeightChange: (e) => this.updateGradingSetupField(category, 'weight_pct', e.target.value),
      onTotalItemsChange: (e) => this.updateGradingSetupField(category, 'total_items', e.target.value),
      onDropLowestChange: (e) => this.updateGradingSetupField(category, 'drop_lowest', e.target.value),
    }));
```

- [ ] **Step 5: Update the returned-object keys**

Change:
```javascript
      gradingSetupOpen: s.gradingSetupOpen, gradingSetupRows: gradingSetupRows,
      gradingSetupLoading: s.gradingSetupLoading, gradingSetupError: s.gradingSetupError,
      openGradingSetup: () => this.openGradingSetup(),
      closeGradingSetup: () => this.closeGradingSetup(),
      addGradingSetupCategory: () => this.addGradingSetupCategory(),
      submitGradingSetup: () => this.submitGradingSetup(),
```
to:
```javascript
      gradingSetupOpen: s.gradingSetupOpen, gradingSetupRows: gradingSetupRows,
      gradingSetupLoading: s.gradingSetupLoading, gradingSetupError: s.gradingSetupError,
      openGradingSetup: () => this.openGradingSetup(),
      closeGradingSetup: () => this.closeGradingSetup(),
      submitGradingSetup: () => this.submitGradingSetup(),
```
(`addGradingSetupCategory` is simply removed — no replacement key needed, since the markup change in the next step removes the only place that referenced it.)

- [ ] **Step 6: Replace the modal's row markup**

Inside the `<sc-if value="{{ gradingSetupOpen }}" ...>` block, replace this section:
```html
          <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:var(--space-4)">
            <sc-for list="{{ gradingSetupRows }}" as="row" hint-placeholder-count="3">
              <div style="display:flex;gap:8px;align-items:center">
                <input class="input" placeholder="Category name" value="{{ row.component }}" onChange="{{ row.onComponentChange }}" style="flex:2;min-width:0"/>
                <input class="input" placeholder="Weight %" value="{{ row.weight_pct }}" onChange="{{ row.onWeightChange }}" style="flex:1;min-width:0"/>
                <input class="input" placeholder="Total items" value="{{ row.total_items }}" onChange="{{ row.onTotalItemsChange }}" style="flex:1;min-width:0"/>
                <input class="input" placeholder="Drop lowest" value="{{ row.drop_lowest }}" onChange="{{ row.onDropLowestChange }}" style="flex:1;min-width:0"/>
                <button type="button" class="btn btn-ghost" onClick="{{ row.onRemove }}">Remove</button>
              </div>
            </sc-for>
          </div>

          <button type="button" class="btn btn-secondary" onClick="{{ addGradingSetupCategory }}" style="margin-bottom:var(--space-4)">+ Add category</button>
```
with:
```html
          <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:var(--space-4)">
            <sc-for list="{{ gradingSetupRows }}" as="row" hint-placeholder-count="7">
              <div style="display:flex;gap:8px;align-items:center">
                <label style="display:flex;align-items:center;gap:8px;flex:1;cursor:pointer">
                  <input type="checkbox" checked="{{ row.checked }}" onChange="{{ row.onToggle }}"/>
                  <span style="font-size:14px;font-weight:600">{{ row.category }}</span>
                </label>
                <sc-if value="{{ row.checked }}" hint-placeholder-val="{{ false }}">
                  <input class="input" placeholder="Weight %" value="{{ row.weight_pct }}" onChange="{{ row.onWeightChange }}" style="flex:1;min-width:0"/>
                  <input class="input" placeholder="Total items" value="{{ row.total_items }}" onChange="{{ row.onTotalItemsChange }}" style="flex:1;min-width:0"/>
                  <input class="input" placeholder="Drop lowest" value="{{ row.drop_lowest }}" onChange="{{ row.onDropLowestChange }}" style="flex:1;min-width:0"/>
                </sc-if>
              </div>
            </sc-for>
          </div>
```
(The `+ Add category` button is deleted entirely — the row set is fixed at 7 now, nothing to add.)

Everything else in the modal (the title, `gradingSetupError` display, `gradingSetupLoading` display, Cancel/Save buttons) stays exactly as it is — do not touch it.

- [ ] **Step 7: Manually verify — server renders, no template error**

Start the dev server on a free port (`venv/Scripts/python.exe -m uvicorn config.asgi:application --port 8030`), confirm HTTP 200 with no template error, and grep the response for `"Edit grading categories"` to confirm the modal's markup reached the page.

- [ ] **Step 8: Manually verify — real browser interaction (required, not optional for this task)**

Using live browser tooling (Playwright or equivalent):

1. Open Grade Calculator for a course with **no** `grading` array yet (or a fresh test course). Click "Set up grading categories." Confirm all 7 rows render (Homework, Tests, Quizzes, Midterm, Final, Projects, Other), none checked, no weight/total-items/drop-lowest fields visible for any of them.
2. Check the "Homework" box. Confirm its weight%/total-items/drop-lowest fields appear immediately (this is the specific interaction most likely to reveal a `checked="{{ }}"` binding problem — watch for the fields not appearing, or appearing for the wrong row).
3. Fill in a weight and total_items for Homework and Midterm, save. Confirm the modal closes and the "Grading breakdown" card shows exactly those two categories.
4. Re-open "Edit categories." Confirm Homework and Midterm are pre-checked with their saved values, and the other 5 are unchecked. Uncheck Midterm, save. Confirm it disappears from the breakdown card.
5. Test the legacy pre-fill heuristic: open Grade Calculator for a course that still has an old free-text category (e.g. `cs101` or `psyc201`, which have names like `"Homework (6 assignments)"`, `"Class Participation"`, `"Final Project"` from before this change — do not save changes to these courses' real data during this test, or revert afterward). Open "Edit categories" and confirm each legacy category landed on a reasonable pre-checked box (e.g. `"Homework (6 assignments)"` → Homework checked; `"Class Participation"` → likely Other checked, since it doesn't match any keyword list). Cancel without saving (or save then manually revert `courses/<id>/syllabus.json` via `git checkout --`) so you don't overwrite real course data.
6. Confirm `git status` shows no unintended changes to `courses/*/syllabus.json` before committing this task's code.

If checkbox binding doesn't work as expected in step 2 (fields don't appear/disappear correctly on toggle), stop and report BLOCKED with exactly what you observed — do not guess at a workaround without understanding why the binding failed.

- [ ] **Step 9: Commit**

```bash
git add agent/templates/agent/ontrack.html
git commit -m "feat: rewrite grading-setup form as a fixed-category toggle list"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-19-fixed-grading-categories-design.md` maps to a task — canonical list + storage enforcement (Task 1), `category_choices` surfaced to the frontend (Task 2), extraction prompt mapping + merge-duplicates rule (Task 3), toggle-list UI + legacy pre-fill heuristic + orphan-warning interaction (Task 4, the orphan-warning itself needs no new code since it was already built in the prior plan's final-review fix pass — Task 4 just has to not break it, which the manual verification in Step 8.4 checks).
- **Placeholder scan:** no TBDs; every step has complete code. Task 3 has no automated test by design, matching this codebase's existing convention for the one other LLM-call service (documented explicitly rather than left as an implicit gap).
- **Type consistency checked:** `GRADING_CATEGORY_CHOICES` is defined once in Task 1 and referenced identically (never redefined) in Tasks 2-4. The frontend's `gradingSetupChecked`/`gradingSetupFields` state shape introduced in Task 4 is used consistently across `openGradingSetup`, `toggleGradingSetupCategory`, `updateGradingSetupField`, `submitGradingSetup`, and the `gradingSetupRows` computed var — all keyed by the same category-name strings that `category_choices` (Task 2) provides.
- **Cross-plan consistency:** Task 2's fix to `test_grading_config_put_warns_about_orphaned_grades` was double-checked against every other `"component":` value across `agent/tests/test_views.py` and `agent/tests/test_storage_grades.py` (via `grep -n '"component":' ...`) — it is the only test whose component name becomes invalid under Task 1's new enforcement; every other test either uses a valid fixed-set name already, or writes directly through `storage.write_syllabus`/`storage.write_grading_config`/`storage.write_grades` (which never call `validate_grading_config`), so it's unaffected.
