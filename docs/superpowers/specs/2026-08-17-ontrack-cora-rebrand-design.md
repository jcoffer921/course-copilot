# OnTrack / Cora rebrand — design

## Context

The project has shipped under the working name "Course Copilot" throughout development. This pass renames the product to **OnTrack** and introduces a named assistant persona, **Cora** (Course Organization & Resource Assistant), that the chat UI and `ask.py`'s system prompt speak as. OnTrack is the app; Cora is who the user talks to inside it.

Scope was set via three explicit decisions:
1. Rebrand depth: cosmetic copy **and** assistant persona **and** internal naming (template filename, view function, URL name) — not just surface text.
2. The project's top-level folder (`course-copilot`) and the GitHub repo name stay as-is — renaming them mid-project risks breaking the open IDE session and isn't required for the rebrand to take effect.
3. "Cora" is named explicitly throughout the chat UI's microcopy (placeholder, empty state, grounding description), not just in the sidebar logo.

Historical dated documents under `docs/superpowers/plans/` and `docs/superpowers/specs/` are **not** rewritten — they're a record of past work under the prior name, not live branding surface.

## What changes and why

### 1. Assistant persona — `agent/services/ask.py`

`ASK_SYSTEM_PROMPT` currently opens directly with grounding rules and has no identity or tone language at all — a user asking "who are you?" gets whatever the model improvises, ungoverned by the system prompt. This pass adds an identity + tone paragraph at the very top of the prompt, before the existing "You answer questions..." sentence:

```
You are Cora, the AI academic assistant inside OnTrack — you help students stay on top of their \
semester. You answer questions about ONE course using ONLY the material provided below, plus — only \
when that material genuinely doesn't cover the question — real, cited results from a restricted web \
search when one is available to you. There is nothing else to draw on: never answer from \
general/training knowledge as if it were this course's material.

Identity and tone: If asked who you are or what you do, answer briefly and naturally as Cora — an \
assistant that helps organize syllabi, notes, deadlines, and answers grounded questions about a \
student's courses. Keep your "answer" text supportive and encouraging, like a well-organized study \
partner — clear and direct, never padded with filler or excessive enthusiasm. This identity and tone \
guidance never overrides the grounding rules below, and never justifies adding anything to the JSON \
output beyond the "answer" field itself.
```

This replaces only the opening sentence of the existing prompt (which becomes the second sentence of the merged paragraph) — every grounding tier, the JSON-only output contract, the `grounded`/`sources` schema, and the "no preamble" rule are unchanged. The identity paragraph is explicitly scoped to *how the `"answer"` field is written*, not license to break the strict single-JSON-object output the rest of the prompt (and `ask_async`'s parser) depends on.

**Verification of intent:** a live "who are you?" question against `cs101` should come back with `answer` identifying itself as Cora and describing what it does, still as valid JSON with `grounded: false` (the question isn't about course material) and `sources: []` — proving the identity clause doesn't leak outside the JSON envelope or corrupt `grounded` semantics.

### 2. Chat UI copy — `agent/templates/agent/course_copilot.html` (see §3 for the rename)

Four literal string changes, no logic/state changes:

| Location | Current | New |
|---|---|---|
| Sidebar logo (~line 32) | `Course Copilot` | `OnTrack` |
| `<head>` (currently no `<title>` at all) | *(none)* | `<title>OnTrack</title>` |
| Chat input placeholder (~line 493) | `Ask about this course's material...` | `Ask Cora about this course's material...` |
| Chat empty state (~line 458) | `Ask a question about {{ courseName }} to get started.` | `Ask Cora a question about {{ courseName }} to get started.` |
| `chatGroundingText` JS (~line 1018) | `'Answers are grounded only in this course\'s syllabus' + ...` | `'Cora only grounds answers in this course\'s syllabus' + ...` (same conditional notes/references clauses and trailing web-results clause, unchanged) |

The sidebar logo is app-wide identity (OnTrack, visible on every tab: Dashboard, Chat, Progress, Quiz). Cora is named specifically where the user is actually talking to the assistant — the Chat tab's input and grounding copy — not injected into unrelated tabs.

### 3. Internal renames

Three files reference the old `course_copilot` naming as an internal identifier, not just prose:

- **Template file:** `agent/templates/agent/course_copilot.html` → `agent/templates/agent/ontrack.html`
- **View function** (`agent/views.py`): `course_copilot_page` → `ontrack_page`, its docstring's `course_copilot.html` reference updated to `ontrack.html`, and its `render(request, "agent/course_copilot.html")` call updated to `"agent/ontrack.html"`
- **URL wiring** (`config/urls.py`): `from agent.views import course_copilot_page` → `from agent.views import ontrack_page`; `path("", course_copilot_page, name="course-copilot")` → `path("", ontrack_page, name="ontrack")`

Pure rename, no behavioral change — the view still does no I/O, just renders the template.

### 4. Docs

- **`README.md`:** title line `# Course Copilot — Quickstart` → `# OnTrack — Quickstart`, with one short intro line under the title naming Cora (e.g. "OnTrack keeps your semester organized. Cora — the Course Organization & Resource Assistant — answers grounded questions about your courses."). The rest of the README (architecture notes, setup steps, CLI examples) is unchanged — it documents the project's real Django/DRF/ASGI mechanics, not branding.
- **`CLAUDE.md`:** title line `# Course Copilot — Project Instructions` → `# OnTrack — Project Instructions`. The `## What this project is` paragraph is rewritten to introduce the OnTrack/Cora naming while preserving every existing factual claim (Anthropic API, scoped to current semester's coursework, answers questions/tracks deadlines/generates quizzes, grounded in actual syllabi and notes). No other section of CLAUDE.md (non-negotiable constraints, file structure, schemas, build order) changes — those describe the system, not the brand.

## Explicitly out of scope for this pass

- Renaming the top-level project folder (`course-copilot`) or the GitHub repo (`jcoffer921/course-copilot`).
- Renaming the Django app (`agent`) or any other internal Python package/module names beyond the three identifiers in §3.
- Rewriting historical dated documents under `docs/superpowers/plans/` and `docs/superpowers/specs/`.
- Any new UI elements, badges, or onboarding/intro moments introducing Cora (e.g. a "Meet Cora" splash) — this pass only changes existing copy strings, it doesn't add new UI surface.
- A favicon or other new static branding asset — none exists today, and adding one isn't part of this rename.

## Verification

- `python manage.py check` after the view/URL rename.
- Manual check: load `/`, confirm the page renders (no broken template reference), confirm the browser tab shows "OnTrack", confirm the sidebar logo reads "OnTrack" on every tab.
- Manual check: open the Chat tab, confirm the input placeholder and empty-state text name Cora, confirm `chatGroundingText` renders with "Cora only grounds answers in..." and the correct conditional clauses for a course with/without notes and references.
- Live-API check (skipped without `ANTHROPIC_API_KEY`): ask `cs101` "who are you?" — response should be valid JSON, `answer` should identify itself as Cora and describe what it does, `grounded: false`, `sources: []`.
- `grep -rn "course_copilot\|Course Copilot" agent/ config/ README.md CLAUDE.md` (excluding `docs/superpowers/`) should return nothing after this pass.
