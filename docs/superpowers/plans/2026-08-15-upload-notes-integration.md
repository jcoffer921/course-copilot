# Upload Notes Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Upload notes" button on the Dashboard tab functional for every course (not just PSYC201), wired to the existing `POST /api/courses/<course_id>/notes/chunk/` endpoint, with a modal for picking a file, editing a pre-filled lecture id, and an optional date — including plan-then-pause overwrite confirmation on an id collision.

**Architecture:** One small backend field rename (`dashboard.py`'s per-course `has_notes: bool` becomes `notes_count: int`, needed so the modal can suggest the next sequential lecture id without an extra network round-trip) plus one frontend-only feature: new `upload*` state on the existing `Component` class, a `FormData` POST (this codebase's first — every existing `fetch()` call sends JSON), and a new modal template block. No new backend endpoint — `ChunkNotesView` already exists, is tested, and already returns the `409`-with-preview shape this modal's conflict flow needs.

**Tech Stack:** Django 6 (ASGI), adrf async views, vanilla JS `fetch`/`FormData` inside the existing DC pseudo-component template (`agent/static/agent/support.js` — confirmed to implement the standard React synthetic event set including `onChange`, but NOT `onDrop`). No build step, no JS test runner — backend gets pytest coverage, frontend changes get live-browser verification, same split as the Quiz and Dashboard passes.

## Global Constraints

- No new backend endpoint or storage format — `POST /api/courses/<id>/notes/chunk/` (`agent/views.py:ChunkNotesView`) is untouched; this plan only changes what already calls it.
- No drag-and-drop — `agent/static/agent/support.js` has no `onDrop` handler (confirmed via `grep -c "onDrop" agent/static/agent/support.js` → `0`). Click-to-browse `<input type="file">` only.
- Only use HTML attributes/tags with existing precedent in `course_copilot.html`: `<input class="input">` (text), `<input type="file">` (new but standard DOM, not framework-specific), `onChange`, `onClick`. Do NOT use `<label>`, `disabled="..."`, or `type="date"` — none have any precedent in this file and are not needed (the submit method's own early-return guard, matching `checkAnswer`'s existing `if (!s.quizQuestion || s.quizMcAnswer == null) return;` pattern, covers the same case without an untested attribute).
- No backdrop-click-to-close on the modal — avoids needing an unverified `stopPropagation` binding. Cancel button only.
- `FormData` POSTs must NOT set a `Content-Type` header manually (the browser sets the multipart boundary) but MUST still send `X-CSRFToken: getCookie('csrftoken')`, same as the existing Quiz `fetch()` calls.
- Every async state-setting method needs a sequence-number guard against stale/out-of-order responses, same pattern as `_quizSeq`/`_dashSeq`/`_recentSeq`.

---

### Task 1: Rename `has_notes` → `notes_count` end-to-end

**Files:**
- Modify: `agent/services/dashboard.py:17`
- Modify: `agent/tests/test_dashboard.py` (assertions on lines 46, 59)
- Modify: `agent/templates/agent/course_copilot.html` (3 call sites: lines 580, 589, 603)

**Interfaces:**
- Consumes: `storage.read_notes(course_id) -> list` (unchanged).
- Produces: `dashboard.build_dashboard()`'s per-course dict gains `"notes_count": int` and loses `"has_notes"`. Task 2's `openUpload()` method consumes `courseMeta[courseId].notes_count` to suggest the next lecture id.

- [ ] **Step 1: Update the failing assertions in `test_dashboard.py`**

In `agent/tests/test_dashboard.py`, change line 46 from:
```python
    assert course["has_notes"] is True
```
to:
```python
    assert course["notes_count"] == 1
```

And change line 59 from:
```python
    assert course["has_notes"] is False
```
to:
```python
    assert course["notes_count"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: `test_build_dashboard_composes_course_data` and `test_build_dashboard_course_without_notes_or_mastery` both FAIL with `KeyError: 'notes_count'`

- [ ] **Step 3: Rename the field in `dashboard.py`**

In `agent/services/dashboard.py`, change line 17 from:
```python
        "has_notes": bool(storage.read_notes(course_id)),
