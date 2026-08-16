# Expanding ask.py's grounding sources — design

## Context

`ask.py` currently grounds every answer in exactly two things for the single course being asked about: `syllabus.json` and that course's `notes/*.json`, both stuffed in full into the prompt (`ask.py:69-73`). The system prompt (`ASK_SYSTEM_PROMPT`, `ask.py:18-59`) forbids answering from anything else — CLAUDE.md's first non-negotiable constraint: "Never fabricate course content... don't answer from training data or general knowledge as if it's the course's content."

This pass adds two new, real (not fabricated) sources the agent can draw on when the syllabus/notes genuinely don't cover a question:

1. **User-uploaded reference material** per course (e.g. a textbook chapter) — still the user's own real material, just not lecture notes.
2. **Restricted web search** — real, fetched, cited web content, gated to a curated allowlist of trustworthy domains.

Both stay inside the "never fabricate" spirit: nothing is invented from parametric training data. What changes is the *set of real things* the agent is allowed to ground in.

## What changes and why

### 1. Reference docs (new source, no web involved)

**Schema** — `courses/<course_id>/references/<reference_id>.json`, new sibling to `notes/`:
```json
{
  "reference_id": "string",
  "title": "string",
  "source_filename": "string",
  "text": "string"
}
```
No `chunks`/`topics` — unlike notes, references aren't quizzed or mastery-tracked, so there's no need to chunk by topic. Per the "full-context stuffing" decision, the whole `text` gets stuffed into `ask.py`'s context every time, same as syllabus and notes already are. `reference_id` gets the same filesystem-safe validation as `lecture_id` (`storage.py`'s `LECTURE_ID_RE` pattern, reused as `REFERENCE_ID_RE`).

**No LLM call needed for ingestion** — unlike `chunk_notes.py` (which needs the LLM to semantically chunk notes by topic) or `syllabus_extraction.py` (which needs the LLM to extract structured fields), a reference doc just needs its raw text extracted and stored whole. `agent/services/references.py` (new): `ingest_reference(course_id, file_bytes, filename, title=None) -> dict` — extracts text via `pypdf` for `.pdf` or a plain read for `.txt`/`.md`, then calls new `storage.write_reference()`. Same CLI + API pattern as everything else: `management/commands/references.py` wraps the same function; `ReferencesView` (`POST` multipart upload, `GET` to list) in `views.py`, routed at `courses/<id>/references/`.

**`storage.py` additions** (mirroring the existing `notes` functions exactly): `validate_reference()`, `read_references(course_id) -> list` (all references, `[]` if none — normal state), `write_reference(course_id, reference_id, data, overwrite=False)`.

### 2. Restricted web search (new source, real API tool)

**The constraint that shaped this:** Anthropic's `web_search` tool's `allowed_domains` parameter takes only literal domains — `*.edu` and `*.gov` are explicitly rejected as invalid ("Wildcards are not allowed in the domain itself"). There is no way to say "any `.edu` site" to the API. The only real enforcement available is a literal, maintained list of specific domains.

**The list is per-course and LLM-suggested, not a hardcoded global constant.** A single static list (e.g. `docs.python.org`, `nih.gov`) is CS101/PSYC201-shaped and gives a Chemistry or History course nothing relevant — it wouldn't scale to a course added later. Instead, domain suggestions are generated per course from that course's own `syllabus.json` (`course_name` + `topics`, already extracted), and a human confirms them before they're ever used for search — same plan-then-pause spirit CLAUDE.md already applies to syllabus overwrites, applied here because an LLM-suggested domain string could be wrong or non-existent and this is the one thing in this pass that gates what the agent is allowed to fetch from.

**New schema** — `courses/<course_id>/trusted_domains.json`:
```json
{
  "course_id": "string",
  "domains": ["string", ...]
}
```
Absent entirely (not an empty file) until the user approves at least one domain — same "doesn't exist yet = normal state" convention as `mastery_scores.json` before any quiz attempt.

**New service** `agent/services/domain_suggestions.py`:
```python
async def suggest_domains(course_id: str) -> list[str]:
    """LLM call: reads this course's syllabus (course_name + topics) and proposes
    a short list of real, authoritative domains for it — official documentation,
    .gov, .edu, reputable .org. Read-only; nothing is written or trusted yet."""
```
The prompt explicitly excludes Wikipedia (openly-editable, not treated as authoritative here — carried over from the earlier decision) and instructs the model to prefer institutional/official domains over general commercial ones. This is a suggestion only — the model can get a domain wrong or invent one that doesn't resolve; nothing from this call is used for search until a human approves it via the step below. Same CLI + API pattern as the rest of the project: `management/commands/domains.py` (`--suggest` prints candidates, `--approve domain1,domain2,...` writes the approved list), and two views — `DomainSuggestionsView` (`POST /api/courses/<id>/domains/suggest/`, read-only, returns `{"suggested": [...]}`) and `DomainsView` (`GET /api/courses/<id>/domains/` to read the current approved list, `PUT` to replace it with the user's — possibly hand-edited — selection).

