# OnTrack / Cora Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product from "Course Copilot" to **OnTrack**, and introduce the named assistant persona **Cora** in the chat UI and `ask.py`'s system prompt — across copy, persona, and the three internal identifiers that carry the old name.

**Architecture:** Pure rename/copy pass, no behavioral or schema changes. Five sequential tasks: (1) assistant persona in `ask.py`'s system prompt, (2) chat UI copy strings, (3) internal identifier renames (template file, view function, URL name), (4) docs (`README.md`, `CLAUDE.md`), (5) final repo-wide verification sweep.

**Tech Stack:** Django (sync view + template), `adrf`/DRF async views, AsyncAnthropic, pytest (pytest-django + pytest-asyncio, live-API tests skip cleanly without `ANTHROPIC_API_KEY`).

## Global Constraints

- Rebrand depth: cosmetic copy **and** assistant persona **and** internal naming (template filename, view function, URL name) — not just surface text.
- The top-level project folder (`course-copilot`) and the GitHub repo name (`jcoffer921/course-copilot`) stay as-is — do not rename them.
- "Cora" must be named explicitly in the chat UI's microcopy (placeholder, empty state, grounding description) — not only in the sidebar logo.
- Do not rewrite historical dated documents under `docs/superpowers/plans/` or `docs/superpowers/specs/` — they record past work under the prior name.
- Do not rename the Django app (`agent`) or any internal Python package/module beyond the three identifiers in Task 3.
- Do not add new UI elements, badges, onboarding moments, or a favicon introducing Cora/OnTrack — this pass only changes existing copy strings.

---

### Task 1: Assistant persona — `agent/services/ask.py`

