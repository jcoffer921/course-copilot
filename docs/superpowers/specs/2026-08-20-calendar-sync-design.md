# Google Calendar Sync — Design

## Problem

The Google Sign-In flow (see `docs/superpowers/specs/2026-08-20-google-accounts-design.md`)
already requests the `calendar.events` scope and stores each signed-in
user's `access_token`/`refresh_token`/`token_expiry` on `GoogleAccount` —
but nothing uses them yet. `CLAUDE.md` has flagged Calendar sync as a
deferred feature since project inception, with two constraints already
decided: push events one at a time with explicit confirmation (never bulk
a semester's dates in one call — `reminders.py` is for browsing, not
syncing), and treat it as a dry-run-first action, not silent background
sync.

The Dashboard's "Upcoming" panel already surfaces `reminders.upcoming_deadlines()`
per course — exams, assignments, reading, other — read from each course's
`syllabus.json`. This feature turns that existing read-only list into
something actionable: push an individual deadline into the signed-in
user's real Google Calendar.

## Decisions

- **One event at a time, from the existing Dashboard Upcoming panel** — no
  new nav tab, no calendar grid view, no bulk "sync everything" action.
  Each deadline row gets an "Add to Calendar" action; clicking it is the
  confirmation (satisfies "per-event explicit confirmation" — there's no
  separate dry-run step because the click itself is the commit, and
  nothing happens before it).
- **Sync state is tracked and duplicates are prevented.** New per-course
  file `courses/<course_id>/calendar_sync.json` records every deadline
  that's been pushed, keyed by `(date, title)` (syllabus dates have no
  stable ID — see `syllabus.json`'s schema in `CLAUDE.md`), storing the
  Google Calendar event ID returned by the API. `dashboard.py`'s existing
  aggregation annotates each deadline with `synced: true/false` by
  cross-referencing this file, so the UI can render "Added ✓" without a
  second round-trip.
- **UI + API only, no `manage.py` CLI wrapper** — deferred until there's an
  actual need to script this outside the browser.
- **New dependency**: `google-api-python-client`, for `googleapiclient.discovery.build("calendar", "v3", credentials=...)`. Not yet in `requirements.txt`.
- **Token refresh happens inline, transparently.** `GoogleAccount.access_token`
  can be (and after ~1 hour, will be) expired by the time a user clicks
  "Add to Calendar." The service builds a `google.oauth2.credentials.Credentials`
  object from the stored tokens and calls `.refresh()` via
  `google.auth.transport.requests.Request()` if expired, using the stored
  `refresh_token` — then persists the refreshed `access_token`/`token_expiry`
  back onto `GoogleAccount` so the next call reuses it. If refresh itself
  fails (revoked access, deleted consent), the endpoint returns a clear
  error the UI surfaces inline — "Could not connect to Google Calendar —
  try signing out and back in" — rather than a raw 500.
- **Events are all-day**, matching `syllabus.json`'s dates (date only, no
  time-of-day data exists to sync). Google Calendar's all-day event API
  requires an exclusive end date (start date + 1 day). Event summary
  includes the course; description notes the deadline type
  (exam/assignment/reading/other).

## Architecture

- `agent/services/calendar_sync.py` (new):
  - `_get_credentials(google_account) -> Credentials` — builds/refreshes,
    persists refreshed tokens back to the `GoogleAccount` row.
  - `add_deadline_to_calendar(user, course_id, date, title, event_type) -> dict`
    — refuses (raises) if `(date, title)` is already recorded in
    `calendar_sync.json`; otherwise calls the Calendar API, records the
    result, returns `{"google_event_id": ...}`.
- `agent/services/dashboard.py`: existing `upcoming_deadlines(...)` call
  site gets each dict annotated with `synced` by reading
  `calendar_sync.json` (absent file = nothing synced yet, same
  "absence is a normal state" convention as `trusted_domains.json`/
  `mastery_scores.json`).
- `agent/views.py`: new `CalendarSyncView` (`POST /api/courses/<course_id>/calendar-sync/`),
  async, following the existing `APIView`/`sync_to_async` pattern used
  throughout this file.
- `agent/templates/agent/ontrack.html`: each Upcoming-panel deadline row
  gets an "Add to Calendar" button (hidden/replaced with a checkmark once
  `synced` is true), wired through `renderVals()` the same way other
  per-row actions already are in this file.

## calendar_sync.json schema

```json
{
  "course_id": "string",
  "synced": [
    {"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other", "google_event_id": "string", "synced_at": "ISO8601"}
  ]
}
```

Absent entirely until the first successful sync for that course — same
convention as `trusted_domains.json`.

## Non-goals

- No calendar grid/month view in the UI.
- No two-way sync (reading the user's existing Google Calendar events back
  into OnTrack).
- No bulk/"sync all" action.
- No `manage.py calendar_sync` CLI wrapper.
- No un-syncing / deleting a previously-created Google Calendar event from
  OnTrack's side.

## Testing

- `calendar_sync.add_deadline_to_calendar`: creates an event (mocked
  Calendar API client), records it in `calendar_sync.json`, refuses a
  second call for the same `(date, title)`.
- Credential refresh: expired token triggers `.refresh()` and persists the
  new token/expiry to `GoogleAccount`; refresh failure surfaces as a
  handled error, not an unhandled exception.
- `dashboard.py`: deadlines correctly annotated `synced: true/false`
  against a `calendar_sync.json` fixture, and correctly `false` for every
  deadline when the file doesn't exist yet.
- `CalendarSyncView`: success path (200 + event id), already-synced
  rejection, and a Google-API-failure path returning a clear error instead
  of a 500.
