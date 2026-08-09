# Quiz live integration — design

## Context

`agent/templates/agent/course_copilot.html` is a DC pseudo-component mockup (React under the hood, compiled at runtime by `agent/static/agent/support.js`) recently wired into the Django app under `agent/templates/agent/` + `agent/static/agent/`, served at `/` via `agent.views.course_copilot_page`. All four of its views (Dashboard, Progress, Quiz, Chat) currently run on hardcoded mock data.

The Django backend already has real, working endpoints for all of this under `/api/` (`agent/urls.py`, `agent/views.py`, `agent/services/*.py`), backed by real per-course data on disk (`courses/cs101/` has a full syllabus, two chunked lectures, quiz history, and mastery scores; `courses/psyc201/` has only a syllabus — which is exactly why the mock's PSYC201 empty state exists).

This is the first of several integration passes (Dashboard, Progress, and Chat will follow later as separate passes) — this one wires up **Quiz only**, since it's the one flow where both read (`generate`) and write (`record`) endpoints already exist server-side, giving the fastest fully-real end-to-end slice.

## What changes and why

**The quiz format itself changes.** `agent/services/quiz.py`'s `QUIZ_SYSTEM_PROMPT` only ever produces multiple-choice questions (exactly 4 choices, one correct) — there's no True/False or Short-Answer question type anywhere on the backend, and no server-side notion of a "3-question quiz session," just "generate one MC question" / "record one answer" as independent calls. The mock's 3-step MC→TF→SA sequence was invented UI variety with no backend behind two of the three steps. Making this real means the Quiz flow becomes **3 sequential real MC questions**, each independently generated and recorded against the live backend. This is a deliberate behavior change, not a bug — the alternative (keeping fake TF/SA steps) would mean shipping UI that lies about what the app does.

**Quiz generation is a live Anthropic API call** (`agent/services/quiz.py:generate_question_async`) — real latency, real token cost, per question. The workspace-root `.env` has `ANTHROPIC_API_KEY`, but Django reads env vars from `course-copilot/`'s own process environment, and nothing there loads a `.env` file today — `agent/services/client.py` raises `ValueError("ANTHROPIC_API_KEY environment variable is not set")` if it's absent. `python-dotenv` is already in `requirements.txt` and already installed in `venv/`, just not wired into `config/settings.py`. Fixing this is in scope here since Quiz can't work live without it.

## Design

### 1. Env wiring (`config/settings.py`)

Immediately after `BASE_DIR = Path(__file__).resolve().parent.parent`, add:
```python
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")
```
before the `os.environ.get(...)` calls that follow. Create `course-copilot/.env` (already covered by `course-copilot/.gitignore`'s `.env` entry) with `ANTHROPIC_API_KEY` copied in from the workspace-root `.env` — copied file-to-file, never printed to a terminal or logged.

### 2. Component state (`course_copilot.html`, `Component` class)

Replace:
```js
quizStep, quizMcAnswer, quizTf, quizSaAnswer
```
with:
```js
quizStep,            // 0..3, same meaning as today (3 = results)
quizQuestion,         // the live-generated question object, or null
quizMcAnswer,         // the user's currently-selected choice string, or null
quizCorrectCount,     // running tally, incremented only from real record() responses
quizLoading,          // true while a generate/record call is in flight
quizError             // backend/network error message, or null
```

`quizQuestion` shape (from `POST /api/courses/<id>/quiz/generate/`):
```json
{ "lecture_id": "...", "chunk_id": "...", "topic": "...", "question": "...", "choices": ["...", "...", "...", "..."], "correct_answer": "..." }
```

### 3. New method: `loadQuestion(courseId)`

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
```

No new question-type branching — MC is the only shape, so the three `isQuizStep0/1/2` template blocks collapse into one reusable "current question" card.

### 4. Flow changes

- **Entering Quiz** (`goQuiz`, `practiceWeak`, and switching the course chip while already on the Quiz tab): reset `quizStep: 0, quizCorrectCount: 0, quizMcAnswer: null, quizQuestion: null, quizError: null`, then call `this.loadQuestion(s.course)` — but only when the newly-selected course actually has notes (`courseHasNotes`); PSYC201 still short-circuits straight to the existing empty state, never touching the network.
- **Selecting an option**: sets `quizMcAnswer` to the clicked choice string (unchanged pattern from before, still local state, no network call).
- **"Check answer"**: `POST /api/courses/<id>/quiz/record/` with `{ lecture_id, chunk_id, topic, question, correct_answer, user_answer }` pulled from `quizQuestion` + `quizMcAnswer`. On success (`{ correct, correct_answer }`):
  - increment `quizCorrectCount` if `correct`
  - if `quizStep + 1 < 3`: advance `quizStep`, call `loadQuestion(s.course)` again for the next round
  - else: advance `quizStep` to `3` (results) — `quizCorrectCount` is already the real, accumulated total, no extra computation needed on the results screen
  - On failure: `quizError` set, stay on the current question (don't advance) so the user can retry the same "Check answer" click without losing their in-flight state.

### 5. Template changes

- Topic tag ("Weakest topic first · Recursion") becomes dynamic: `{{ quizQuestion.topic }}` when a question is loaded, a neutral "Loading…" label while `quizLoading` and no question yet.
- New `quizLoading` block: a lightweight loading state inside the existing `.card` shell (reuse `.card elev-md`, no new visual pattern).
- New `quizError` block: message + a "Try again" button that re-calls `loadQuestion(s.course)`. Reuses `.card` + `.btn-secondary`, same pattern as the empty-state cards already built.
- Results screen (`isQuizStep3`) is otherwise unchanged — it already reads `quizCorrectCount`, which is now real.

## Explicitly out of scope for this pass

Dashboard, Progress, and Chat stay on mock data — separate integration passes later. Completing a real quiz round does **not** yet update Progress's mastery display (even though the backend's `record_attempt` does rebuild `mastery_scores.json` server-side) — that wiring is part of the Progress pass.

## Verification

- `python manage.py check` after the settings.py change.
- One full live 3-question CS101 round through the browser (Playwright): confirm each question is different/real (not the old hardcoded Fibonacci/RecursionError/LinearSearch text), confirm the results screen shows an accurate real tally, confirm PSYC201 still shows the empty state without any network call.
- Trigger the error path once (e.g. temporarily unset the env var or hit a bad course id) to confirm the error card + retry button work, then confirm the real path still works afterward.
- Not more live-API calls than necessary — this costs real tokens per question.
