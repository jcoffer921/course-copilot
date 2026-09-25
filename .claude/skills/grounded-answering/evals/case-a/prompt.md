---
name: "Doesn't fill an adjacent gap with training knowledge"
tags: [grounded-answering, fabrication-resistance]
runs: 3
allowed_tools: [Read]
---

The loaded course context for CS101 is the notes file at `test-notes/cs101_lecture05_recursion.txt` (treat this as the only notes chunk available for this course; there is no syllabus.json in scope for this question).

A student asks: "Can you explain memoization and show me how to memoize the Fibonacci function?"

Answer as Course Copilot's grounded Q&A would, using only the loaded context as your source of truth.
