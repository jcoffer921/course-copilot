# OnTrack — Project Instructions

## What this project is
OnTrack is an AI agent scoped to the current semester's coursework, built on the Anthropic API. Cora, its assistant persona, answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.

## Stack
- Anthropic API (Messages endpoint), Python
- Sonnet for extraction/quiz/chat; reserve Opus for rubric critique if reasoning quality matters more than cost
- Structured JSON per course as the knowledge store (no vector DB in v1, no relational DB either — flat files, single user)
- Django + DRF, served over **ASGI** (uvicorn), not WSGI — the agent makes per-request calls to the Anthropic API, which are I/O-bound; async views (`adrf`) + `AsyncAnthropic` keep the event loop free instead of blocking a worker thread per call
- Django's own `db.sqlite3` is used ONLY for its built-in auth/session/admin tables — never for course content
- Optional: Google Calendar API for deadline sync (later phase, not v1)

## Non-negotiable constraints
- Never fabricate course content. Ground every answer in real material only: this course's syllabus/notes, a user-uploaded reference document, or — only when that material genuinely doesn't cover the question, and only from a domain the user has explicitly approved for this course — real, cited web content. Never invent facts, never blend web content into an answer as if it were the course's own material, and never search the web outside an approved domain list.
- Rubric critique mode never writes the assignment for the user. Scaffold, question, and critique only.
- All extracted data (dates, topics, notes chunks) goes through a defined JSON schema — no free-text dumps into course files.
- Plan-then-pause: before any destructive or bulk write (overwriting a course's JSON, bulk re-parsing notes), pause and confirm.

## File structure
```
course-copilot/
  manage.py
  config/
    settings.py          # DEBUG/SECRET_KEY from env; sqlite for Django's own tables only
    urls.py               # mounts agent.urls under /api/
    asgi.py                # run THIS (uvicorn config.asgi:application), not wsgi.py
    wsgi.py                 # kept for tooling compat only — not how this project runs
  agent/                  # Django app: services + async DRF views + CLI commands
    services/
      client.py              # shared AsyncAnthropic init + MODEL constants — every
                              # API-calling service imports from here, not anthropic directly
      storage.py            # JSON schema validation + read/write (courses/*.json)
      syllabus_extraction.py # syllabus text/pdf -> syllabus.json
      chunk_notes.py         # notes (pdf/txt/md) or slides (.pptx) -> notes/<lecture_id>.json
      references.py          # reference doc (pdf/txt/md) -> references/<reference_id>.json, no LLM call
      ask.py                    # grounded Q&A, stateless or multi-turn via session_id
      domain_suggestions.py     # LLM-suggested trusted domains for a course's restricted web search, read-only
      sessions.py               # conversation session read/write (courses/*/sessions/*.json)
      quiz.py                  # question generation from chunks + quiz_history.json logging
      mastery.py                # EWMA topic scoring, rebuilds mastery_scores.json from quiz_history.json
      reminders.py               # read-only deadline digest across all courses, no writes
    views.py               # async DRF views (adrf.views.APIView)
    urls.py
    management/commands/
      extract_syllabus.py  # CLI wrapper — no server needed
      chunk_notes.py         # CLI wrapper, handles both notes files and .pptx decks
      references.py           # CLI wrapper around references.py
      ask.py                 # CLI wrapper around ask.py, optional --session
      domains.py               # CLI wrapper around domain_suggestions.py (--suggest / --approve)
      sessions.py             # CLI wrapper around sessions.py (--create/--list/--show)
      quiz.py                  # CLI wrapper — generates a question, prompts, records the attempt
      mastery.py                # CLI wrapper (--rebuild / --weak-topics)
      reminders.py                # CLI wrapper (--within-days / --course-id)
    tests/                  # pytest (pytest-django + pytest-asyncio); live-API tests skip
                            # cleanly without ANTHROPIC_API_KEY set
  courses/
    <course_id>/
      syllabus.json       # extracted dates, topics, grading breakdown
      notes/
        <lecture_id>.json # chunked notes/slides, one file per lecture — see schema below
      references/
        <reference_id>.json # uploaded reference material, one file per doc — see schema below
      sessions/
        <session_id>.json # multi-turn grounded Q&A conversation history
      quiz_history.json   # append-only event log: every attempt, questions asked, correct/incorrect
      mastery_scores.json # derived from quiz_history.json — never hand-edited, always rebuildable
      trusted_domains.json # human-approved web-search domains — absent until at least one is approved
  test-syllabi/           # sample syllabi for testing extraction
  test-notes/             # sample lecture notes + slide decks for testing chunk_notes
  CLAUDE.md               # this file
```

Each script/service in the original build order becomes both a management
command (CLI) and a service function called by an async DRF view (API) —
same pattern as `extract_syllabus`. No logic duplicated between the two.

## Schemas (v1)

**syllabus.json**
```json
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other"}],
  "grading": [{"component": "string", "weight_pct": 0}],
  "topics": ["string"]
}
```

**notes/<lecture_id>.json**
```json
{
  "lecture_id": "string",
  "source": "notes|slides",
  "date": "YYYY-MM-DD",
  "topics": ["string"],
  "chunks": [{"id": "string", "topic": "string", "text": "string"}]
}
```

"source" records whether this lecture came from raw notes (pdf/txt/md) or a slide
deck (.pptx) — chunk_notes.py runs the same LLM chunking core on both after
converting slides to text first (divider/title-only slides are collapsed into a
section-heading prefix on the next content slide, never their own chunk).

Each chunk's "topic" should reuse a string from syllabus.json's "topics" list
whenever the content genuinely matches one (verified in practice: cs101's chunked
notes and slides both landed on "Recursion" and "Sorting and searching algorithms"
verbatim) — this is what keeps mastery.py's topic scores meaningful across notes,
slides, and quizzes instead of drifting into unrelated topic vocabulary per source.
The lecture-level "topics" array is the deduplicated set of topics used across
its own "chunks".

**references/<reference_id>.json**
```json
{
  "reference_id": "string",
  "title": "string",
  "source_filename": "string",
  "text": "string"
}
```

No `chunks`/`topics` — unlike notes, references aren't quizzed or mastery-tracked, so there's no need
to chunk by topic. The whole `text` gets stuffed into ask.py's context every time, same as syllabus
and notes.

**trusted_domains.json**
```json
{
  "course_id": "string",
  "domains": ["string", ...]
}
```

Absent entirely (not an empty file) until the user approves at least one domain via
`manage.py domains <course_id> --approve ...` or `PUT /api/courses/<id>/domains/` — same
"doesn't exist yet = normal state" convention as mastery_scores.json before any quiz attempt.
`domain_suggestions.suggest_domains()` proposes candidates from the course's own syllabus, but never
writes this file itself.

**sessions/<session_id>.json**
```json
{
  "session_id": "string",
  "course_id": "string",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "messages": [
    {
      "role": "user|assistant",
      "content": "string",
      "timestamp": "ISO8601",
      "sources": ["string"],
      "grounded": true
    }
  ]
}
```

"sources" and "grounded" only apply to assistant messages (mirrors ask.py's response
shape) — omit them for user messages rather than leaving them null/empty.

**quiz_history.json** — append-only event log, one file per course, never edited in
place. mastery.py's only input; it always replays this from scratch rather than
trusting any incremental state.
```json
{
  "course_id": "string",
  "attempts": [
    {
      "lecture_id": "string",
      "chunk_id": "string",
      "topic": "string",
      "question": "string",
      "correct_answer": "string",
      "user_answer": "string",
      "correct": true,
      "timestamp": "ISO8601"
    }
  ]
}
```

**mastery_scores.json** — derived, disposable, rebuilt from quiz_history.json by
`mastery.rebuild_scores()` on every quiz attempt. Never hand-edited and never
itself a source of truth; safe to delete and regenerate at any time.
```json
{
  "course_id": "string",
  "rebuilt_at": "ISO8601",
  "scores": [
    {
      "topic": "string",
      "score": 0.0,
      "attempts": 0,
      "last_seen": "ISO8601",
      "status": "weak|developing|strong"
    }
  ]
}
```

"score" is an EWMA (alpha=0.3) over that topic's attempts in chronological order,
starting from a neutral 0.5. "status" thresholds: weak < 0.4 <= developing < 0.7 <=
strong. `weak_topics()` returns "scores" sorted weakest-first; quiz.py uses that
ordering to bias which topic (and one of its chunks) gets quizzed next.

## Build order (done, in this order)

1. `extract_syllabus.py` — test extraction reliability first; this was the highest-risk step
2. `client.py` — shared AsyncAnthropic init; extract_syllabus.py and ask.py both retrofitted to it
3. `chunk_notes.py` — notes (pdf/txt/md) and slide decks (.pptx) -> notes/<lecture_id>.json
4. `ask.py` — grounded Q&A, stateless or multi-turn via session_id
5. `quiz.py` + `mastery.py` — question generation/tracking, wired to an EWMA rebuild on every attempt
6. `reminders.py` — read-only deadline digest across all courses

**Deferred, not yet built:**

- Rubric critique mode
- Calendar sync (`calendar_sync.py`) — needs a user-provided Google Cloud OAuth
  client (credentials.json); blocked on that, not on anything else being unready.
  When built: dry-run by default, per-event explicit confirmation, never bulk-add
  a semester's dates in one call (that's what reminders.py is for browsing).

## Definition of "working" for each script
- Runs standalone from CLI with no manual context-pasting
- Fails loudly (no silent empty results) if the source file is missing or malformed
- Output validated against the JSON schema before writing to disk

## Resolved decisions

- Chunking granularity: by topic/subtopic within a lecture (semantically meaningful, not by
  character count or by lecture wholesale) — verified in practice on both a text-notes
  lecture and a slide deck.
- quiz_history.json does feed back into what gets quizzed next: mastery.py's weakest-first
  topic ordering biases quiz.py's chunk selection (verified: 3/3 picks favored the weaker
  topic once mastery data existed).

## Open decisions (revisit before scaling past one course)

- Retrieval/chunk-routing — still full-context stuffing (all of a course's notes/slides
  into every ask.py call). Only becomes necessary once a course's material is too large to
  fit in context; don't build it speculatively before that's actually true.
- Rubric critique mode's system prompt/behavior contract — deferred, not designed yet.
