# Course Copilot — Quickstart

## Architecture (updated)
Django + DRF, served over **ASGI** (uvicorn) rather than WSGI. The extraction
call to Claude is I/O-bound and can take a few seconds — on WSGI that blocks
an entire worker thread per request; on ASGI with `AsyncAnthropic`, the event
loop stays free to handle other requests while waiting on the API. Views use
[`adrf`](https://pypi.org/project/adrf/) (async support for DRF) so handler
methods can be `async def` directly.

Course data (`syllabus.json`, notes, quiz history) stays on **flat JSON
files** under `courses/<course_id>/` — no database for course content. This
is a single-user project, so a DB layer would add complexity without adding
value. Django's own `db.sqlite3` exists only for its built-in auth/session/
admin tables and is never touched by course data.

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
scripts\run_server.bat        # Windows cmd.exe / PowerShell
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
