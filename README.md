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
content. `CourseMaterial` rows contain only owned operational upload metadata,
not trusted extracted content. Content is genuinely per-user: two students can each have their own
`cs101` without colliding or seeing each other's data, which is what makes
piloting OnTrack to a department of students possible. Django's own
`db.sqlite3` exists only for its built-in auth/session/admin tables (plus
mutable per-user state like grades and quiz history, already scoped by a
`user` FK) and is never used to store extracted/generated course content.

The runtime `courses/` tree is ignored by Git except for `.gitkeep`. Historical
course fixtures live under `test-course-data/legacy-course-fixtures/` and are
not loaded as live user data.

The browser UI uses real Django page routes with a shared OnTrack shell:
`/dashboard/`, `/calendar/`, `/courses/`, `/cora/`, `/study/`,
`/profile/`, and `/settings/`. Anonymous visitors see the public welcome
page at `/`; `/login/` and `/signup/` are separate presentations of the
same Google identity flow, which creates the OnTrack account on first sign-in.
Course workspaces and materials are available at
`/courses/<course_id>/`, `/courses/<course_id>/materials/`,
`/courses/<course_id>/study/`, and `/courses/<course_id>/mastery/`. The legacy
course Schedule URL redirects to the owned course filter on the global Calendar;
OnTrack does not maintain a second course calendar interface. The JSON API
remains independently mounted under `/api/`; authenticated visits to `/`
redirect to `/dashboard/`.

`/profile/` is a read-only student overview composed from the authenticated
user's identity, owned courses, mastery, streak, and study activity.
`/settings/` remains the editing and privacy workspace. It persists bio,
university, major, graduation year, IANA timezone, preferred session length,
available study days, reminder lead time, and notification preference. Its
JSON download is owner-scoped and omits OAuth credentials and private storage
keys. Exam workspaces use these preferences when composing their deterministic
readiness and preparation plan.

`/courses/` is a page-owned, API-backed semester overview. Course IDs remain
stable while names, codes, instructors, colors, and semesters can be edited.
Archiving is reversible and preserves the course directory; archived courses
are excluded from active dashboard, calendar, and reminder planning. Permanent
deletion remains a separate typed-confirmation action.

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

CLI and HTTP material flows call the same lifecycle services. Syllabus uploads
are staged as `needs_review`; extraction alone never replaces confirmed course
data. The review step lets the student edit or exclude extracted dates, topics,
and grading rows before explicit confirmation. Failed lecture or reference
processing likewise keeps the previous valid source intact.

## Setup
```bash
cd course-copilot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...    # Windows: set ANTHROPIC_API_KEY=sk-ant-...

# Google Sign-In — identity only (openid, email, and profile)
# (every page redirects to a login that raises if these are unset). Get the
# client ID/secret from a Google Cloud Console OAuth client.
export GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
export GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
# Use "allowlist" for private beta (the default) or "open" for public signup.
export ONTRACK_ADMISSION_MODE=allowlist
# Used only in allowlist mode; empty/unset blocks everyone.
export ALLOWED_GOOGLE_EMAILS=you@example.com,teammate@example.com

# Google Calendar is optional and is not authorized by sign-in. Calendar sync
# endpoints return code=calendar_not_connected until connected separately from
# Settings. The connect flow requests Calendar access only; disconnecting does
# not sign the user out of OnTrack.
# In the Google Cloud Console OAuth web client, register both callbacks using
# the exact ONTRACK_BASE_URL origin (scheme, host, and port must match):
# http://127.0.0.1:8000/accounts/callback/
# http://127.0.0.1:8000/accounts/calendar/callback/

# Required only to run the 9 CLI dev-tool commands (extract_syllabus, ask,
# quiz, etc.) — they're dev/debug tools, never used by real students, and
# operate as this one designated owner account rather than taking a --user
# flag. Must match the email of a User who has signed in at least once.
export CLI_OWNER_EMAIL=you@example.com

# Exactly one active account may view the private pilot analytics page, API,
# and per-student CSV export. Defaults to CLI_OWNER_EMAIL when omitted.
export ONTRACK_PILOT_OWNER_EMAIL=you@example.com

# Optional material-processing bounds (defaults shown).
export ONTRACK_MAX_UPLOAD_BYTES=10485760
export ONTRACK_MATERIAL_PROCESSING_TIMEOUT_SECONDS=90

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

Then, from another terminal, create the course and stage a syllabus:
```bash
curl -X POST http://127.0.0.1:8000/api/courses/cs101/ \
  -H "Content-Type: application/json" \
  -d '{"course_name":"Intro to CS"}'

curl -X POST http://127.0.0.1:8000/api/courses/cs101/syllabus/extract/ \
  -F "file=@test-syllabi/cs101_clean.txt" \
  -F "course_name=Intro to CS"

