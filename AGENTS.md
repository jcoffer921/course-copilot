# AGENTS.md

Instructions for AI coding agents working in this repo. Human contributors should read `README.md` (quickstart) and `CLAUDE.md` (full architecture, schemas, and build history) — this file is the condensed, agent-facing version of the same rules; when in doubt, `CLAUDE.md` is the source of truth.

## What this is

OnTrack: a Django + DRF app (served over **ASGI**/uvicorn, not WSGI) where an AI agent ("Cora") answers grounded questions, tracks deadlines, and generates quizzes from a student's own uploaded syllabi/notes. Course *content* (syllabus, notes, quiz history) lives in per-user JSON files under `courses/<user.pk>/<course_id>/`, never in the database. `db.sqlite3` holds only Django's own auth/session/admin tables plus mutable per-user state (grades, quiz attempts, calendar sync records, `UserSettings`, etc.) that benefits from relational queries.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in ANTHROPIC_API_KEY, GOOGLE_OAUTH_CLIENT_ID/SECRET, etc.
python manage.py migrate
```

## Running

```bash
./scripts/run_server.sh         # Git Bash / WSL / macOS / Linux
.\run_server.bat                # Windows
```

Always run the server via this script (it wraps uvicorn and kills any leftover instance first), **not** `python manage.py runserver` — the app is async (`adrf` + `AsyncAnthropic`) and runserver doesn't exercise that path.

## Testing — run this before calling anything done

```bash
venv/Scripts/python.exe -m pytest agent/tests/ -q      # Windows
venv/bin/python -m pytest agent/tests/ -q               # macOS/Linux
```

Also run after any model change:

```bash
python manage.py check
python manage.py migrate
```

Live-API tests skip cleanly without `ANTHROPIC_API_KEY` set. A handful of tests in `test_notifications.py`/`test_reminders.py`/`test_views.py` hardcode dates and can flake on the specific calendar day they collide with real wall-clock time — if a failure looks date-coincidental and unrelated to your change, verify it isn't yours before treating it as a regression.

## Non-negotiable rules

- **Tests before implementation.** Write the test, watch it fail for the right reason, then implement.
- **Fail loudly.** No silent empty results, no swallowing exceptions to "keep going" — especially around course data and the LLM usage cap.
- **No speculative abstraction.** Don't add a field, function, or config flag nothing reads yet. Don't build for a hypothetical future requirement.
- **Plan-then-pause** before any destructive or bulk write (overwriting a course's JSON, a data migration touching every row, bulk re-parsing). Outline the change and wait for approval before writing code, unless the user has explicitly told you to proceed without stopping.
- **Never fabricate course content.** Every answer must ground in real material (this course's syllabus/notes, an uploaded reference, or explicitly-approved web domains) — never invented facts, never web content blended in as if it were the course's own material.
- **One enforcement point per rule.** E.g. access control lives in `agent/authentication.py`'s `ActiveAccessPermission` (API) and `agent/middleware.py`'s `AccessStatusMiddleware` (pages) — if you find yourself writing the same conditional in two views, it belongs in a shared helper instead.
- **Commit only when asked**, and only after the full suite is green. Prefer new commits over `--amend`. Never force-push, skip hooks, or run destructive git commands without explicit instruction.
- Don't add comments explaining *what* code does (names should do that); only note non-obvious *why* (a workaround, an invariant, a past incident).

## Conventions specific to this repo

- Each script/service is both a management command (CLI, for dev use) **and** a service function called by an async DRF view (API) — no logic duplicated between the two. See `agent/services/*.py` + `agent/management/commands/*.py`.
- Course content is user-scoped on disk: `courses/<user.pk>/<course_id>/`, never a shared `courses/<course_id>/`.
- The 9 CLI dev-tool commands (never used by real students) resolve a single designated owner via `CLI_OWNER_EMAIL`, not a `--user` flag.
- Access control: `UserSettings.access_status` (`pending`/`active`/`suspended`) is the real gate — `ALLOWED_GOOGLE_EMAILS` is bootstrap-only (decides who starts `active` vs `pending`), not a sign-in gate. Tier-based entitlements resolve through `agent/services/entitlements.py`, never inlined per-view.
- Google Calendar access is optional and fully decoupled from sign-in (`GoogleCalendarConnection`, separate consent flow) — a broken/expired Calendar grant must never break an unrelated feature; it degrades to `calendar_connected: false` and a reconnect prompt.
- Browser pages (`/dashboard/`, `/calendar/`, `/courses/`, `/cora/`, `/study/`, `/settings/`, ...) are plain Django views + page-owned JS, separate from the JSON API under `/api/`.

## Where to look for more

`CLAUDE.md` has the full file structure map, all JSON schemas (syllabus, notes, quiz history, calendar events, etc.), the build order, and a running log of resolved/open design decisions. Read the relevant section there before touching a service you haven't worked in yet.
