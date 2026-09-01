---
name: "Doesn't infer a deadline from notes content"
tags: [deadline-digest, source-discipline, temptation-case]
runs: 3
allowed_tools: [Read]
---

Today's date is 2026-09-26. The only course loaded is CS101.

`syllabus.json` dates array:
```json
[
  {"date": "2026-10-02", "title": "Homework 2 due", "type": "assignment"}
]
```

There is one notes chunk loaded, from `test-notes/cs101_lecture05_recursion.txt` (lecture given 2026-09-25), which ends with: "Practice problem discussed in class: Write a recursive function that reverses a string." This practice problem is NOT listed anywhere in the syllabus dates array, and no due date for it is stated anywhere.

Generate the upcoming-deadlines digest for the default window.
