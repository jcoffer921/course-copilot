# Quiz Live Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Quiz tab of `course_copilot.html` to the real `/api/courses/<id>/quiz/generate/` and `/quiz/record/` endpoints, replacing its hardcoded MC/TF/SA mock steps with 3 sequential real multiple-choice questions.

**Architecture:** Two independent slices. (1) `config/settings.py` loads `.env` via `python-dotenv` so `ANTHROPIC_API_KEY` reaches the Django process — a prerequisite for any live Anthropic call, not quiz-specific. (2) `course_copilot.html`'s `Component` class gains new state (`quizQuestion`, `quizCorrectCount`, `quizLoading`, `quizError`) and two methods (`loadQuestion`, `checkAnswer`) that call the live endpoints via `fetch`; the three separate MC/TF/SA template blocks collapse into one reusable "current question" card driven by `quizQuestion`.

**Tech Stack:** Django 6 (ASGI), adrf async views (already built, no changes), `python-dotenv`, vanilla JS `fetch` inside a DC pseudo-component template (no build step, no JS test runner — this repo has none).

## Global Constraints

- Never print, log, or paste the `ANTHROPIC_API_KEY` value anywhere (terminal output, commit, or this plan) — copy it file-to-file only.
- No new question-type branching: MC is the only shape produced by the backend today. Do not add TF/SA handling anywhere.
- Dashboard, Progress, and Chat stay on mock data — do not touch them in this plan.
- Don't wire quiz completion into Progress's mastery display — out of scope for this pass even though `record_attempt` already rebuilds `mastery_scores.json` server-side.
- Minimize live Anthropic API calls during verification — each `generate` call costs real tokens.

---

### Task 1: Env wiring so `ANTHROPIC_API_KEY` reaches Django

**Files:**
- Modify: `config/settings.py:1-4`
- Create: `course-copilot/.env` (already covered by `.gitignore`'s `.env` entry — verify, don't re-add)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ANTHROPIC_API_KEY` present in `os.environ` by the time `agent/services/client.py:get_client()` runs, for every later task in this plan (and every other live-API service) to rely on.

- [ ] **Step 1: Add `load_dotenv` to settings.py**

Edit `config/settings.py`, immediately after the `BASE_DIR` line:

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me-before-any-real-deploy")
```

- [ ] **Step 2: Confirm `.env` is gitignored**

Run: `git check-ignore -v course-copilot/.env` (from the workspace root, i.e. `c:\Users\jcoff\course-copliot-agent`)
Expected: prints a match against `course-copilot/.gitignore:1:.env` — confirms the file about to be created can never be committed.

- [ ] **Step 3: Copy the API key file-to-file (never transcribe the value)**

From `course-copilot/` (PowerShell):
```powershell
Copy-Item ..\.env .env
```
This copies the workspace-root `.env` (which contains only `ANTHROPIC_API_KEY=...`) byte-for-byte into `course-copilot/.env`. Do not open the file and retype its contents — that risks the value ending up in a terminal scrollback or a pasted log.

- [ ] **Step 4: Verify Django picks it up**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

Run: `python manage.py shell -c "import os; print('ANTHROPIC_API_KEY' in os.environ)"`
Expected: `True` — confirms the key loaded without ever printing its value.

- [ ] **Step 5: Commit**

```bash
git add config/settings.py
git commit -m "Load .env in Django settings so ANTHROPIC_API_KEY reaches the process"
```

