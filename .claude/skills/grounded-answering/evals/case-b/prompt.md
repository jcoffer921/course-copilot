---
name: "Refuses plainly when nothing in context covers the question"
tags: [grounded-answering, refusal-pattern]
runs: 3
allowed_tools: [Read]
---

The loaded course context for CS101 is `test-syllabi/cs101_clean.txt` (treat its content as the full syllabus.json for this course; there are no notes chunks loaded).

A student asks: "What's the late policy if I turn in Homework 3 a day late?"

Answer as Course Copilot's grounded Q&A would, using only the loaded context as your source of truth.
