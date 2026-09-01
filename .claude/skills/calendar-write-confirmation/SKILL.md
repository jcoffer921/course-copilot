---
name: calendar-write-confirmation
description: Enforce plan-then-pause confirmation before any Google Calendar write in calendar_sync.py — creating, updating, or deleting calendar events from syllabus deadline data. Use this for every calendar write path, not just bulk syncs; a single-event write still requires the same confirmation discipline. calendar_sync.py is implemented and live against the real Google Calendar API — apply this skill to every write it makes, not a future one.
---

# Calendar Write Confirmation

Calendar writes are external side effects on a real account the student uses for everything else — a bad sync is more disruptive than a bad quiz question. This skill enforces the project's plan-then-pause rule specifically for `calendar_sync.py`, which is kept deliberately separate from the read-only `reminders.py` digest.

## Before any write

1. **Show the plan, not just the intent.** List exactly which events will be created/updated/deleted, with their source (which syllabus.json entry each maps to), before making any API call.
2. **Distinguish new syncs from re-syncs.** A first-time sync of a course's deadlines is additive; a re-sync after a syllabus update may involve updating or deleting previously-synced events — call out which category each change falls into, since deletions carry more risk than additions.
3. **Never write silently on a schedule.** Even if this is eventually cron-invoked like `reminders.py`, an unattended write to an external calendar is a bigger risk than an unattended digest — cron-triggered calendar syncs should still queue changes for confirmation rather than applying them unattended, unless the user has explicitly set up an auto-approve policy for a specific, narrow case (e.g. "always auto-add exam dates, always ask before anything else").
4. **Wait for explicit confirmation** before calling the calendar write API — a generic "looks fine" earlier in conversation doesn't count as confirmation for a specific batch of writes being proposed now.

## Handling ambiguous mappings

If a syllabus date entry doesn't map cleanly to a calendar event (unclear time, unclear duration, recurring vs. one-off), flag it in the plan rather than guessing a default (e.g. don't silently default every entry to a 1-hour all-day block without saying so).

## Handling sync conflicts

If a syllabus date changed since the last sync (detected via the project's SHA-256 content fingerprinting) and a calendar event already exists for the old date, the plan must show this as an update-with-diff (old value → new value), not a silent overwrite or a duplicate new event.

## What NOT to do

- Don't batch-write "since they're all from the same syllabus" as an excuse to skip per-batch confirmation — the batch itself needs to be shown and confirmed as a whole, but it still needs to be shown.
- Don't delete calendar events without listing them explicitly in the plan — deletions are the highest-risk category of write here.
- Don't treat prior authorization from a different sync session as still valid — confirmation is per-write-batch, not a standing permission.