`course-copilot/.env` itself must NOT be staged (it's gitignored — `git status` should show it as untracked-and-ignored, not appear at all under `git add -A` or `git status --porcelain`; confirm with `git status --porcelain course-copilot/.env` printing nothing).

---

### Task 2: Wire the Quiz tab to live `generate`/`record` endpoints

**Files:**
- Modify: `agent/templates/agent/course_copilot.html`
  - `state = {...}` block (~line 399-402)
  - `renderVals()` body (~line 424 onward): `setTab`, `selectCs101`/`selectPsyc`→`selectCourse`, quiz-related locals (`MC_CORRECT`, `mcOptionStyle`, `mcOptions`, `mcCorrect`/`tfCorrect`/`saCorrect`/`quizCorrectCount`, `quizDots`), and the returned props object (~line 542-582)
  - New class methods: `loadQuestion`, `checkAnswer`
  - Quiz template block (~line 265-342): topic tag, loading/error cards, collapsed question card, results card

**Interfaces:**
- Consumes: `POST /api/courses/<course_id>/quiz/generate/` → `{ lecture_id, chunk_id, topic, question, choices: string[], correct_answer }` or `{ detail: string }` on error (`agent/views.py:182-216`). `POST /api/courses/<course_id>/quiz/record/` with `{ lecture_id, chunk_id, topic, question, correct_answer, user_answer }` → `{ correct: bool, correct_answer: string }` or `{ detail: string }` on error (`agent/views.py:219-243`, `agent/serializers.py:27-33` — all six record fields are required, non-blank strings).
- Produces: nothing consumed outside this file — Quiz is a self-contained tab.

- [ ] **Step 1: Replace quiz state fields**

In the `state = {...}` block, replace:
```js
quizStep: 0, quizMcAnswer: null, quizTf: null, quizSaAnswer: ''
```
with:
```js
quizStep: 0, quizQuestion: null, quizMcAnswer: null,
quizCorrectCount: 0, quizLoading: false, quizError: null
```

- [ ] **Step 2: Add `loadQuestion` and `checkAnswer` methods to the `Component` class**

Add both as methods on `Component` (alongside `navBtn`/`courseChip`/`renderVals`):

```js
loadQuestion(courseId) {
  this.setState({ quizLoading: true, quizError: null, quizQuestion: null, quizMcAnswer: null });
  fetch(`/api/courses/${courseId}/quiz/generate/`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
  })
    .then(r => r.json().then(data => ({ ok: r.ok, data })))
    .then(({ ok, data }) => {
      if (!ok) { this.setState({ quizLoading: false, quizError: data.detail || 'Could not generate a question.' }); return; }
      this.setState({ quizLoading: false, quizQuestion: data });
    })
    .catch(e => this.setState({ quizLoading: false, quizError: 'Network error: ' + e.message }));
}

checkAnswer(courseId) {
  const s = this.state;
  if (!s.quizQuestion || s.quizMcAnswer == null) return;
  const q = s.quizQuestion;
  this.setState({ quizLoading: true, quizError: null });
  fetch(`/api/courses/${courseId}/quiz/record/`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lecture_id: q.lecture_id, chunk_id: q.chunk_id, topic: q.topic,
      question: q.question, correct_answer: q.correct_answer, user_answer: s.quizMcAnswer
    })
  })
    .then(r => r.json().then(data => ({ ok: r.ok, data })))
    .then(({ ok, data }) => {
      if (!ok) { this.setState({ quizLoading: false, quizError: data.detail || 'Could not record your answer.' }); return; }
      const nextCount = this.state.quizCorrectCount + (data.correct ? 1 : 0);
      if (this.state.quizStep + 1 < 3) {
        this.setState({ quizLoading: false, quizCorrectCount: nextCount, quizStep: this.state.quizStep + 1 });
        this.loadQuestion(courseId);
      } else {
        this.setState({ quizLoading: false, quizCorrectCount: nextCount, quizStep: 3 });
      }
    })
    .catch(e => this.setState({ quizLoading: false, quizError: 'Network error: ' + e.message }));
}
```

`checkAnswer` no-ops if nothing is selected yet (`quizMcAnswer == null`), so the button stays inert rather than sending a blank `user_answer` the backend serializer would reject. On failure it only sets `quizLoading: false` and `quizError` — `quizQuestion`/`quizMcAnswer`/`quizStep` are left untouched, so a retry click re-sends the same in-flight answer instead of losing it.

- [ ] **Step 3: Rewire tab/course switches to trigger `loadQuestion`**

Replace `setTab` (inside `renderVals()`):
```js
const setTab = (t) => {
  if (t === 'quiz') {
    this.setState({ tab: t, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
    if (courseHasNotes) this.loadQuestion(s.course);
  } else {
    this.setState({ tab: t });
  }
};
```
(`courseHasNotes` here is the existing local already computed a few lines below from `cd = courseData[s.course]` — keep it defined before this closure runs, i.e. above `setTab`, matching where `cd`/`courseHasNotes` already sit in the current file.)

Replace `selectCs101: () => this.setState({ course: 'cs101' })` and `selectPsyc: () => this.setState({ course: 'psyc201' })` in the returned props object with a shared helper defined next to `setTab`:
```js
const selectCourse = (courseId) => {
  if (s.tab === 'quiz') {
    this.setState({ course: courseId, quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null });
    if (courseData[courseId].hasNotes) this.loadQuestion(courseId);
  } else {
    this.setState({ course: courseId });
  }
};
```
and in the returned props object:
```js
selectCs101: () => selectCourse('cs101'),
selectPsyc: () => selectCourse('psyc201'),
```
`practiceWeak: () => setTab('quiz')` stays as-is — it already routes through the now-upgraded `setTab`.

- [ ] **Step 4: Replace mock scoring locals with live-question-driven ones**

Delete these locals (mock-only, now dead): `MC_CORRECT`, `mcCorrect`, `tfCorrect`, `saCorrect`, the old `quizCorrectCount` computed-from-mock-state line.

Replace the `mcOptionStyle`/`mcOptions` block with:
```js
const mcOptionStyle = (selected) => 'width:100%;text-align:left;padding:13px 15px;border-radius:var(--radius-lg);cursor:pointer;font-size:14px;font-family:var(--font-body);' +
  (selected ? 'border:1px solid var(--color-accent-700);background:var(--color-accent-100);font-weight:600' : 'border:1px solid var(--color-neutral-200);background:#fff');
const mcOptions = (s.quizQuestion ? s.quizQuestion.choices : []).map(label => ({
  label: label,
  onClick: () => this.setState({ quizMcAnswer: label }),
  style: mcOptionStyle(s.quizMcAnswer === label)
}));
const quizTopicLabel = s.quizQuestion ? s.quizQuestion.topic : (s.quizError ? '—' : 'Loading…');
const showQuizQuestion = !s.quizLoading && !s.quizError && !!s.quizQuestion && s.quizStep < 3;
```
(`quizDots` is unchanged — it already reads `s.quizStep`, which still means the same thing.)

- [ ] **Step 5: Update the returned props object**

In the `return { ... }` object of `renderVals()`:
- Remove: `isTfTrue`, `isTfFalse`, `selectTfTrue`, `selectTfFalse`, `quizSaAnswer`, `setSaAnswer`, `quizNext`.
- Add: `quizTopicLabel: quizTopicLabel`, `showQuizQuestion: showQuizQuestion`, `quizLoading: s.quizLoading`, `quizError: s.quizError`, `checkAnswer: () => this.checkAnswer(s.course)`.
- `quizCorrectCount: quizCorrectCount` becomes `quizCorrectCount: s.quizCorrectCount` (now real state, not a derived mock).
- Keep `isQuizStep0`/`isQuizStep1`/`isQuizStep2` removed (no longer used by the template after Step 6) but keep `isQuizStep3: s.quizStep === 3` and `quizPos: s.quizStep + 1`.

- [ ] **Step 6: Collapse the template's three quiz-step blocks into one**

In the Quiz section (inside `<sc-if value="{{ courseHasNotes }}">`, currently lines ~277-330):

Replace both hardcoded topic-tag spans (`Weakest topic first · Recursion`, appearing once in the "not step 3" header and once in the "step 3" header) with `{{ quizTopicLabel }}`.

Replace the three separate blocks (`isQuizStep0` MC / `isQuizStep1` TF / `isQuizStep2` SA) with:
```html
<sc-if value="{{ quizLoading }}" hint-placeholder-val="{{ false }}">
  <div class="card elev-md" style="padding:var(--space-6);text-align:center;opacity:.7">
    Loading question…
  </div>
</sc-if>

<sc-if value="{{ quizError }}" hint-placeholder-val="{{ false }}">
  <div class="card elev-md" style="padding:var(--space-6)">
    <p class="card-body" style="margin:0 0 var(--space-4)">{{ quizError }}</p>
    <button type="button" class="btn btn-secondary btn-block" onClick="{{ retryQuiz }}">Try again</button>
  </div>
</sc-if>

<sc-if value="{{ showQuizQuestion }}" hint-placeholder-val="{{ true }}">
  <div class="card elev-md" style="padding:var(--space-6)">
    <span class="tag tag-outline" style="margin-bottom:var(--space-3);display:inline-block">Multiple choice</span>
    <div style="font-family:var(--font-heading);font-size:20px;line-height:1.35;margin-bottom:var(--space-6)">{{ quizQuestionText }}</div>
    <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:var(--space-6)">
      <sc-for list="{{ mcOptions }}" as="opt" hint-placeholder-count="4">
        <button type="button" onClick="{{ opt.onClick }}" style="{{ opt.style }}">{{ opt.label }}</button>
      </sc-for>
    </div>
    <button type="button" class="btn btn-primary btn-block" onClick="{{ checkAnswer }}">Check answer</button>
  </div>
</sc-if>
```
Leave the `isQuizStep3` results block exactly as-is (spec: "otherwise unchanged").

Add two more props to the `return { ... }` object from Step 5: `quizQuestionText: s.quizQuestion ? s.quizQuestion.question : ''` and `retryQuiz: () => this.loadQuestion(s.course)`.

- [ ] **Step 7: `manage.py check` sanity pass**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).` (template/JS changes don't affect Django checks directly, but this confirms Task 1's settings edit and this task's `urls.py`/`views.py`-adjacent files are still intact — cheap to re-run.)

- [ ] **Step 8: Live browser verification (uses the `run` skill or Playwright MCP tools)**

Start the app per this project's own run instructions, then in a browser:
1. Go to `/`, select CS101, click "Quiz". Confirm a real generated question appears (not the old hardcoded "naive recursive Fibonacci" text) and the topic tag shows a real topic string instead of "Loading…".
2. Answer all 3 questions (any option each time), clicking "Check answer" each time. Confirm each of the 3 questions is different (a fresh live-generated question), and the results screen shows a tally that matches how many you actually got right (cross-check against the `correct_answer` shown transiently isn't possible since it's hidden — instead verify by intentionally answering one you're confident is right/wrong and confirming the tally increments accordingly).
3. Switch to PSYC201 while on the Quiz tab. Confirm the empty-state card appears immediately with no loading spinner and no network request fires (check the browser's network tab — zero requests to `/api/courses/psyc201/quiz/`).
4. Trigger the error path once: temporarily rename `course-copilot/.env` (`Move-Item .env .env.bak`), restart the server, click into Quiz. Confirm the error card + "Try again" button render. Restore the file (`Move-Item .env.bak .env`), restart the server, click "Try again", confirm a real question now loads.

Keep total live `generate` calls during this pass to what's needed above (one 3-question round plus one retry-after-error check) — each call costs real tokens.

- [ ] **Step 9: Commit**

```bash
git add agent/templates/agent/course_copilot.html
git commit -m "Wire Quiz tab to live generate/record endpoints, drop mock TF/SA steps"
```

---

## Explicitly out of scope (per spec, do not implement here)

- Dashboard, Progress, Chat live wiring — later passes.
- Updating Progress's mastery display after a quiz round — `mastery_scores.json` already rebuilds server-side; the UI read of it is a separate pass.
- Any True/False or Short-Answer question type — no backend support exists for either.