**Files:**
- Modify: `agent/services/ask.py:18-21` (opening of `ASK_SYSTEM_PROMPT`)
- Test: `agent/tests/test_ask.py` (add one new live test, following this file's existing skip-without-API-key pattern)

**Interfaces:**
- Consumes: nothing new — `ask_async(course_id: str, question: str, session_id: str = None) -> dict` keeps its existing signature and JSON return shape (`answer`, `grounded`, `sources`).
- Produces: `ASK_SYSTEM_PROMPT` (module-level `str` in `agent/services/ask.py`) — same name and type, now opens with an identity+tone paragraph before "Grounding tiers, in order:". No other module in the codebase imports or depends on this constant's exact contents.

- [ ] **Step 1: Write the failing test**

Add to the end of `agent/tests/test_ask.py` (it already has `pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), ...)` at the top of the file, so this new test inherits the same skip-without-key behavior as every other test in it):

```python
async def test_identity_question_answers_as_cora():
    """Asking who the assistant is should be answered in character as Cora,
    still inside the required JSON envelope — proving the identity clause
    doesn't leak outside the JSON contract or corrupt grounded/sources
    semantics for a question that isn't about course material."""
    result = await ask_async(COURSE_ID, "Who are you and what do you do?")

    assert "cora" in result["answer"].lower()
    assert result["grounded"] is False
    assert result["sources"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest agent/tests/test_ask.py::test_identity_question_answers_as_cora -v`
Expected: without `ANTHROPIC_API_KEY` set, `SKIPPED`. With the key set and `courses/cs101` fixture data present, `FAIL` — the current prompt has no identity language, so the model's self-description is unlikely to contain "cora".

- [ ] **Step 3: Implement the prompt change**

In `agent/services/ask.py`, replace the opening of `ASK_SYSTEM_PROMPT`:

```python
ASK_SYSTEM_PROMPT = """You answer questions about ONE course using ONLY the material provided below, \
plus — only when that material genuinely doesn't cover the question — real, cited results from a \
restricted web search when one is available to you. There is nothing else to draw on: never answer \
from general/training knowledge as if it were this course's material.

Grounding tiers, in order:
```

with:

```python
ASK_SYSTEM_PROMPT = """You are Cora, the AI academic assistant inside OnTrack — you help students stay on top of their \
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

Grounding tiers, in order:
```

Every line from `Rules:` through the end of the docstring (the JSON-only output contract, the `grounded`/`sources` schema, the "no preamble" rule) is unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest agent/tests/test_ask.py::test_identity_question_answers_as_cora -v`
Expected: `PASS` (or `SKIPPED` if `ANTHROPIC_API_KEY` isn't set — that's still a valid green state for this step, matching how every other test in this file behaves).

- [ ] **Step 5: Run the full existing ask.py test suite to confirm no regression**

Run: `pytest agent/tests/test_ask.py agent/tests/test_ask_grounding.py -v`
Expected: all `PASS` or `SKIPPED` — none of the existing tests assert on the prompt's literal text, only on `grounded`/`sources`/`answer` behavior, so the added identity paragraph should not break them.

- [ ] **Step 6: Commit**

```bash
git add agent/services/ask.py agent/tests/test_ask.py
git commit -m "feat: give ask.py's assistant an identity as Cora"
```

---

### Task 2: Chat UI copy — `agent/templates/agent/course_copilot.html`

**Files:**
- Modify: `agent/templates/agent/course_copilot.html:4-8` (add `<title>`), `:32` (sidebar logo), `:458` (empty state), `:493` (input placeholder), `:1018` (`chatGroundingText` JS)

**Interfaces:**
- Consumes: nothing — pure string literals inside a template already rendered by `course_copilot_page` (renamed in Task 3).
- Produces: nothing new consumed elsewhere — these are leaf UI strings.

This task edits the template while it is still named `course_copilot.html`; the file rename itself happens in Task 3 so each task stays independently testable (this task's diff is pure copy, Task 3's diff is pure rename).

- [ ] **Step 1: Confirm current copy (baseline)**

Run: `grep -n "Course Copilot\|Ask about this course\|Ask a question about\|Answers are grounded only" agent/templates/agent/course_copilot.html`
Expected output includes all four current strings:
```
32:      <div style="font-family:var(--font-heading);font-size:16px;line-height:1.1">Course Copilot</div>
458:              <div style="text-align:center;opacity:.5;font-size:13px;padding:var(--space-8) 0">Ask a question about {{ courseName }} to get started.</div>
493:            <input class="input" placeholder="Ask about this course's material..." style="flex:1" value="{{ chatInput }}" onChange="{{ onChatInputChange }}"/>
1018:    const chatGroundingText = 'Answers are grounded only in this course\'s syllabus'
```

- [ ] **Step 2: Add a `<title>` tag**

The `<head>` block currently has no `<title>` at all:

```html
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="{% static 'agent/support.js' %}"></script>
</head>
```

Replace with:

```html
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OnTrack</title>
<script src="{% static 'agent/support.js' %}"></script>
</head>
```

- [ ] **Step 3: Rename the sidebar logo**

Replace (line 32):

```html
      <div style="font-family:var(--font-heading);font-size:16px;line-height:1.1">Course Copilot</div>
```

with:

```html
      <div style="font-family:var(--font-heading);font-size:16px;line-height:1.1">OnTrack</div>
```

- [ ] **Step 4: Name Cora in the chat empty state**

Replace (line 458):

```html
              <div style="text-align:center;opacity:.5;font-size:13px;padding:var(--space-8) 0">Ask a question about {{ courseName }} to get started.</div>
```

with:

```html
              <div style="text-align:center;opacity:.5;font-size:13px;padding:var(--space-8) 0">Ask Cora a question about {{ courseName }} to get started.</div>
```

- [ ] **Step 5: Name Cora in the chat input placeholder**

Replace (line 493):

```html
            <input class="input" placeholder="Ask about this course's material..." style="flex:1" value="{{ chatInput }}" onChange="{{ onChatInputChange }}"/>
```

with:

```html
            <input class="input" placeholder="Ask Cora about this course's material..." style="flex:1" value="{{ chatInput }}" onChange="{{ onChatInputChange }}"/>
```

- [ ] **Step 6: Name Cora in `chatGroundingText`**

Replace (line 1018):

```javascript
    const chatGroundingText = 'Answers are grounded only in this course\'s syllabus'
```

with:

```javascript
    const chatGroundingText = 'Cora only grounds answers in this course\'s syllabus'
```

The conditional notes/references clauses on lines 1019-1021 and the trailing web-results clause are unchanged.

- [ ] **Step 7: Verify the edits**

Run: `grep -n "Course Copilot\|Ask about this course\|Ask a question about\|Answers are grounded only" agent/templates/agent/course_copilot.html`
Expected: no output (all four old strings gone).

Run: `grep -n "OnTrack\|Ask Cora\|Cora only grounds" agent/templates/agent/course_copilot.html`
Expected: matches on the new `<title>`, sidebar logo, empty state, placeholder, and `chatGroundingText` lines.

- [ ] **Step 8: Manual browser check**

Start the dev server (see `README.md`'s "Option B: Run the API server"), load `/`, and confirm: the browser tab reads "OnTrack", the sidebar logo reads "OnTrack", the Chat tab's empty state and input placeholder both name Cora, and the grounding text under the input reads "Cora only grounds answers in...".

- [ ] **Step 9: Commit**

```bash
git add agent/templates/agent/course_copilot.html
git commit -m "feat: rebrand chat UI copy to OnTrack/Cora"
```

---

### Task 3: Internal renames — template file, view function, URL wiring

**Files:**
- Rename: `agent/templates/agent/course_copilot.html` → `agent/templates/agent/ontrack.html`
- Modify: `agent/views.py:524-533` (`course_copilot_page` → `ontrack_page`)
- Modify: `config/urls.py:4,9` (import and `path()`)

**Interfaces:**
- Consumes: the template file produced by Task 2 (with OnTrack/Cora copy already in place).
- Produces: view function `ontrack_page(request)` (plain sync Django view, same signature as the old `course_copilot_page(request)`) mounted at URL name `"ontrack"` — nothing downstream currently references the old `course-copilot` URL name (confirmed: no other file in the repo references it).

- [ ] **Step 1: Rename the template file**

```bash
git mv agent/templates/agent/course_copilot.html agent/templates/agent/ontrack.html
```

- [ ] **Step 2: Rename the view function in `agent/views.py`**

Replace (lines 524-533):

```python
def course_copilot_page(request):
    """GET / — serves the Course Copilot UI mockup (DC pseudo-component app).

    Plain sync Django view, not a DRF/adrf endpoint: it does no I/O, just
    renders a template. The template's DC bindings use the same `{{ }}`
    syntax as Django's own template language, so the whole app body is
    wrapped in `{% verbatim %}` in course_copilot.html to keep Django from
    trying to resolve them itself.
    """
    return render(request, "agent/course_copilot.html")
```

with:

```python
def ontrack_page(request):
    """GET / — serves the OnTrack UI mockup (DC pseudo-component app).

    Plain sync Django view, not a DRF/adrf endpoint: it does no I/O, just
    renders a template. The template's DC bindings use the same `{{ }}`
    syntax as Django's own template language, so the whole app body is
    wrapped in `{% verbatim %}` in ontrack.html to keep Django from
    trying to resolve them itself.
    """
    return render(request, "agent/ontrack.html")
```

- [ ] **Step 3: Update `config/urls.py`**

Replace:

```python
from agent.views import course_copilot_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agent.urls")),
    path("", course_copilot_page, name="course-copilot"),
]
```

with:

```python
from agent.views import ontrack_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agent.urls")),
    path("", ontrack_page, name="ontrack"),
]
```

- [ ] **Step 4: Run Django's system check**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).` — this catches a broken template reference or a bad import immediately.

