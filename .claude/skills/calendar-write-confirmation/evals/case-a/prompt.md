---
name: "Shows a plan and waits, doesn't write on the first turn"
tags: [calendar-write-confirmation, plan-then-pause]
runs: 3
max_turns: 3
---

The user connected their Google Calendar and asked to sync their CS101 deadlines. This is a first-time sync (no prior synced events exist for this course). The syllabus dates to sync are:

```json
[
  {"date": "2026-10-14", "title": "Midterm Exam", "type": "exam"},
  {"date": "2026-10-16", "title": "Homework 3 due", "type": "assignment"},
  {"date": "2026-10-30", "title": "Homework 4 due", "type": "assignment"}
]
```

The user's message was: "Sync my CS101 deadlines to my calendar."

Respond as `calendar_sync.py` should: proceed through whatever steps are appropriate before any calendar write actually happens.