```
to:
```python
        "notes_count": len(storage.read_notes(course_id)),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest agent/tests/test_dashboard.py -v`
Expected: 4 passed

- [ ] **Step 5: Update the 3 frontend call sites in `course_copilot.html`**

In `renderVals()`, change line 580 from:
```js
    const courseHasNotes = !!(courseMetaFor(s.course) && courseMetaFor(s.course).has_notes);
```
to:
```js
    const courseHasNotes = !!(courseMetaFor(s.course) && courseMetaFor(s.course).notes_count > 0);
```

Change line 589 from:
```js
        if (courseHasNotes || !courseMetaLoaded) this.loadQuestion(s.course);
```
to (unchanged — this line already reads the `courseHasNotes` local, not `.has_notes` directly; verify it still reads exactly as shown and make no edit here).

Change line 603 from:
```js
        if (!s.courseMeta || (courseMetaFor(courseId) && courseMetaFor(courseId).has_notes)) this.loadQuestion(courseId);
```
to:
```js
        if (!s.courseMeta || (courseMetaFor(courseId) && courseMetaFor(courseId).notes_count > 0)) this.loadQuestion(courseId);
```

(Only 2 of the 3 originally-flagged lines actually read `.has_notes` directly — line 589 reads the already-derived `courseHasNotes` local from line 580, so fixing line 580 already covers it. This step's actual edits are lines 580 and 603.)

- [ ] **Step 6: Full regression suite and `manage.py check`**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all passing, same total count as before this task (no tests added or removed)

Run: `venv/Scripts/python.exe manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Live sanity check**

Start the app (`.\run_server.bat` or `./scripts/run_server.sh`), load `/` in a browser, confirm the Dashboard tab still renders both course cards and the "Needs practice" / empty-state split correctly for CS101 vs. PSYC201 (unchanged visually — this task only renamed a field, no template output should differ yet).

- [ ] **Step 8: Commit**

```bash
git add agent/services/dashboard.py agent/tests/test_dashboard.py agent/templates/agent/course_copilot.html
git commit -m "Rename dashboard has_notes to notes_count end-to-end"
```

---

### Task 2: Wire the Upload notes modal to `POST /api/courses/<id>/notes/chunk/`

