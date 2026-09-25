---
name: deadline-digest
description: Format an upcoming-deadlines digest from syllabus.json date entries for reminders.py, whether manually invoked or run on a cron schedule. Use this whenever generating a deadline summary or reminder digest across one or more courses.
---

# Deadline Digest

`reminders.py` is read-only and digest-style — it summarizes what's coming up, it doesn't write anywhere (that's `calendar_sync.py`'s job, kept deliberately separate). This skill governs the digest's content and tone.

## Source

Pull only from `dates` arrays in each course's `syllabus.json`. Don't infer additional deadlines from notes chunks or general course-pattern assumptions (e.g. don't assume "there's probably a problem set due Friday" just because that's a common pattern) — if it's not in the syllabus dates, it's not in the digest.

## Scoping the window

Default to a reasonable near-term window (e.g. next 7–14 days) unless the caller specifies otherwise. Group by course if multiple courses are in scope, and sort chronologically within each.

## Format

- Lead with the soonest deadline.
- Include date, title, and type (exam/assignment/reading/other) for each entry.
- Flag anything within 48 hours distinctly (e.g. "due tomorrow") rather than burying it in a plain date list.
- If a date entry was flagged as uncertain during extraction (missing year, etc. — see `syllabus-extraction`), surface that uncertainty in the digest rather than presenting it with false confidence.

## What NOT to do

- Don't editorialize about workload or stress ("that's a lot due this week!") — state the facts, let the student assess their own load.
- Don't silently drop past-due entries that weren't marked complete — surface them if they're recent, since a missed deadline the student didn't act on is still relevant information.
- Don't write anything to disk or trigger any calendar action from this skill — digest generation is strictly read-and-summarize. Any write path belongs to `calendar-write-confirmation`.
