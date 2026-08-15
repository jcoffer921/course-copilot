# Upload notes integration — design

## Context

`agent/templates/agent/course_copilot.html`'s Dashboard tab currently renders an
"Upload notes" button on the PSYC201 course card only (shown because
`courseHasNotes` is false for that course) — but the button has no `onClick`
handler at all. It's dead UI. CS101's card doesn't show the button, even
though a real course keeps adding lectures throughout the semester.

The backend already has a complete, working, tested endpoint for this:
`POST /api/courses/<course_id>/notes/chunk/` (`agent/views.py:ChunkNotesView`,
backed by `agent/services/chunk_notes.py`). It accepts
`multipart/form-data` (`file`, `lecture_id`, optional `date`, optional
`overwrite`), auto-detects notes (pdf/txt/md) vs. slide decks (`.pptx`) by
extension, chunks via a live Claude call, schema-validates, and writes
`courses/<course_id>/notes/<lecture_id>.json`. It already returns `409` with
an `existing_preview` when `lecture_id` collides and `overwrite` isn't set —
this is the same plan-then-pause contract `ExtractSyllabusView` uses, already
proven out in the Quiz/Dashboard integration passes and by direct CLI testing
(`manage.py chunk_notes`).

This is the third UI live-integration pass in this project (after Quiz and
Dashboard), following the same process: design spec → implementation plan →
worktree → implement → `finishing-a-development-branch`.

## What changes and why

**The button becomes universal, not PSYC201-only.** Every course card gets
"Upload notes," since adding lectures over time is normal usage, not a
one-time "first note" action. This means `has_notes`/`notes_count` need to be
correct and refreshed after every successful upload, for every course, not
just used once to decide whether to show an empty state.

**`dashboard.py`'s course summary gains a count, not just a boolean.**
`_course_summary()` currently exposes `"has_notes": bool(storage.read_notes(course_id))`.
The modal needs to suggest the next sequential lecture id (`lecture09` if 8
already exist) without a separate network round-trip, and the Dashboard tab
already fetches `/api/dashboard/` on mount — so this becomes
`"notes_count": len(notes)` instead of a bool, with `has_notes` derived from
it client-side (`notes_count > 0`) everywhere it's currently used. This is
the only backend change; the upload endpoint itself is untouched.

**No drag-and-drop.** `agent/static/agent/support.js` implements the full
React synthetic event set (`onChange`, `onClick`, `onSubmit`, drag-enter/
leave/over/start/end) but not `onDrop` — confirmed by grep, not assumed. A
click-to-browse `<input type="file">` is the only cleanly supported pattern
here, so that's what this uses.

**First controlled file input and first FormData POST in this codebase.**
Every existing input in the template (the Chat message box) is currently
uncontrolled/unwired. Every existing `fetch()` call (Quiz, Dashboard) POSTs
JSON with `Content-Type: application/json`. This introduces both a
controlled `<input type="file" onChange="...">` and a `FormData` POST
(browser sets the multipart boundary — no manual `Content-Type` header, but
`X-CSRFToken` is still required, same as the Quiz calls).

## Design

### 1. Backend change (`agent/services/dashboard.py`)

```python
def _course_summary(course_id: str) -> dict:
    ...
    notes = storage.read_notes(course_id)
    return {
        ...
        "notes_count": len(notes),
        ...
    }
```

Drop the old `"has_notes"` key entirely — every current reader in the
template switches to `courseMeta[s.course].notes_count > 0`.

### 2. Component state (`course_copilot.html`, `Component` class)

New state:

```js
uploadOpenFor,        // course_id the modal is open for, or null (modal closed)
uploadLectureId,      // text field value, pre-filled on open, user-editable
uploadDate,           // text field value, optional, blank by default
uploadFile,           // the selected File object, or null
uploadLoading,        // true while the chunk request is in flight
uploadError,          // error message string, or null
uploadConflict         // { existing_preview } when a 409 comes back, else null
```

`_uploadSeq` sequence counter, same stale-response guard pattern as
`_quizSeq`/`_dashSeq`/`_recentSeq`.

### 3. Opening/closing the modal

