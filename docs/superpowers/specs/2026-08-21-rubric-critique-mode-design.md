# Rubric Critique Mode — Design

## Problem

OnTrack's non-negotiable constraints have named rubric critique mode since
v1 ("Rubric critique mode never writes the assignment for the user.
Scaffold, question, and critique only.") and `client.py` already reserves
an Opus model constant for it, but the feature itself was never built —
it's the last major piece of the original project scope.

Students have no way to get feedback on in-progress work against a rubric
without either not asking at all, or risking a generic AI tool that just
writes the assignment for them. This plan adds a single-shot critique flow:
submit a draft and a rubric, scoped to one course, and get back a
structured critique that pushes the student to improve their own work —
never a rewrite, never example text.

## Decisions

- **Single-shot, not conversational.** One request (draft + rubric) produces
  one structured critique response. No multi-turn session, no follow-up
  chat — unlike `ask.py`, which is genuinely conversational. If a student
  wants another critique after revising, they submit again.
- **Rubric is supplied fresh every time, never persisted.** No new
  `rubric.json` or similar. The student pastes or uploads their rubric
  alongside their draft on every request. Simpler than a saved-rubric
  concept, and rubrics are usually assignment-specific and used once per
  assignment anyway.
- **Draft and rubric both accept paste or file upload** (pdf/txt/md), reusing
  `syllabus_extraction.extract_text_from_bytes` — the same helper
  notes/references/syllabus extraction already share. Consistent with the
  rest of the app rather than inventing a text-only special case.
- **Grounded in the course's own material** (syllabus/notes/references),
  same tiered grounding rules `ask.py`'s system prompt already enforces —
  so the critique can flag a misapplied course concept (citing where),
  not just generic rubric-vs-draft matching. Requires the student to pick
  a course; 404s if that course has no syllabus.json yet (same as `ask.py`).
- **No persistence of the critique itself.** Nothing is logged or saved —
  no `critique_history.json`. If the student wants to keep a critique, they
  copy it themselves. Matches the "nothing new to persist" shape the
  "rubric supplied fresh every time" decision already implies.
- **Uses `MODEL_RUBRIC_CRITIQUE` (Opus)**, not the `MODEL_DEFAULT` (Sonnet)
  every other LLM-calling service uses — already reserved for exactly this
  in `client.py`'s existing comment. Trades cost for reasoning quality on a
  task where catching what's *almost* right but not quite matters more than
  latency or cost.
- **New "Critique" nav tab**, not a mode bolted onto the existing "Ask Cora"
  chat tab — the input shape (course + draft + rubric, one submission) is
  different enough from a chat thread that reusing that tab's layout would
  fight its own conventions rather than reuse them cleanly.

## Architecture

- `agent/services/rubric_critique.py` (new): `CRITIQUE_SYSTEM_PROMPT` +
  `critique_async(course_id: str, draft_text: str, rubric_text: str) -> dict`.
  Reads syllabus/notes/references the same way `ask_async` does for
  grounding context, calls the Anthropic API on `MODEL_RUBRIC_CRITIQUE`, and
  parses a JSON response — no session, no history. Raises
  `storage.CourseNotFoundError` if `course_id` has no syllabus.json yet
  (mirrors `ask_async`'s own check), and a plain `ValueError` for any
  API-layer failure (missing key, malformed JSON response, truncated
  response) — matching `ask_async`'s and `extract_syllabus_async`'s own
  error conventions, so the view can catch it identically.

  Response shape:
  ```json
  {
    "overall_assessment": "string",
    "criteria": [
      {"criterion": "string", "meets_criterion": "yes|partial|no", "questions": ["string", ...]}
    ],
    "general_questions": ["string", ...]
  }
  ```
  `criteria` is the per-rubric-item breakdown (one entry per criterion the
  model identifies in the supplied rubric); `general_questions` covers
  cross-cutting issues that don't map to a single criterion (e.g. overall
  structure, clarity). The system prompt's core rule: never produce
  replacement or example text for any part of the draft — surface a
  pointed question instead of showing what a fix looks like.

- `agent/serializers.py`: `CritiqueRequestSerializer` — `draft_text` or
  `draft_file` (exactly one required; both present, or both absent, is a
  400 — an ambiguous request rather than a silent pick), `rubric_text` or
  `rubric_file` (same exactly-one rule, independent of which form the
  draft took).

- `agent/views.py`: `CritiqueView` — `POST /api/courses/<course_id>/critique/`.
  Resolves any uploaded file to plain text via
  `syllabus_extraction.extract_text_from_bytes` before calling
  `critique_async`, so the service function's own signature stays plain
  strings regardless of how the input arrived (matching how `ExtractSyllabusView`
  separates "resolve upload to text" from the extraction call itself).
  Error mapping, following `ExtractSyllabusView`'s established pattern:
  - Serializer validation failure (both text and file missing/blank for
    either field, or neither provided) → 400
  - `storage.InvalidCourseIdError` → 400
  - `storage.CourseNotFoundError` → 404
  - File-extraction `ValueError` (unsupported type, empty/unreadable file)
    → 400
  - `critique_async`'s `ValueError` (API-layer failure) → 502

- `agent/urls.py`: the new route, URL name `course-critique`.

- `agent/management/commands/critique.py` (new): CLI wrapper —
  `--draft <path>` or `--draft-text`, `--rubric <path>` or `--rubric-text`,
  positional `course_id` — same dual-mode (file-or-text) pattern the view
  itself uses, wrapping `critique_async` with `asyncio.run()` like every
  other async service's CLI command.

- `agent/templates/agent/ontrack.html`: new "Critique" nav tab — course
  picker (reusing `realCourseIds`, same as the Deadlines tab's course
  dropdown), a draft input (textarea + file-upload toggle), a rubric input
  (same shape), a submit button, and a rendered response: overall
  assessment, then each criterion with its questions, then general
  questions. No persistence means no list view, no history — the tab is
  just the input form and the most recent response.

## Non-goals

- Saved/reusable rubrics (a `rubric.json` or similar) — deferred; every
  request supplies its own rubric text/file fresh.
- Critique history/logging — nothing is saved after the response is shown.
- Multi-turn refinement ("now critique just section 2") — a student wanting
  another pass resubmits with their revised draft.
- Rewriting or providing example replacement text for any part of the
  draft — this is the entire point of the feature, enforced by the system
  prompt, not just a missing nice-to-have.
- Grading or scoring the draft numerically — this is qualitative feedback
  (`meets_criterion: yes/partial/no` + questions), not a grade prediction;
  that's what the existing Grade Calculator (`grades.py`) is for, and it
  operates on entered scores, not draft content.

## Testing

- `rubric_critique.py`: live-API test file (`agent/tests/test_rubric_critique.py`),
  module-level `skipif` on `ANTHROPIC_API_KEY` unset — same convention as
  `test_ask.py`. Verifies against `cs101`'s existing fixture data that a
  real critique response parses into the expected shape, that no criterion
  or general question contains obvious replacement text (a heuristic check,
  not a hard guarantee — the system prompt is the real enforcement), and
  that a course-specific concept (from `cs101`'s notes) gets correctly
  flagged when the supplied draft misapplies it.
- View-layer tests in `test_views.py` (mocked, no live key needed): 400 on
  missing draft/rubric text-or-file, 400 on an unsupported file type, 404
  on a course with no syllabus.json, 502 on a mocked API-layer failure —
  mirroring how `AskView`'s own error paths are tested today (mocking the
  service call's failure mode, not hitting the real API).
