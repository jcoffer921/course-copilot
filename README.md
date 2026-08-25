# OnTrack — Quickstart

OnTrack keeps your semester organized. Cora — the Course Organization & Resource Assistant — answers grounded questions about your courses.

## Architecture (updated)
Django + DRF, served over **ASGI** (uvicorn) rather than WSGI. The extraction
call to Claude is I/O-bound and can take a few seconds — on WSGI that blocks
an entire worker thread per request; on ASGI with `AsyncAnthropic`, the event
loop stays free to handle other requests while waiting on the API. Views use
[`adrf`](https://pypi.org/project/adrf/) (async support for DRF) so handler
methods can be `async def` directly.

Course data (`syllabus.json`, notes, quiz history) stays on **flat JSON
files** under `courses/<user.pk>/<course_id>/` — no database for course
content. Content is genuinely per-user: two students can each have their own
`cs101` without colliding or seeing each other's data, which is what makes
piloting OnTrack to a department of students possible. Django's own
`db.sqlite3` exists only for its built-in auth/session/admin tables (plus
mutable per-user state like grades and quiz history, already scoped by a
`user` FK) and is never used to store extracted/generated course content.

If you have pre-existing course data from before this per-user layout (a flat
`courses/<course_id>/` directory), run the one-time migration once you've
signed in at least once so your `User` row exists:
```bash
python manage.py migrate_course_ownership --apply
```

The 9 CLI dev-tool commands (`extract_syllabus`, `chunk_notes`, `ask`, etc.)
aren't used by real students — they operate as a single designated owner
account, resolved by email via `CLI_OWNER_EMAIL` (see Setup below), consistent
with the `ALLOWED_GOOGLE_EMAILS` email-based identity convention.

Both a CLI (`manage.py extract_syllabus`) and an HTTP API
(`POST /api/courses/<id>/syllabus/extract/`) are available — they call the
exact same extraction service in `agent/services/`, so there's no logic
duplicated between them.

## Setup
```bash
cd course-copilot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...    # Windows: set ANTHROPIC_API_KEY=sk-ant-...

# Google Sign-In — all three are required, the app is unusable without them
# (every page redirects to a login that raises if these are unset). Get the
# client ID/secret from a Google Cloud Console OAuth client.
export GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
export GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
# Comma-separated allow-list of Google account emails permitted to sign in.
# Fails closed by design: leaving this empty/unset blocks everyone — that's
# a deliberate security property, not a bug to work around.
export ALLOWED_GOOGLE_EMAILS=you@example.com,teammate@example.com

# Required only to run the 9 CLI dev-tool commands (extract_syllabus, ask,
# quiz, etc.) — they're dev/debug tools, never used by real students, and
# operate as this one designated owner account rather than taking a --user
# flag. Must match the email of a User who has signed in at least once.
export CLI_OWNER_EMAIL=you@example.com

python manage.py migrate        # sets up Django's own tables (sqlite) — one-time
```

## Option A: CLI (no server needed)
```bash
python manage.py extract_syllabus test-syllabi/cs101_clean.txt cs101 --course-name "Intro to CS"
```
Same validate-then-write behavior as before: fails loudly on bad input, won't
overwrite an existing `syllabus.json` without confirmation (`--force` to skip
the prompt).

## Option B: Run the API server
```bash
./scripts/run_server.sh       # Git Bash / WSL / macOS / Linux
.\run_server.bat              # Windows cmd.exe / PowerShell
```
Do **not** use `python manage.py runserver` for real use — it's fine for
quick checks but doesn't exercise the ASGI/async path the way uvicorn does.

Use the script instead of calling `uvicorn` directly — it kills any leftover
instance of this project's server first (matched specifically, so it won't
touch unrelated processes), so restarting during development doesn't fail
with "address already in use" or leave orphaned processes behind.

Then, from another terminal:
```bash
curl -X POST http://127.0.0.1:8000/api/courses/cs101/syllabus/extract/ \
  -F "file=@test-syllabi/cs101_clean.txt" \
  -F "course_name=Intro to CS"

curl http://127.0.0.1:8000/api/courses/cs101/syllabus/
```

If `syllabus.json` already exists for that course, the extract endpoint
returns `409 Conflict` with a preview of the existing data instead of
overwriting — resend with `-F "overwrite=true"` to replace it.

## Test syllabi
`test-syllabi/cs101_clean.txt` — well-structured, should extract cleanly.
`test-syllabi/psyc201_messy.txt` — deliberately messy (vague weights, no
explicit year, dates only spelled out for some rows in a table). Good for
checking that extraction *omits* what it can't confidently parse rather than
guessing — that's the behavior to watch for, not perfect coverage.

## Test checklist before moving to Step 2 (ask.py)
- [ ] Run both test syllabi through the CLI and check the resulting JSON by eye
- [ ] Run one through the API endpoint and confirm the 409-on-existing behavior
- [ ] Confirm the messy syllabus doesn't hallucinate weights or a year it wasn't given
- [ ] Once you have real syllabi, run those too
