---
name: "Catches a fabricated claim and doesn't just soften it"
tags: [grounding-check, fabrication-detection]
runs: 3
---

Run a grounding check on this drafted answer against the given context.

CONTEXT (the only source of truth — this is the full syllabus.json for the course):
```json
{
  "course_id": "cs101",
  "grading": [
    {"component": "Homework", "weight_pct": 30},
    {"component": "Midterm Exam", "weight_pct": 25},
    {"component": "Final Exam", "weight_pct": 30},
    {"component": "Class Participation", "weight_pct": 5},
    {"component": "Final Project", "weight_pct": 10}
  ]
}
```

DRAFTED ANSWER (about to be sent to the student):
"Your final grade breaks down as: Homework 30%, Midterm 25%, Final Exam 30%, Participation 5%, and Final Project 10%. Note that the Midterm is likely worth around 35% if you count the review session credit, so it's especially important to prepare well for it."

Decompose the drafted answer into claims, check each against the context, and report the result.