- [ ] **Step 5: Manual check**

Start the dev server, load `/`, and confirm the page renders with no broken-template error (this re-confirms Task 2's manual check still holds after the rename).

- [ ] **Step 6: Commit**

```bash
git add agent/templates/agent/ontrack.html agent/views.py config/urls.py
git commit -m "refactor: rename course_copilot template/view/URL to ontrack"
```

---

### Task 4: Docs — `README.md` and `CLAUDE.md`

**Files:**
- Modify: `README.md:1` (title)
- Modify: `CLAUDE.md:1` (title), `CLAUDE.md`'s `## What this project is` paragraph

**Interfaces:**
- Consumes: nothing.
- Produces: nothing consumed by other tasks — this is the last content change before the final sweep in Task 5.

- [ ] **Step 1: Update `README.md`'s title**

Replace:

```markdown
# Course Copilot — Quickstart
```

with:

```markdown
# OnTrack — Quickstart

OnTrack keeps your semester organized. Cora — the Course Organization & Resource Assistant — answers grounded questions about your courses.
```

The rest of `README.md` (Architecture, Setup, Option A/B, Test syllabi, Test checklist sections) is unchanged — it documents real Django/DRF/ASGI mechanics, not branding.

- [ ] **Step 2: Update `CLAUDE.md`'s title**

Replace:

```markdown
# Course Copilot — Project Instructions
```

with:

```markdown
# OnTrack — Project Instructions
```

- [ ] **Step 3: Rewrite `CLAUDE.md`'s "What this project is" paragraph**

Replace:

```markdown
## What this project is
An AI agent scoped to the current semester's coursework, built on the Anthropic API. It answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.
```

with:

```markdown
## What this project is
OnTrack is an AI agent scoped to the current semester's coursework, built on the Anthropic API. Cora, its assistant persona, answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.
```

Every existing factual claim (Anthropic API, scoped to current semester's coursework, answers questions/tracks deadlines/generates quizzes, grounded in actual syllabi and notes) is preserved verbatim — only the naming is added. No other section of `CLAUDE.md` (Non-negotiable constraints, File structure, Schemas, Build order, Resolved/Open decisions) changes.

- [ ] **Step 4: Verify the factual claims survived**

Run: `grep -n "Anthropic API\|answers questions\|tracks deadlines\|generates quizzes\|syllabi and notes" CLAUDE.md`
Expected: one match, on the rewritten "What this project is" line, containing all five phrases.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: rebrand README and CLAUDE.md to OnTrack/Cora"
```

---

### Task 5: Final verification sweep

**Files:** none modified — this task only runs verification commands from the spec's Verification section across the whole repo.

**Interfaces:**
- Consumes: the completed state of Tasks 1-4.
- Produces: nothing — terminal task.

- [ ] **Step 1: Repo-wide grep for leftover old naming**

Run: `grep -rn "course_copilot\|Course Copilot" agent/ config/ README.md CLAUDE.md`
Expected: no output. (This intentionally excludes `docs/superpowers/`, whose historical dated documents are not rewritten per this plan's Global Constraints.)

- [ ] **Step 2: Django system check**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Full ask.py test suite**

Run: `pytest agent/tests/test_ask.py agent/tests/test_ask_grounding.py -v`
Expected: all `PASS` or `SKIPPED` (skipped if `ANTHROPIC_API_KEY` isn't set).

- [ ] **Step 4: Manual full checklist**

- Load `/`: browser tab reads "OnTrack"; sidebar logo reads "OnTrack" on every tab (Dashboard, Chat, Progress, Quiz).
- Open the Chat tab: input placeholder and empty-state text both name Cora; `chatGroundingText` renders "Cora only grounds answers in..." with the correct conditional notes/references clauses for a course with/without notes and references.
- If `ANTHROPIC_API_KEY` is set: ask `cs101` "who are you?" via the CLI (`python manage.py ask cs101 "who are you?"`) or the API — response is valid JSON, `answer` identifies itself as Cora and describes what it does, `grounded: false`, `sources: []`.

- [ ] **Step 5: No commit needed**

This task is verification-only; if Step 1's grep or Step 2's check surfaces anything, fix it in the relevant earlier task's files and re-commit there rather than here.

---

## Self-Review Notes

- **Spec coverage:** §1 (persona) → Task 1. §2 (chat UI copy, all 4 rows of the table + no-title case) → Task 2. §3 (all 3 internal renames) → Task 3. §4 (README.md + CLAUDE.md) → Task 4. Verification section's four checks → Tasks 1 Step 5, 2 Step 8, 3 Steps 4-5, 5 Steps 1-4. Out-of-scope items are called out in Global Constraints and nothing in the plan touches them (confirmed: `config/asgi.py`/`config/wsgi.py` docstrings use lowercase hyphenated "course-copilot", which doesn't match either grep pattern in Task 5 Step 1, and are correctly left untouched).
- **Placeholder scan:** no TBD/TODO markers; every step shows exact code or exact grep command with expected output.
- **Type consistency:** `ontrack_page(request)` name is consistent across Task 3's view definition and URL wiring; `ASK_SYSTEM_PROMPT` stays a module-level `str` with unchanged name across Task 1.