`openUpload(courseId)`: computes the next sequential id from
`this.state.courseMeta[courseId].notes_count` (`lecture{n+1 padded to 2 digits}`),
sets `uploadOpenFor: courseId, uploadLectureId: <suggested id>, uploadDate: '', uploadFile: null, uploadError: null, uploadConflict: null`.

`closeUpload()`: resets all `upload*` state to closed/empty. Called on
cancel, on backdrop click, and after a successful upload.

### 4. Submitting

```js
submitUpload(overwrite = false) {
  const s = this.state;
  if (!s.uploadFile || !s.uploadLectureId) return;
  const seq = ++this._uploadSeq;
  this.setState({ uploadLoading: true, uploadError: null, uploadConflict: null });

  const body = new FormData();
  body.append('file', s.uploadFile);
  body.append('lecture_id', s.uploadLectureId);
  if (s.uploadDate) body.append('date', s.uploadDate);
  if (overwrite) body.append('overwrite', 'true');

  fetch(`/api/courses/${s.uploadOpenFor}/notes/chunk/`, {
    method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') }, body
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

Conflict resolution: the conflict card shows `uploadConflict.existing_preview`
(lecture id, source, and topics — the same fields the endpoint already
returns, per `notes/<lecture_id>.json`'s schema) plus "Overwrite"
(`submitUpload(true)`) and
"Cancel" (clears `uploadConflict`, stays open so the id can be edited)
buttons. Mirrors `ExtractSyllabusView`'s 409 shape exactly — no new backend
error format.

### 5. Template changes

- "Upload notes" button added to **every** course card's action row (not
  just PSYC201's), `onClick="{{ () => this.openUpload('cs101') }}"` /
  `'psyc201'` respectively — same inline-arrow pattern already used for
  other per-course actions in this file.
- New modal block, gated on `{{ uploadOpenFor }}` being non-null, rendered
  once at the end of the Dashboard `sc-if` block (not per-card) so there's
  exactly one modal instance regardless of which card opened it.
- Modal contents: file input, lecture id text input (pre-filled, editable),
  date text input (optional), Cancel/Upload buttons. `uploadLoading` swaps
  the button row for the same lightweight loading treatment Quiz uses.
  `uploadError` and `uploadConflict` each get their own inline block within
  the modal, reusing `.card`/`.btn-secondary` — no new visual pattern.
- `.has_notes` is read directly off `courseMeta` in exactly 3 places —
  the `courseHasNotes` computed var (line ~580), and two Quiz-entry guards
  that check a specific course's meta before auto-loading a question (lines
  ~589, ~603). All three become `.notes_count > 0`. Every other `has_notes`
  usage (the 4 `sc-if` blocks gating Progress/Quiz/Dashboard empty states)
  already consumes the downstream `courseHasNotes` var and needs no change.

## Explicitly out of scope for this pass

- Drag-and-drop (framework doesn't cleanly support `onDrop` — see above).
- Browsing, renaming, or deleting existing lectures.
- Progress/Chat tabs staying wired to real data beyond the `notes_count`
  refresh they already inherit from `loadDashboard()` — no new work in
  either tab.
- Client-side file-type/size validation beyond the `accept` attribute — the
  backend already fails loudly and specifically (`unsupported file type`,
  `source file is empty`, etc.) and the error card surfaces that text
  as-is.

## Verification

- `python manage.py check` after the `dashboard.py` change.
- `python -m pytest -q` — `test_dashboard.py` needs its `has_notes`
  assertions updated to `notes_count`.
- Live browser pass (Playwright): upload a real `.txt` notes file to a course
  with existing lectures (e.g. CS101, currently `notes_count: 2`) — confirm
  the suggested id is `lecture03`, confirm the card's state refreshes after
  success without a reload, confirm the new lecture is queryable via Ask/Quiz
  afterward. Then trigger the 409 path deliberately (re-upload the same id)
  and confirm the overwrite-confirm flow works. Then trigger a 400 (e.g. an
  unsupported extension) and confirm the error card + retry work.
- Not more live-API calls than necessary — chunking costs real tokens per
  upload.