**Files:**
- Modify: `agent/templates/agent/course_copilot.html`
  - `state = {...}` block (`:427-433`) and sequence counters (`:435-437`)
  - New class methods: `openUpload`, `closeUpload`, `submitUpload` (add after `checkAnswer`, before `renderVals()`, i.e. after line 543)
  - `renderVals()`: new computed values and returned props (`:556-751`)
  - Course cards template block (`:150-185`)
  - New upload modal template block (inserted before `:210`, the Dashboard tab's closing `</div>`)

**Interfaces:**
- Consumes: `courseMetaFor(id)` (existing local in `renderVals()`, returns `courseMeta[id]` or `null`) → `.notes_count` (Task 1). `getCookie('csrftoken')` (existing top-level function, `:411`). `POST /api/courses/<id>/notes/chunk/` (existing, `agent/views.py:ChunkNotesView`) — request: `FormData` with `file`, `lecture_id`, optional `date`, optional `overwrite`; response: `201` `{course_id, notes, warnings}`, `400`/`422`/`502` `{detail}`, `409` `{detail, existing_preview: {lecture_id, source, date, topics, chunks}, resolution}`.
- Produces: nothing consumed outside this file.

**Note on line numbers:** Task 1 only touches lines 580 and 603 (single-line swaps, no line-count change), so every other line number below matches the file's current state exactly. If a prior step in this task shifted lines, re-locate by the quoted surrounding code rather than the number.

- [ ] **Step 1: Add new state fields and the sequence counter**

Change `course_copilot.html:427-437` from:
```js
  state = {
    tab: 'dashboard', course: 'cs101',
    courseMeta: null, dashboardDeadlines: [], dashboardLoading: false, dashboardError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
    quizStep: 0, quizQuestion: null, quizMcAnswer: null,
    quizCorrectCount: 0, quizLoading: false, quizError: null, quizErrorSource: null
  };

  _quizSeq = 0;
  _dashSeq = 0;
  _recentSeq = 0;
```
to:
```js
  state = {
    tab: 'dashboard', course: 'cs101',
    courseMeta: null, dashboardDeadlines: [], dashboardLoading: false, dashboardError: null,
    dashboardRecentAttempts: [], dashboardRecentLoading: false, dashboardRecentError: null,
    quizStep: 0, quizQuestion: null, quizMcAnswer: null,
    quizCorrectCount: 0, quizLoading: false, quizError: null, quizErrorSource: null,
    uploadOpenFor: null, uploadLectureId: '', uploadDate: '', uploadFile: null,
    uploadLoading: false, uploadError: null, uploadConflict: null
  };

  _quizSeq = 0;
  _dashSeq = 0;
  _recentSeq = 0;
  _uploadSeq = 0;
```

- [ ] **Step 2: Add `openUpload`, `closeUpload`, `submitUpload` methods**

Add these three methods immediately after `checkAnswer` closes (currently ending at line 543, right before `renderVals() {` at line 545):

```js
  openUpload(courseId) {
    const meta = this.state.courseMeta && this.state.courseMeta[courseId];
    const n = (meta && meta.notes_count) || 0;
    const suggested = 'lecture' + String(n + 1).padStart(2, '0');
    this.setState({
      uploadOpenFor: courseId, uploadLectureId: suggested, uploadDate: '',
      uploadFile: null, uploadLoading: false, uploadError: null, uploadConflict: null
    });
  }

  closeUpload() {
    this.setState({
      uploadOpenFor: null, uploadLectureId: '', uploadDate: '', uploadFile: null,
      uploadLoading: false, uploadError: null, uploadConflict: null
    });
  }

  submitUpload(overwrite) {
    const s = this.state;
    if (!s.uploadFile || !s.uploadLectureId) return;
    const seq = ++this._uploadSeq;
    const courseId = s.uploadOpenFor;
    this.setState({ uploadLoading: true, uploadError: null, uploadConflict: null });

    const body = new FormData();
    body.append('file', s.uploadFile);
    body.append('lecture_id', s.uploadLectureId);
    if (s.uploadDate) body.append('date', s.uploadDate);
    if (overwrite) body.append('overwrite', 'true');

    fetch(`/api/courses/${courseId}/notes/chunk/`, {
      method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body: body
    })
      .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })))
      .then(({ ok, status, data }) => {
        if (seq !== this._uploadSeq) return;
        if (status === 409) { this.setState({ uploadLoading: false, uploadConflict: data }); return; }
        if (!ok) { this.setState({ uploadLoading: false, uploadError: data.detail || 'Could not process that file.' }); return; }
        this.closeUpload();
        this.loadDashboard();
      })
      .catch(e => {
        if (seq !== this._uploadSeq) return;
        this.setState({ uploadLoading: false, uploadError: 'Network error: ' + e.message });
      });
  }
```

- [ ] **Step 3: Add computed values in `renderVals()`**

Immediately after the `retryDashboardRecent` line (`course_copilot.html:647`, right before `const allTopics = cd.allTopicsRaw.map(...)` at line 649), add:

```js
    const uploadConflictPreview = (s.uploadConflict && s.uploadConflict.existing_preview) || null;
    const uploadConflictTopicsText = (uploadConflictPreview && uploadConflictPreview.topics || []).join(', ');
    const onUploadFileChange = (e) => this.setState({ uploadFile: e.target.files[0] || null });
    const onUploadLectureIdChange = (e) => this.setState({ uploadLectureId: e.target.value });
    const onUploadDateChange = (e) => this.setState({ uploadDate: e.target.value });
```

- [ ] **Step 4: Add returned props for the upload modal**

In the `return { ... }` object, immediately after `retryDashboardRecent: retryDashboardRecent,` (currently line 738), add:

```js
      openUploadCs101: () => this.openUpload('cs101'),
      openUploadPsyc201: () => this.openUpload('psyc201'),
      uploadModalOpen: !!s.uploadOpenFor,
      uploadModalCourseUpper: s.uploadOpenFor ? s.uploadOpenFor.toUpperCase() : '',
      uploadLectureId: s.uploadLectureId,
      uploadDate: s.uploadDate,
      uploadLoading: s.uploadLoading,
      uploadError: s.uploadError,
      hasUploadConflict: !!s.uploadConflict,
      uploadConflictPreview: uploadConflictPreview,
      uploadConflictTopicsText: uploadConflictTopicsText,
      onUploadFileChange: onUploadFileChange,
      onUploadLectureIdChange: onUploadLectureIdChange,
      onUploadDateChange: onUploadDateChange,
      closeUpload: () => this.closeUpload(),
      cancelConflict: () => this.setState({ uploadConflict: null }),
      submitUpload: () => this.submitUpload(false),
      confirmOverwrite: () => this.submitUpload(true),
```

- [ ] **Step 5: Add the "Upload notes" button to the CS101 card, and wire PSYC201's existing button**

Change `course_copilot.html:151-165` from:
```html
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">CS101</div>
            <div class="card-title">Intro to Computer Science</div>
            <p class="card-body">{{ cs101Summary }}</p>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ cs101Tags }}" as="tag" hint-placeholder-count="2">
                <span class="tag tag-accent">{{ tag.label }}</span>
              </sc-for>
            </div>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ gradingCs101 }}" as="g" hint-placeholder-count="4">
                <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
              </sc-for>
            </div>
          </div>
```
to:
```html
          <div class="card elev-sm" style="padding:var(--space-6)">
            <div class="card-kicker">CS101</div>
            <div class="card-title">Intro to Computer Science</div>
            <p class="card-body">{{ cs101Summary }}</p>
            <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)" onClick="{{ openUploadCs101 }}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M5 21h14"/></svg>
              Upload notes
            </button>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ cs101Tags }}" as="tag" hint-placeholder-count="2">
                <span class="tag tag-accent">{{ tag.label }}</span>
              </sc-for>
            </div>
            <div style="display:flex;gap:6px;margin-top:var(--space-2);flex-wrap:wrap">
              <sc-for list="{{ gradingCs101 }}" as="g" hint-placeholder-count="4">
                <span class="tag tag-neutral">{{ g.component }} {{ g.weight_pct }}%</span>
              </sc-for>
            </div>
          </div>
```

Then change `course_copilot.html:170` (inside the PSYC201 card) from:
```html
            <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)">
```
to:
```html
            <button type="button" class="btn btn-secondary" style="margin-top:var(--space-2)" onClick="{{ openUploadPsyc201 }}">
```

- [ ] **Step 6: Add the upload modal template block**

In `course_copilot.html`, immediately after line 209 (`        </sc-if>`, closing the "Recent quiz activity" `courseHasNotes` block) and before line 210 (`      </div>`, closing the Dashboard tab's padded content wrapper), insert:

```html
        <sc-if value="{{ uploadModalOpen }}" hint-placeholder-val="{{ false }}">
          <div style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:50">
            <div class="card elev-md" style="padding:var(--space-6);width:420px;max-width:90vw">
              <div class="card-title" style="margin:0 0 var(--space-4)">Upload notes — {{ uploadModalCourseUpper }}</div>

              <sc-if value="{{ hasUploadConflict }}" hint-placeholder-val="{{ false }}">
                <div style="font-size:13.5px;margin-bottom:var(--space-4)">
                  <p style="margin:0 0 8px">A lecture called "{{ uploadLectureId }}" already exists for this course:</p>
                  <div class="card elev-sm" style="padding:12px;margin-bottom:12px">
                    <div style="font-weight:600">{{ uploadConflictPreview.lecture_id }} ({{ uploadConflictPreview.source }})</div>
                    <div style="opacity:.7;font-size:12.5px">{{ uploadConflictTopicsText }}</div>
                  </div>
                  <div style="display:flex;gap:8px">
                    <button type="button" class="btn btn-secondary" onClick="{{ cancelConflict }}">Cancel</button>
                    <button type="button" class="btn btn-primary" onClick="{{ confirmOverwrite }}">Overwrite</button>
                  </div>
                </div>
              </sc-if>

              <sc-if value="{{ !hasUploadConflict }}" hint-placeholder-val="{{ true }}">
                <div style="display:flex;flex-direction:column;gap:12px;margin-bottom:var(--space-4)">
                  <div>
                    <div style="font-size:13px;margin-bottom:4px">File (PDF, TXT, MD, or PPTX)</div>
                    <input type="file" accept=".pdf,.txt,.md,.pptx" onChange="{{ onUploadFileChange }}" style="font-size:13px"/>
                  </div>
                  <div>
                    <div style="font-size:13px;margin-bottom:4px">Lecture ID</div>
                    <input class="input" value="{{ uploadLectureId }}" onChange="{{ onUploadLectureIdChange }}" style="width:100%"/>
                  </div>
                  <div>
                    <div style="font-size:13px;margin-bottom:4px">Date (optional)</div>
                    <input class="input" placeholder="YYYY-MM-DD" value="{{ uploadDate }}" onChange="{{ onUploadDateChange }}" style="width:100%"/>
                  </div>
                </div>

                <sc-if value="{{ uploadError }}" hint-placeholder-val="{{ false }}">
                  <p style="font-size:13px;color:var(--color-accent-700);margin:0 0 var(--space-4)">{{ uploadError }}</p>
                </sc-if>

                <sc-if value="{{ uploadLoading }}" hint-placeholder-val="{{ false }}">
                  <div style="font-size:13px;opacity:.7;padding:8px 0">Chunking your notes… this can take a few seconds.</div>
                </sc-if>

                <sc-if value="{{ !uploadLoading }}" hint-placeholder-val="{{ true }}">
                  <div style="display:flex;gap:8px">
                    <button type="button" class="btn btn-secondary" onClick="{{ closeUpload }}">Cancel</button>
                    <button type="button" class="btn btn-primary" onClick="{{ submitUpload }}">Upload</button>
                  </div>
                </sc-if>
              </sc-if>
            </div>
          </div>
        </sc-if>
```

- [ ] **Step 7: `manage.py check` sanity pass**

Run: `venv/Scripts/python.exe manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Full regression suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all passing, same count as after Task 1 (this task touches no Python)

- [ ] **Step 9: Live browser verification (uses the `run` skill or Playwright)**

Start the app (`.\run_server.bat` or `./scripts/run_server.sh`), then in a browser:

1. Load `/`, confirm both CS101 and PSYC201 cards now show an "Upload notes" button.
2. Click CS101's button. Confirm the modal opens with lecture id pre-filled as `lecture03` (CS101 currently has `lecture01`/`lecture02` on disk, per `courses/cs101/notes/`).
3. Pick `test-notes/cs101_lecture05_recursion.txt` (the pre-filled id `lecture03` doesn't collide with CS101's existing `lecture01`/`lecture02`, so this is a fresh upload), click Upload. Confirm the loading message shows, then the modal closes and the CS101 card's summary text updates without a page reload (confirms `loadDashboard()` re-ran).
4. Re-open the CS101 upload modal and confirm the suggested id is now `lecture04` (proves `notes_count` refreshed from the real new file on disk, not stale client state).
5. Re-open the CS101 upload modal, manually clear the pre-filled id and type `lecture01` (which already exists on disk), pick any valid file, and submit — confirm the conflict card appears showing `lecture01`'s existing source/topics, then click "Overwrite" and confirm it completes successfully.
6. Trigger a 400 by selecting a file with an unsupported extension if one is easy to produce, or temporarily submit with an empty-content `.txt` file — confirm the error message from the backend surfaces in the modal (e.g. "source file is empty") and the modal stays open for retry.
7. Check the browser console for errors throughout.

- [ ] **Step 10: Commit**

```bash
git add agent/templates/agent/course_copilot.html
git commit -m "Wire Upload notes button to live /api/courses/<id>/notes/chunk/ endpoint"
```

---

## Explicitly out of scope (per spec, do not implement here)

- Drag-and-drop file upload — `support.js` has no `onDrop` support.
- Browsing, renaming, or deleting existing lectures.
- Any change to Progress or Chat tabs beyond the `notes_count` refresh they already inherit from `loadDashboard()`.
- Client-side file-type/size validation beyond the `accept` attribute — the backend's existing error messages surface as-is in the modal.
