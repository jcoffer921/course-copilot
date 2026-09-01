---
name: "Question traces to a real chunk, moderate default for no mastery data"
tags: [quiz-generation, grounding, calibration]
runs: 3
allowed_tools: [Read]
---

Read `test-course-data/legacy-course-fixtures/computer-graphics-algorithms/notes/Chapter-01.json`.

Generate one quiz question on the topic "Overview of WebGL". There is no mastery score yet for this topic (never quizzed before), and no quiz history to check against.

Show the question and tell me which chunk it's drawn from.
