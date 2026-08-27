# OnTrack — Project Instructions

## What this project is
OnTrack is an AI agent scoped to the current semester's coursework, built on the Anthropic API. Cora, its assistant persona, answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.

## Stack
- Anthropic API (Messages endpoint), Python
- Sonnet for extraction/quiz/chat; reserve Opus for rubric critique if reasoning quality matters more than cost
- Structured JSON per course as the knowledge store for extracted/generated content (syllabus, notes, references, quiz_history) — no vector DB
- Django + DRF, served over **ASGI** (uvicorn), not WSGI — the agent makes per-request calls to the Anthropic API, which are I/O-bound; async views (`adrf`) + `AsyncAnthropic` keep the event loop free instead of blocking a worker thread per call
- Django's `db.sqlite3` holds auth/session/admin tables plus mutable per-user state that benefits from relational queries/constraints (flashcard progress, grades, quiz attempts, mastery scores, calendar sync records, custom events, notifications, sessions, saved sites) and `CourseMaterial` operational upload metadata. Extracted/generated *content* itself (syllabus, notes, references) still lives in per-course JSON, never the DB; `CourseMaterial.extracted_data` is only a temporary unconfirmed syllabus review candidate.
- Course content is user-scoped on disk: `courses/<user.pk>/<course_id>/...`, not a shared `courses/<course_id>/` — two students can each have their own `cs101` without colliding. The 9 CLI dev-tool commands (never used by real students) resolve a single designated owner account via the `CLI_OWNER_EMAIL` env var (see `agent/services/cli_owner.py`) instead of taking a `--user` flag. Pre-existing flat-layout course data needs a one-time `python manage.py migrate_course_ownership --apply` to move it under an owner's `<user.pk>/`.
- Google Calendar API for deadline sync is optional and uses a separate `GoogleCalendarConnection`; identity sign-in never requests Calendar access
- Private mutable-state ownership is non-null. Migrations abort rather than guessing ownership when unexpected anonymous rows exist.

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
                            # GoogleAccount/GoogleCalendarConnection/UserSettings plus mutable per-user
                            # state models (FlashcardProgress — now also carrying spaced-repetition
                            # scheduling fields: suspended/last_reviewed/next_review/rating/interval_days/
                            # review_count — GradeItem, CalendarSyncRecord, CourseMaterial, CustomEvent,
                            # Notification, SavedSite, QuizAttempt, MasteryScore — now also carrying a
                            # "reason" string alongside status — CourseSession/SessionMessage,
                            # StudySession/StudyActivity, RecommendationDismissal, ExamPlan) — never
                            # extracted/generated content, which stays in per-course JSON (see Schemas below)
    auth_views.py           # Google Sign-In: login redirect, OAuth callback, logout — plain
                            # Django views (browser-redirect flow), not DRF
    page_views.py           # authenticated browser-page rendering; no API/business logic
    page_urls.py            # named browser routes mounted separately from /api/
    authentication.py       # DRF authentication class controlling 401-vs-403 on an
                            # unauthenticated request
    serializers.py          # DRF request serializers for views.py's APIViews
    services/
      client.py              # shared AsyncAnthropic init + MODEL constants — every
                              # API-calling service imports from here, not anthropic directly
      storage.py            # JSON schema validation + read/write (courses/*.json)
      material_files.py     # bounded upload validation + private object-storage adapter
      materials.py          # owned upload/status/review lifecycle shared by API and CLI
      syllabus_extraction.py # syllabus text/pdf -> syllabus.json
      chunk_notes.py         # notes (pdf/txt/md) or slides (.pptx) -> notes/<lecture_id>.json
      references.py          # reference doc (pdf/txt/md) -> references/<reference_id>.json, no LLM call
      ask.py                    # grounded Q&A, stateless or multi-turn via session_id
      domain_suggestions.py     # LLM-suggested trusted domains for a course's restricted web search, read-only
      sessions.py               # SQLite-backed owned conversation CRUD + retry idempotency
      citations.py              # resolves model labels to owned, inspectable structured sources
      quiz.py                  # question generation from chunks + quiz_history.json logging;
                               # record_attempt validates lecture_id/chunk_id actually belong to
                               # this user's course before logging, so a submission can't forge
                               # quiz/mastery history against another course's or user's chunk
      mastery.py                # mastery v2: quiz-only EWMA score is unchanged from v1 (still what
                               # quiz.py's chunk-picking weight reads), but status now expands to
                               # not_started/learning/needs_review/proficient/at_risk/exam_ready —
                               # blending in a flashcard-rating signal when quiz data is thin/absent,
                               # plus recency and attempt count — with a human-readable "reason" per
                               # topic built from those same facts
      recommendations.py        # deterministic (no LLM) "what to study next" ranking: mastery gap +
                               # deadline urgency + assessment importance (grading-component match,
                               # else a type-tier guess) + recency, all from constants documented in
                               # the module; dismiss/defer never touches the underlying academic data
                               # it's computed from, only a RecommendationDismissal row
      spaced_repetition.py      # deterministic again/hard/good/easy -> interval-days scheduler
                               # (algorithm v1) — a pure function, no DB access; storage.py's
                               # review_flashcard() is what actually applies its result to a
                               # FlashcardProgress row
      exams.py                  # exam workspace: ExamPlan holds only mutable plan state
                               # (included topics/materials, generated study guide) layered over
                               # one confirmed test_quiz-type calendar event, which is always
                               # re-resolved live by event_id from calendar_events.py — never
                               # cached, so a deleted/rescheduled event just stops resolving
                               # instead of leaving a stale plan visible. Study guide generation
                               # reads ONLY the plan's included topics/materials and resolves each
                               # section's citation through citations.py; practice questions reuse
                               # quiz.py's existing generate/record endpoints (topic-scoped),
                               # deliberately not a competing question store
      study_sessions.py         # guided StudySession/StudyActivity lifecycle: start, append an
                               # activity, complete (returns a summary), list history, and
                               # session_detail for reviewing one later — all owner-scoped
      reminders.py               # read-only deadline digest across all courses, no writes
      calendar_events.py          # canonical user-scoped read model combining confirmed
                                  # syllabus, manual, and study-plan calendar events
      grades.py                  # grade calculation engine: current_grade, add/update/delete item
                                 # CRUD, grade_needed (what-if solver), missable_by_category,
                                 # all_courses_summary, find_orphaned_components
      calendar_sync.py           # pushes syllabus deadlines to the signed-in user's real
                                 # Google Calendar, one event at a time
      custom_events.py           # manual/study-plan deadlines/events (course-specific or
                                 # general, course_id: null) — full CRUD + Calendar sync,
                                 # reusing calendar_sync.py's credentials
      dashboard.py                # cross-course Dashboard-tab summary — composition only, no
                                 # new storage format. Also composes next_deadline/next_exam
                                 # (soonest in the windowed deadlines list), today_plan (deadlines
                                 # with a real estimated_effort_minutes, backfilled with top
                                 # recommendations.rank_recommendations() results for
                                 # not-yet-covered courses — "marking done" always acts on the
                                 # underlying deadline/recommendation directly, never a second
                                 # write path), and each course's mastery_pct (average of its
                                 # syllabus topics' scores, unstarted counted as 0 — never skipped)
      streak.py                   # cross-course study streak (consecutive UTC days with a quiz
                                 # attempt) — read-only. week_activity() is the same union of
                                 # attempt-dates reshaped into the current Mon-Sun week for the
                                 # dashboard's 7-dot strip
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
      app_base.html           # shared application shell
      partials/               # sidebar, topbar, course selector, states, overlays, runtime adapter
      pages/                  # extracted DC markup for remaining DC-driven product areas
                              # (Progress/Flashcards/Quiz/Grades tabs under study.html; Cora
                              # chat under cora.html) — dashboard_content.html was retired when
                              # dashboard.html moved fully to the vanilla-JS pattern below
      dashboard.html          # URL-addressable browser pages extend app_base.html. Plain HTML +
                              # dashboard.js (like materials.html/study.html's guided-session
                              # panel/exams/detail.html) — no DC bindings on this page at all
      calendar.html
      cora.html
      study.html
      settings.html
      courses/                # course list/workspace/material pages
      exams/                  # exam workspace (plain HTML + exams.js, see services/exams.py)
      ontrack.html            # tiny compatibility template; no longer the application shell
    static/agent/
      support.js               # generated DC runtime; do not hand-edit
      css/app.css              # application-owned shell and extracted page styles. Also defines
                               # --color-cora* custom properties (a violet distinct from the
                               # app's orange/olive --color-accent*/--color-accent-2*, which live
                               # in the generated _ds bundle) for Cora-branded surfaces — the
                               # dashboard's recommendation card and quick-ask panel, so far
      js/core/                 # API, CSRF, navigation, modal, toast, and DC controller bridge
      js/*.js                  # page-owned entry modules; each page loads only its entry point
      _ds/                     # generated "Organic" design system (CSS + component bundle)
      images/                  # logo assets (full logo + cropped icon-only mark for
                               # favicon/sidebar use at small sizes)
  courses/
    <user.pk>/            # every piece of course content is user-scoped — two students
                          # can each have their own "cs101" without colliding or seeing
                          # each other's data (integer primary key, not username/email —
                          # stable, no path-unsafe characters)
      <course_id>/
        course.json         # user-managed catalog metadata (stable id/name/code/semester/
                            # instructor/color/archive state); archive preserves all course data
        uploads/             # randomized private originals; never trusted context directly
        syllabus.json       # extracted dates, topics, grading breakdown
        notes/
          <lecture_id>.json # chunked notes/slides, one file per lecture — see schema below
        references/
          <reference_id>.json # uploaded reference material, one file per doc — see schema below
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
  test-course-data/       # non-runtime course fixtures; never loaded as a user's live data
  CLAUDE.md               # this file
```

Browser pages are URL-addressable and remain separate from the JSON API:
`/dashboard/`, `/calendar/`, `/courses/`, `/courses/<course_id>/`,
`/courses/<course_id>/materials/`, `/courses/<course_id>/study/`,
`/courses/<course_id>/mastery/`, `/cora/`, `/study/`,
`/courses/<course_id>/exams/<exam_id>/`, and `/settings/`. Authenticated `/`
redirects to `/dashboard/`; anonymous page requests use the Google login flow.
`/study/?course=&topic=` and `/cora/?q=` prefill (never auto-submit) the guided-session
setup and the Cora chat input respectively — `window.ONTRACK_INITIAL_TOPIC`/
`_QUESTION`, both `|escapejs`-embedded free text capped at 255/500 chars server-side
in `page_views.py`. The dashboard's recommendation card and "Today's plan" both link
into the first; its Cora quick-entry box links into the second.

The course workspace has Overview, Materials, Study, Mastery, and Grades tabs.
`/courses/<course_id>/schedule/` is compatibility-only and redirects, after an
ownership check, to `/calendar/?course=<course_id>`; the global Calendar is the
only full calendar UI. Course Study composes confirmed syllabus topics, existing
spaced-repetition, quiz, recommendation, and StudySession APIs. Course Mastery
renders the existing rebuildable mastery rows and explicitly withholds a trend
when no replayable history supports one.

The authenticated Courses page is composed by `GET /api/courses/overview/`
with optional `semester=<season>-<year>` and `archived=1` filters. It reads
only the signed-in owner's course tree and returns saved metadata, confirmed
future deadlines in the selected term, ready-material counts, and
evidence-backed mastery. Missing mastery is reported as not enough data rather
than zero. `PATCH /api/courses/<course_id>/archive/` preserves the complete
course directory while excluding an archived course from active Dashboard,
Calendar, and reminder composition. A semester move requires
`confirm_semester_move: true`; the stable course ID and storage directory are
not renamed. Nested browser workspaces return the same `404` for missing and
foreign-owned courses.

Material uploads use a DB-backed operational lifecycle with statuses
`uploaded`, `processing`, `needs_review`, `ready`, and `failed`. List and
detail/polling endpoints are owner-scoped. Syllabus extraction stops at
`needs_review`; only `POST /api/courses/<course_id>/materials/<material_id>/confirm/`
may replace validated `syllabus.json`, and it requires an edited candidate
whose `course_id` matches the URL plus `confirm: true`. Previous confirmed
content remains active through upload, processing, review, and any failure.

Each script/service in the original build order becomes both a management
command (CLI) and a service function called by an async DRF view (API) —
same pattern as `extract_syllabus`. No logic duplicated between the two.

## Schemas (v1)

**syllabus.json**
```json
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "hw|project|test_quiz|class|other"}],
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

**CourseSession / SessionMessage (SQLite; API representation)**
```json
{
  "session_id": "string",
  "course_id": "string",
  "title": "string",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "messages": [
    {
      "role": "user|assistant",
      "content": "string",
      "timestamp": "ISO8601",
      "sources": [
        {
          "material_id": "string",
          "material_type": "syllabus|notes|slides|reference|web",
          "title": "string",
          "lecture_id": "string|null",
          "chunk_id": "string|null",
          "page": "integer|null",
          "url": "string|null",
          "excerpt": "string (maximum 360 characters)"
        }
      ],
      "grounded": true
    }
  ]
}
```

"sources" and "grounded" only apply to assistant messages (mirrors ask.py's response
shape) — omit them for user messages rather than leaving them null/empty. Existing
assistant rows containing legacy string source labels remain readable and render as
plain labels/links. New grounded answers resolve model labels on the server to sources
owned by that user and course before the exchange is atomically persisted. Ungrounded
answers always persist `sources: []`. A client-generated UUID makes retrying an exchange
idempotent, so the same user message is not appended twice.

Source previews are re-resolved by `POST /api/courses/<course_id>/sources/preview/`;
the request identifies the owned session, assistant-message index, and citation
index, and the server previews the stored citation rather than trusting source
metadata supplied by the browser.
The server ignores client-supplied titles/excerpts and returns `404` unless the material,
chunk, saved URL, or internal course record belongs to the signed-in user. Web sources
are always typed `web` and must still match a saved site or approved domain.

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

**CustomEvent database rows** — user-owned manual or study-plan deadlines, full CRUD. The
calendar read model combines these rows with confirmed `syllabus.json` dates; pending
`CourseMaterial.extracted_data` review candidates never appear as calendar events.
```json
{
  "id": "string",
  "course_id": "string|null",
  "date": "YYYY-MM-DD",
  "time": "HH:MM|null",
  "end_time": "HH:MM|null",
  "title": "string",
  "type": "hw|project|test_quiz|class|other",
  "location": "string",
  "notes": "string",
  "source": "manual|study_plan",
  "estimated_effort_minutes": "positive integer|null",
  "source_material_id": "owned ready material UUID|null",
  "replaces_syllabus_key": "string|null",
  "completed": false,
  "synced": false,
  "google_event_id": "string|null",
  "synced_at": "ISO8601|null",
  "created_at": "ISO8601"
}
```

`course_id: null` means general. `source_material_id`, when present, must resolve to a ready
material owned by the same user and course. Syllabus event IDs are deterministic per user and
replacement key; converting a read-only syllabus date into an editable manual override keeps
the same event ID. `GET /api/calendar/` returns the full owner-scoped calendar snapshot:
canonical events, course names/colors, server-defined filter groups, and non-fatal per-course
warnings. Canonical API rows also include `start_time`, `all_day`, `course_name`,
`course_color`, `confirmed`, and `extraction_state`; only confirmed/live rows are returned.

Cora receives the client-side `propose_calendar_changes` tool only for calendar-intent
messages. The tool is side-effect free: its bounded, structured create/update/delete actions
are stored and rendered as pending proposals. Calendar writes occur only through the
authenticated per-session confirmation endpoint after explicit user confirmation. That
endpoint treats model output as untrusted and re-resolves update/delete event IDs against the
signed-in user's current owned calendar before mutating anything.

**calendar_sync.json** — per-course, tracks which syllabus-derived deadlines have been
pushed to Google Calendar (manual/study-plan events track their own sync state inline on the
database row).
```json
{
  "course_id": "string",
  "synced": [
    {"date": "YYYY-MM-DD", "title": "string", "type": "string", "google_event_id": "string", "synced_at": "ISO8601"}
  ]
}
```

Keyed by `(date, title)` per entry. Absent until the first deadline in that course is synced.

**StudySession / StudyActivity database rows** — a guided study session (`/study/?view=session`,
`POST /api/courses/<id>/study/sessions/`) and its append-only activity stream, both owner-scoped.
```json
{
  "session_id": "uuid",
  "course_id": "string",
  "topic": "string",
  "duration_minutes": "integer|null",
  "mode": "mixed|flashcards|quiz",
  "status": "in_progress|completed|abandoned",
  "state": {},
  "started_at": "ISO8601",
  "completed_at": "ISO8601|null",
  "activities": [
    {"kind": "session_started|flashcard_reviewed|quiz_answered|session_completed", "payload": {}, "position": 0, "created_at": "ISO8601"}
  ]
}
```
`activities` is never edited in place — `study_sessions.record_activity()` only appends, at the
next `position`. `complete_session()` computes its summary (`flashcards_reviewed`,
`questions_answered`, `questions_correct`) from the activity stream itself, then appends a final
`session_completed` activity carrying that same summary, so a later `GET .../sessions/<id>/` call
can replay exactly what happened without recomputing anything.

`state` is private operational resume state for page-owned interactive modes. The generic
session-detail API never serializes it. `interactive_study.py` is the only public boundary for
`practice_attempt` and `flashcard_deck` state: active practice responses omit answer keys and
explanations until finalization, and flashcard responses omit definitions until an explicit
reveal. Practice finalization grades against the stored server key, appends the normal
`QuizAttempt` records, rebuilds mastery, and rejects a second finalization with `409`. Flashcard
ratings use the stored card key and are idempotent within a session, so retrying a rating cannot
advance the spaced-repetition interval twice.

Flashcard spaced repetition (algorithm v1, `services/spaced_repetition.py`) is a fixed
`again|hard|good|easy` -> interval-days ladder, not full SM-2 — deliberately simple and
explainable over adaptive. `POST /api/courses/<id>/flashcards/review/` applies it to a
`FlashcardProgress` row's `interval_days`/`next_review`/`review_count`; reviewing a `suspended`
card is rejected (409), not silently reactivated. `GET .../flashcards/due/` returns cards with
`next_review` unset or in the past, excluding suspended ones.

**Recommendation candidates (API representation, `GET /api/recommendations/`)** — one per
syllabus topic that isn't exam-ready or dismissed/deferred, ranked highest-priority first.
Nothing here is persisted; `recommendations.rank_recommendations()` recomputes the full list on
every call from mastery/deadline/syllabus data that already exists elsewhere.
```json
{
  "course_id": "string",
  "topic": "string",
  "status": "not_started|learning|needs_review|proficient|at_risk|exam_ready",
  "mastery_score": "number|null",
  "gap": 0.0, "urgency": 0.0, "importance": 0.0, "recency": 0.0,
  "rank_score": 0.0,
  "nearest_deadline": {"title": "string", "date": "YYYY-MM-DD"} | null,
  "grading_component": "string|null",
  "reason": "string",
  "suggested_mode": "mixed|flashcards"
}
```
`rank_score = 0.35*gap + 0.25*urgency + 0.15*importance + 0.25*recency` (weights/horizons are
named constants in `recommendations.py`, not magic numbers). `POST /api/recommendations/dismiss/`
(`{"course_id", "topic", "defer_hours": int|null}`) writes only a `RecommendationDismissal` row —
dismissing/deferring can never lose quiz, flashcard, or deadline data, since the recommendation
itself is never stored.

**Exam workspace (API representation, `GET /api/courses/<course_id>/exams/<event_id>/`)** —
`event_id` is a confirmed test_quiz-type event's canonical id from `calendar_events.py`
(`/courses/<course_id>/exams/<event_id>/` in the browser). 404s if that id no longer resolves to
a live, owned, test_quiz event — the same response whether it was deleted, rescheduled (a
syllabus-sourced event's id is a hash of date+title+type, so rescheduling gives it a new id), or
never belonged to this user.
```json
{
  "event": {"id": "string", "title": "string", "date": "YYYY-MM-DD", "course_id": "string"},
  "days_until": 0,
  "plan": {
    "included_topics": ["string"], "included_material_ids": ["uuid"],
    "study_guide": {"sections": [{"topic": "string", "key_points": ["string"], "citation": {"...": "..."} }], "reference_citations": [], "generated_at": "ISO8601"} | null
  },
  "topics": [{"topic": "string", "included": true, "status": "not_started|...", "score": 0.0, "reason": "string"}],
  "weak_topics": [],
  "materials": [{"material_id": "uuid", "original_filename": "string", "material_type": "string", "included": true}]
}
```

The workspace also returns deterministic `readiness`, `recommendation`, and
`preparation` summaries. Readiness weights are named constants in
`agent/services/exams.py` (70% topic mastery, 15% evidence coverage, 15% recent
completed study sessions); preparation blocks use the owner's persisted session
length and never create calendar events automatically.
`PATCH .../plan/` (`{"included_topics": [...]|null, "included_material_ids": [...]|null}`) confirms
scope; anything not actually owned/valid is silently dropped rather than rejected. `POST
.../study-guide/` regenerates the guide from ONLY the plan's current selection — 422 if nothing
usable is selected — and saves it onto the plan. The exam page creates or resumes an owner-scoped
practice attempt through `/api/courses/<course_id>/study/quizzes/<event_id>/attempts/`, then opens
the direct browser route
`/courses/<course_id>/study/quizzes/<event_id>/attempts/<attempt_id>/`. Questions are generated
from the plan's confirmed topics and stored as private `StudySession.state`; answer keys are never
accepted from the browser. The matching flashcard route is
`/courses/<course_id>/study/flashcards/<deck_id>/`.

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
