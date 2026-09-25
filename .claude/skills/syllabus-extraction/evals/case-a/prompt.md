---
name: "Clean syllabus extracts with zero false flags"
tags: [syllabus-extraction, happy-path]
runs: 3
allowed_tools: [Read]
---

Read `test-syllabi/cs101_clean.txt` and extract it into the `syllabus.json` schema this project uses (course_id, course_name, dates[], grading[], topics[]).

Show me the extracted JSON and a summary of anything you were unsure about, before writing the file.
