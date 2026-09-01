---
type: llm
criteria: "Does the extraction confidently produce all fields with no invented values, and does it avoid flagging things that are actually unambiguous in the source?"
focus: last_message
---

`cs101_clean.txt` has no missing years, no vague grading weights, and no table-formatted dates — every date has an explicit year (2026), every grading component has a stated percentage, and the schedule is a plain bulleted list.

Full points only if the response:
- Extracts all 10 date entries with correct YYYY-MM-DD dates and plausible type classification (exam/assignment/reading/other)
- Extracts all 5 grading components with the exact stated percentages (30, 25, 30, 5, 10) and notes they sum to 100%
- Does NOT raise `needs_review` flags or uncertainty caveats for this file — since nothing here is actually ambiguous, flagging it anyway would mean the skill's uncertainty logic is too trigger-happy
- Presents the JSON and a summary before claiming it wrote/would write `syllabus.json` (plan-then-pause)

Deduct points if any date, weight, or topic is invented or altered from the source text.
