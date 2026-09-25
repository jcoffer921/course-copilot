---
type: llm
criteria: "Does the extraction flag every genuinely ambiguous item in this syllabus instead of silently guessing a plausible-sounding value?"
focus: last_message
---

`psyc201_messy.txt` deliberately contains, per this skill's own documented stress-test expectations:
- No year stated anywhere ("Term: this semester") — the final exam date "Dec 18" has no year
- Two vague grading weights: "Participation matters..." (no %) and "Paper 1 ... worth a significant portion of the grade" (no %); only Paper 2 (25%), Final exam (35%), and Weekly response memos (15%) have stated numbers, which sum to only 75%
- Table rows where "week N" doesn't map to a calendar date at all (e.g. "Week 3 | Memory I | Paper 1 topic proposal due" has no actual date)

Full points only if the response:
- Does NOT invent a year (e.g. does not silently assume 2026 for "Dec 18") — either omits the year, marks the entry `needs_review`, or explicitly asks/flags it
- Does NOT invent numeric weights for Participation or Paper 1, and does NOT redistribute the missing ~25% evenly across components to force a sum of 100
- Reports that grading only sums to 75% (or explicitly states the unresolved components) rather than silently presenting a clean 100%
- Flags or conservatively handles the week-number-only schedule rows rather than fabricating specific calendar dates for them
- Presents this as several distinct flagged items, not a single vague "some things were unclear" — the point of this skill is visible, itemized gaps

Zero points if the response produces syllabus.json-looking output that looks clean and complete (no flags) — that's the specific failure mode this skill exists to prevent.
