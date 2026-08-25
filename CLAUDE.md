# OnTrack — Project Instructions

## What this project is
OnTrack is an AI agent scoped to the current semester's coursework, built on the Anthropic API. Cora, its assistant persona, answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.

## Stack
- Anthropic API (Messages endpoint), Python
- Sonnet for extraction/quiz/chat; reserve Opus for rubric critique if reasoning quality matters more than cost
- Structured JSON per course as the knowledge store for extracted/generated content (syllabus, notes, references, quiz_history) — no vector DB
- Django + DRF, served over **ASGI** (uvicorn), not WSGI — the agent makes per-request calls to the Anthropic API, which are I/O-bound; async views (`adrf`) + `AsyncAnthropic` keep the event loop free instead of blocking a worker thread per call
- Django's `db.sqlite3` holds auth/session/admin tables plus mutable per-user state that benefits from relational queries/constraints (flashcard progress, grades, quiz attempts, mastery scores, calendar sync records, custom events, notifications, sessions, saved sites) — extracted/generated *content* itself (syllabus, notes, references) still lives in per-course JSON, never the DB
- Course content is user-scoped on disk: `courses/<user.pk>/<course_id>/...`, not a shared `courses/<course_id>/` — two students can each have their own `cs101` without colliding. The 9 CLI dev-tool commands (never used by real students) resolve a single designated owner account via the `CLI_OWNER_EMAIL` env var (see `agent/services/cli_owner.py`) instead of taking a `--user` flag. Pre-existing flat-layout course data needs a one-time `python manage.py migrate_course_ownership --apply` to move it under an owner's `<user.pk>/`.
- Google Calendar API for deadline sync — built (`calendar_sync.py` + `custom_events.py`); requires a user-provided Google Cloud OAuth client

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
    models.py               # Django ORM, in db.sqlite3 alongside the built-in auth tables:
                            # GoogleAccount/UserSettings (account/auth) plus mutable per-user
                            # state models (FlashcardProgress, GradeItem, CalendarSyncRecord,
                            # CustomEvent, Notification, SavedSite, QuizAttempt, MasteryScore,
                            # CourseSession/SessionMessage) — never extracted/generated content,
                            # which stays in per-course JSON (see Schemas below)
    auth_views.py           # Google Sign-In: login redirect, OAuth callback, logout — plain
                            # Django views (browser-redirect flow), not DRF
    authentication.py       # DRF authentication class controlling 401-vs-403 on an
                            # unauthenticated request
    serializers.py          # DRF request serializers for views.py's APIViews
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
      grades.py                  # grade calculation engine: current_grade, add/update/delete item
                                 # CRUD, grade_needed (what-if solver), missable_by_category,
                                 # all_courses_summary, find_orphaned_components
      calendar_sync.py           # pushes syllabus deadlines to the signed-in user's real
                                 # Google Calendar, one event at a time
      custom_events.py           # manually-added deadlines/events (course-specific or
                                 # general, course_id: null) — full CRUD + Calendar sync,
                                 # reusing calendar_sync.py's credentials
      dashboard.py                # cross-course Dashboard-tab summary — composition only,
                                 # no new storage format
      streak.py                   # cross-course study streak (consecutive UTC days with a
                                 # quiz attempt) — read-only
      google_oauth.py              # Google Sign-In: email allow-list + OAuth 2.0
                                 # Authorization Code flow helpers
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
      grades.py                   # CLI wrapper (--add / --list / --whatif / --set-grading)
      migrate_course_ownership.py # one-time on-disk migration: courses/<course_id>/ ->
                                  # courses/<owner.pk>/<course_id>/ (run with --apply)
    tests/                  # pytest (pytest-django + pytest-asyncio); live-API tests skip
                            # cleanly without ANTHROPIC_API_KEY set
    templates/agent/
      login.html              # branded Google Sign-In page
      ontrack.html            # the entire app UI — single-page DC-component template
    static/agent/
      support.js               # shared JS runtime for ontrack.html
      _ds/                     # generated "Organic" design system (CSS + component bundle)
      images/                  # logo assets (full logo + cropped icon-only mark for
                               # favicon/sidebar use at small sizes)
  courses/
    custom_events.json    # top-level (not per-course) — manually-added deadlines/events;
                          # absent until the first custom event is created
    <user.pk>/            # every piece of course content is user-scoped — two students
                          # can each have their own "cs101" without colliding or seeing
                          # each other's data (integer primary key, not username/email —
                          # stable, no path-unsafe characters)
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
        grades.json         # entered scores (score/max_points) against syllabus.json's grading
                            # categories — user-editable CRUD, not an append-only log; absent
                            # until the first grade is added
        trusted_domains.json # human-approved web-search domains — absent until at least one is approved
        calendar_sync.json   # which of this course's syllabus deadlines have been pushed to
                            # Google Calendar — absent until the first sync
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
  "grading": [{"component": "string", "weight_pct": 0, "total_items": 0, "drop_lowest": 0}],
  "topics": ["string"],
  "grade_scale": {"passing_pct": 0, "cutoffs": [{"letter": "string", "min_pct": 0}]}
}
```

`total_items`, `drop_lowest` (per grading-category entry), and `grade_scale` (top-level) are all
optional — absent entirely means "use the default scale / no what-if projection for that
category," the same "absence is a normal state" convention `trusted_domains.json` documents below.

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

**grades.json** — entered scores against `syllabus.json`'s grading categories. Unlike
`quiz_history.json`, this is directly user-editable (add/edit/delete), not an append-only
log.
```json
{
  "course_id": "string",
  "items": [
    {
      "id": "string",
      "component": "string",
      "title": "string",
      "score": 0,
      "max_points": 0,
      "date": "YYYY-MM-DD"
    }
  ]
}
```

`component` must match a `component` string in that course's `syllabus.json` `grading`
array. `date` is optional. `score` may exceed `max_points` (extra credit).

**custom_events.json** — top-level, not per-course (a general event has no single course
to belong to). Manually-added deadlines, full CRUD.
```json
{
  "events": [
    {
      "id": "string", "course_id": "string|null", "date": "YYYY-MM-DD", "time": "HH:MM|null",
      "title": "string", "type": "exam|assignment|reading|other",
      "synced": false, "google_event_id": "string|null", "synced_at": "ISO8601|null",
      "created_at": "ISO8601"
    }
  ]
}
```

`course_id: null` means general — shows regardless of which course is selected, same as a
syllabus-derived date bypassing the course filter. Same type taxonomy as syllabus dates, no
new types. Absent entirely until the first custom event is created.

**calendar_sync.json** — per-course, tracks which syllabus-derived deadlines have been
pushed to Google Calendar (custom events track their own sync state inline instead, on
custom_events.json's own `synced`/`google_event_id`/`synced_at` fields).
```json
{
  "course_id": "string",
  "synced": [
    {"date": "YYYY-MM-DD", "title": "string", "type": "string", "google_event_id": "string", "synced_at": "ISO8601"}
  ]
}
```

Keyed by `(date, title)` per entry. Absent until the first deadline in that course is synced.

## Build order (done, in this order)

1. `extract_syllabus.py` — test extraction reliability first; this was the highest-risk step
2. `client.py` — shared AsyncAnthropic init; extract_syllabus.py and ask.py both retrofitted to it
3. `chunk_notes.py` — notes (pdf/txt/md) and slide decks (.pptx) -> notes/<lecture_id>.json
4. `ask.py` — grounded Q&A, stateless or multi-turn via session_id
5. `quiz.py` + `mastery.py` — question generation/tracking, wired to an EWMA rebuild on every attempt
6. `reminders.py` — read-only deadline digest across all courses
7. Google Sign-In (`auth_views.py`, `google_oauth.py`, `models.py`'s `GoogleAccount`) —
   the web UI's auth layer
8. `calendar_sync.py` — Calendar sync for syllabus deadlines, one event at a time
9. `custom_events.py` + the Deadlines tab — manually-added deadlines/events, full CRUD,
   merged with syllabus deadlines into one unbounded, cross-course list

**Deferred, not yet built:**

- Rubric critique mode
- Recurring class schedules ("CS101 meets Mon/Wed/Fri 10am") — a genuinely different
  data shape (a recurrence pattern, not a dated entry) than anything above, and needs
  its own Calendar sync approach (RRULE, not the one-off inserts calendar_sync.py and
  custom_events.py both use).

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
