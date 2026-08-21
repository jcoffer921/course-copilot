# Manually-Added Deadlines + Full Deadlines View — Design

## Problem

Today, every deadline OnTrack knows about comes from one source: syllabus
extraction (`syllabus.json`'s `dates` array), read via
`reminders.upcoming_deadlines()` and displayed on the Dashboard's
"Upcoming deadlines" panel, capped at a 14-day window. There is no way to
add something OnTrack didn't extract — a rescheduled exam, a holiday, a
personal deadline — and no way to see everything beyond that 14-day
window at once.

This plan adds manually-created deadlines (course-specific or general —
not tied to any one course, e.g. holidays/breaks) with full add/edit/delete,
and a new full-list view to see every upcoming deadline, not just the next
two weeks.

**Explicitly out of scope, deferred to a separate follow-on plan:**
recurring weekly class schedules ("CS101 meets Mon/Wed/Fri 10am"). That's a
genuinely different data shape (a recurrence pattern, not a dated entry)
and needs its own design and its own Google Calendar sync approach
(recurring events use RRULE, not the one-off inserts this plan and the
existing Calendar sync feature both use). Nothing in this plan should
introduce recurrence, a schedule concept, or a "class session" type.

## Decisions

- **New storage: `courses/custom_events.json`**, a single top-level file
  (not per-course, unlike every other course JSON file) — because a
  general event has no single course to belong to. Holds every
  manually-created deadline, course-specific or general, each with a
  stable `id` (enabling edit/delete, same reason `grades.json` items have
  one). `course_id: null` means "general" — shows regardless of which
  course is selected in the sidebar, the same way syllabus-derived
  deadlines are filtered by `course_id` today except general ones bypass
  that filter.
- **Same type taxonomy as syllabus dates** (`exam|assignment|reading|other`)
  — no new "holiday" or "class" type. A holiday is `type: "other"`, same
  as any syllabus date OnTrack can't otherwise categorize. This keeps the
  existing tag/label rendering (`typeLabel`, `tagStyle`) working unchanged
  for both sources.
- **Optional `time` field** (`"HH:MM"` or `null`). Syllabus-derived
  deadlines never have one (the schema has no time-of-day data) and are
  unaffected. When a custom event has a time and gets pushed to Google
  Calendar, it becomes a real timed event (1-hour default duration)
  instead of all-day.
- **Sync state lives inline on the custom event itself**
  (`synced`/`google_event_id`/`synced_at` fields directly in
  `custom_events.json`), not in the existing per-course
  `calendar_sync.json`. That file's `(date, title)` key assumes every
  entry belongs to exactly one course — true for syllabus dates, not true
  for general custom events. Two independent, purpose-built sync
  mechanisms is simpler than forcing one shared, differently-shaped
  concern through the other.
- **New "Deadlines" sidebar nav tab** (alongside Dashboard/Chat/Progress/
  Quiz/Grades) is the full-list view: every upcoming deadline from both
  sources, unbounded (no 14-day cap — `within_days=None`, which
  `reminders.upcoming_deadlines()` already supports), sorted
  chronologically. "Add deadline" button lives in this tab's corner and
  opens the add/edit modal (date, optional time, title, a course-or-
  general dropdown, type).
- **Every row is tagged by source** (`"syllabus"` or `"custom"`) so the UI
  knows which rows get edit/delete controls. Only custom events are
  editable/deletable through this feature — a syllabus-extracted date
  isn't, since it comes from the syllabus itself and editing it here
  would just be silently overwritten the next time that course's syllabus
  is re-extracted.
- **Dashboard's existing Upcoming panel is untouched** except for one
  addition: a "See all →" link to the new Deadlines tab. Its 14-day
  window, its data source (`build_dashboard()`'s existing `deadlines`
  key), and its own sync-status badges (from the already-shipped Calendar
  sync feature) all stay exactly as they are — this plan doesn't touch
  syllabus-deadline sync at all, only adds a second, parallel source.
- **Full CRUD** on custom events (add, edit, delete) — explicitly in scope
  per this round of clarification, not deferred.

## Architecture

- `agent/services/custom_events.py` (new): `list_custom_events(course_ids=None) -> list`,
  `create_custom_event(course_id, date, time, title, event_type) -> dict`,
  `update_custom_event(event_id, **fields) -> dict`,
  `delete_custom_event(event_id) -> None`, and a Calendar-sync counterpart
  `sync_custom_event_to_calendar(user, event_id) -> dict` (mirrors
  `calendar_sync.add_deadline_to_calendar` but writes its result back onto
  the custom event's own `synced`/`google_event_id` fields instead of a
  separate tracking file, and builds a timed event when `time` is set).
- `agent/services/storage.py`: `read_custom_events() -> list`,
  `write_custom_events(events: list) -> Path` (whole-file overwrite, same
  "directly user-editable, not append-only" pattern as `grades.json`).
- `agent/services/reminders.py` or `dashboard.py`: a merge point that
  combines `upcoming_deadlines()` (syllabus source, tagged `source:
  "syllabus"`) with `custom_events.list_custom_events()` (tagged `source:
  "custom"`) into one chronologically-sorted list for the new Deadlines
  tab. The Dashboard's existing 14-day panel is NOT changed to include
  custom events in this plan — see Non-goals.
- New API views: `GET/POST /api/deadlines/` (list all, create),
  `PATCH/DELETE /api/deadlines/<event_id>/` (edit, delete),
  `POST /api/deadlines/<event_id>/calendar-sync/` (push a custom event to
  Google Calendar).
- `agent/templates/agent/ontrack.html`: new nav tab + its own tab content
  (list, add/edit modal, delete confirmation), plus the one-line "See
  all →" addition to the Dashboard's existing panel.

## custom_events.json schema

```json
{
  "events": [
    {
      "id": "string",
      "course_id": "string|null",
      "date": "YYYY-MM-DD",
      "time": "HH:MM|null",
      "title": "string",
      "type": "exam|assignment|reading|other",
      "synced": false,
      "google_event_id": "string|null",
      "synced_at": "ISO8601|null",
      "created_at": "ISO8601"
    }
  ]
}
```

Absent entirely until the first custom event is created — same "doesn't
exist yet = normal state" convention as `trusted_domains.json`.

## Non-goals

- Recurring class schedules (separate follow-on plan, see Problem).
- Changing the Dashboard's existing 14-day Upcoming panel to include
  custom events, or changing its existing sync-status UI in any way.
- Editing or deleting a syllabus-extracted date (only custom events are
  editable/deletable — re-extracting the syllabus is the only way to
  change those).
- A calendar grid/month view (still out of scope, same as the original
  Calendar sync plan).
- Un-syncing a custom event that's already been pushed to Google Calendar
  (same non-goal as the original Calendar sync plan — deleting a synced
  custom event from OnTrack does not delete the Google Calendar event).

## Testing

- `custom_events.py`: create/list/update/delete round-trip; a general
  (`course_id: null`) event appears in `list_custom_events()` regardless
  of which `course_ids` filter is passed; `sync_custom_event_to_calendar`
  builds a timed event when `time` is set and an all-day event when it
  isn't; re-syncing an already-synced custom event is refused.
- Merge logic: syllabus + custom deadlines combine correctly, each tagged
  with the right `source`, sorted by date.
- API views: full CRUD round-trip through HTTP; 404 on an unknown
  `event_id`; sync endpoint's success/already-synced/auth-failure paths
  (mirroring the existing Calendar sync endpoint's test coverage).
