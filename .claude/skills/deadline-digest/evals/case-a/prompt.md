---
name: "Digest pulls only from syllabus dates, flags near-term items"
tags: [deadline-digest, source-discipline]
runs: 3
---

Today's date is 2026-10-13. The only course loaded is CS101, with this `syllabus.json` dates array:

```json
[
  {"date": "2026-10-12", "title": "Homework 2 due", "type": "assignment"},
  {"date": "2026-10-14", "title": "Midterm Exam", "type": "exam"},
  {"date": "2026-10-16", "title": "Homework 3 due", "type": "assignment"}
]
```

Homework 2 (due 2026-10-12, i.e. yesterday) has not been marked complete. There are no notes chunks loaded. Generate the upcoming-deadlines digest for the default window.
