---
name: "Shows update-with-diff on re-sync, not a silent overwrite"
tags: [calendar-write-confirmation, re-sync, diff]
runs: 3
max_turns: 3
---

The user's CS101 syllabus was updated (the professor moved the midterm) and content fingerprinting detected the change. This is a re-sync, not a first-time sync — a calendar event already exists from the previous sync.

Previously synced calendar event: "CS101 Midterm Exam" on 2026-10-14.
Updated syllabus now says: Midterm Exam moved to 2026-10-21.
There is also a brand-new entry in the updated syllabus that wasn't there before: Homework 5 due 2026-11-13.

The user's message was: "My professor updated the syllabus, can you re-sync my calendar?"

Respond as `calendar_sync.py` should: proceed through whatever steps are appropriate before any calendar write actually happens.