**`storage.py` additions**: `validate_trusted_domains()`, `read_trusted_domains(course_id) -> list` (`[]` if not yet approved), `write_trusted_domains(course_id, domains: list[str])` (always overwrites — this is a user-controlled config list, not append-only data, so there's no destructive-conflict case to guard the way `write_syllabus`/`write_notes` do).

**`ask_async` changes** (`ask.py`):
- Before building `tools`, read this course's approved domains: `approved = await sync_to_async(storage.read_trusted_domains)(course_id)`.
- If `approved` is non-empty, add `web_search_20250305` (basic version — ZDR-eligible, no code-execution dependency this single-user project doesn't need) to `tools`, with `allowed_domains=approved`. **If `approved` is empty, don't add the web_search tool at all** — no domains approved yet means the agent stays scoped to course material only, same as it does today, rather than either failing or (worse) searching unrestricted.
- **System prompt update** (`ASK_SYSTEM_PROMPT`): add a second grounding tier, ordered explicitly —
  1. Answer from `SYLLABUS`/`NOTES`/`REFERENCES` first, always.
  2. Only if those genuinely don't cover the question, you may search the web — restricted to the domains you've been given access to.
  3. Every externally-sourced claim must be cited with its real URL, and the answer must make clear which parts (if any) came from outside the course material — never blend web content into an answer as if it were the course's own material.
- **`grounded` field redefined**: `true` when the answer traces to course material (syllabus/notes/references) **or** a real, cited, allowed-domain web result; `false` only when neither exists. This preserves the actual invariant CLAUDE.md cares about (nothing fabricated), while no longer being "only true if from this course's own files."
- **`sources` stays a flat `list[str]`** — no schema version bump. Entries are one of: `"syllabus"`, a lecture_id, a reference_id, or a full external URL. Consumers (the frontend, storage) can already tell them apart trivially (`starts with "http"` vs. not) without a new field.

**CLAUDE.md updates**: the first non-negotiable constraint gets rewritten to describe the expanded-but-still-bounded rule (real course material, real uploaded references, or real cited results from a domain the user has explicitly approved for that course — never invented, never blended in unlabeled, never searched unrestricted). The file-structure listing gains `references.py` and `domain_suggestions.py` (services + CLI commands) and `references/` + `trusted_domains.json` under each course directory, and new **Schemas** entries for both.

### 3. Frontend (`course_copilot.html`)

Minimal, since `sourcesText` already renders the `sources` array per assistant message (from the 2026-08-16 chat-session pass). Only change: when a source string looks like a URL (`starts with "http"`), render it as an actual link instead of plain text, so external citations are clickable. Internal sources (`"syllabus"`, lecture/reference IDs) keep rendering as plain text.

## Explicitly out of scope for this pass

- **Rich response rendering** (equations, diagrams, images, charts in chat) — the other half of the original ask, deliberately sequenced second and not touched here.
- **A Dashboard/Chat UI for reviewing and approving suggested domains.** The suggest/approve flow in this pass is CLI + API only (matching every other extraction step in this project at first ship); a frontend review screen is a natural follow-up but not required to make the feature work.
- **Re-suggesting domains automatically when a syllabus is re-extracted/overwritten.** `suggest_domains()` can always be re-run manually; this pass doesn't wire it to fire automatically on syllabus changes.
- **Multi-turn interaction with the web-search tool's own `tool_use`/`tool_result` loop.** `web_search_20250305` is a *server-side* tool — the API runs it internally and returns results in the same response (per `SKILL.md`'s Server Tools reference), so this doesn't add a client-side tool loop to `ask_async`. If a search runs long, `pause_turn` handling may be needed — flagged for the plan to verify, not designed away here.
- **Session replay of `web_search_tool_result` blocks.** Multi-turn sessions (`sessions.py`) currently replay only the JSON-envelope answer text (per the earlier ask.py fix). Whether raw search-result blocks need replaying for citation integrity across turns is a question for implementation to check against the live API behavior, not resolved here.

## Verification

- `python manage.py check` after new views/urls.
- `pytest` — new tests for `storage.validate_reference()`/`read_references()`/`write_reference()`, `references.ingest_reference()` (PDF and txt extraction), `storage.validate_trusted_domains()`/`read_trusted_domains()`/`write_trusted_domains()`, and the new views' happy-path/error responses (including `DomainSuggestionsView` never writing anything on its own).
- Live-API test (skipped without `ANTHROPIC_API_KEY`, matching `test_ask.py`'s existing pattern): `suggest_domains()` on cs101 returns plausible real domains and never includes wikipedia.org; a question genuinely outside cs101's notes/syllabus but inside an approved domain's coverage comes back `grounded: true` with a real cited URL from the approved list; the same question with zero approved domains for the course comes back `grounded: false` rather than searching unrestricted or fabricating.
- Manual check: upload a reference doc, ask a question only that reference answers, confirm the answer cites the reference (not "syllabus" or a lecture_id).
- Manual check: run `suggest_domains` against a course whose subject differs sharply from CS101/PSYC201 (or hand-craft a syllabus for one) and confirm the suggestions are actually relevant to that subject, not leftover CS/psych-flavored domains.