curl http://127.0.0.1:8000/api/courses/cs101/syllabus/
```

The extraction response contains a material UUID and editable `candidate`.
Confirm it with `POST /api/courses/cs101/materials/<material_uuid>/confirm/`
using `{"confirm":true,"syllabus":{...}}`. Until that succeeds, the syllabus
detail endpoint continues returning the previous confirmed version (or `404`
for a new draft). Poll `GET /api/courses/cs101/materials/<material_uuid>/` for
the stable `uploaded`, `processing`, `needs_review`, `ready`, or `failed`
status. The browser workflow at `/courses/cs101/materials/` handles review and
polling.

## Cora conversations and citations

Cora conversations can be created, listed, resumed, renamed, and explicitly
deleted from `/cora/`. New answers return structured citations that point to
an owned syllabus, note/slide chunk, uploaded reference, internal course
record, or approved web URL. Clicking a citation opens a server-verified
preview; approved web material is labeled separately from uploaded course
material. Older conversations with string source labels remain readable.

The browser sends a UUID with each session question. Retrying a failed request
reuses that UUID, and the server atomically stores at most one user/assistant
exchange for it. Unsupported questions remain `grounded: false` with an empty
source list.

## Notification and study-reminder email delivery

The notification center includes overdue deadlines, personalized study
recommendations, and deep links to saved Cora replies. Users opt into in-app
study reminders and reminder emails independently from Settings. One study reminder is generated per local
calendar day and is based on that user's current ranked recommendation.
Users choose the delivery time in Settings; it is interpreted in their saved
timezone.

Run this from a scheduler every five minutes so each user's chosen time is
honored. Running it frequently is safe: the backend still sends at most one
email per enabled user per calendar day in that user's timezone.

```bash
python manage.py send_notifications
```

Delivery is idempotent: missed days never produce a catch-up burst, and a
failed send remains queued for another attempt that same day. Local
development prints mail to the console. For production, configure the `DJANGO_EMAIL_*`,
`DJANGO_DEFAULT_FROM_EMAIL`, and `ONTRACK_BASE_URL` values documented in
`.env.example`.

For a branded sender domain, publish SPF, DKIM, and DMARC records with your
mail provider, set `ONTRACK_DKIM_SELECTOR`, and verify DNS before launch:

```bash
python manage.py check_email_domain
```

A personal Gmail sender remains usable for a closed local pilot, but the
check deliberately warns until `DJANGO_DEFAULT_FROM_EMAIL` uses a domain
you control.

## Pilot operations

Create a checksum-verified backup of SQLite and the private `courses/` tree:

```bash
python manage.py backup_ontrack --output-dir backups --keep 14
```

The daily scheduler should run that command with rolling retention. Test a
restore before relying on it; `restore_ontrack` requires the exact typed
confirmation and creates a recovery copy before replacing current data.

`/health/` returns a public, secret-free health snapshot for uptime checks.
Before a deploy or pilot session, run configuration and integration checks:

```bash
python manage.py pilot_smoke_check
python manage.py pilot_smoke_check --live-smtp --live-ai
```

AI endpoints are protected by per-user burst and daily limits. Defaults are
`8/min` and `100/day`; configure `ONTRACK_AI_BURST_RATE` and
`ONTRACK_AI_DAILY_RATE` for the pilot population.

Pilot users can send feedback from every app page. Product metrics record only
small action events and safe scalar metadata—not note content, uploaded text,
questions, answers, or Cora message text. The public disclosure is `/privacy/`.

Feedback now lives at `/feedback/` and is anonymous by default: the database
does not attach the account or page, no feedback metric is created, and the
request logger suppresses the user ID. Users can opt into identified feedback
when they want follow-up. Public support requests are available at `/contact/`,
stored for operator review, protected by a per-IP hourly limit and honeypot,
and emailed to `ONTRACK_SUPPORT_EMAIL` when configured.

## Test syllabi
`test-syllabi/cs101_clean.txt` — well-structured, should extract cleanly.
`test-syllabi/psyc201_messy.txt` — deliberately messy (vague weights, no
explicit year, dates only spelled out for some rows in a table). Good for
checking that extraction *omits* what it can't confidently parse rather than
guessing — that's the behavior to watch for, not perfect coverage.

## Material lifecycle checks
- PDF, PPTX, DOCX, TXT, and Markdown uploads default to a 10 MB limit.
- Original filenames are display-only; private stored objects use randomized keys.
- Unsupported, oversized, empty, corrupt, or deceptively named files are rejected.
- Replacing or deleting trusted material requires explicit confirmation.
- Confirm the messy fixture omits uncertain weights and dates instead of guessing.
