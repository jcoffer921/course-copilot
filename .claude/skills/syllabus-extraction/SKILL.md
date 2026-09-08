---
name: syllabus-extraction
description: Extract structured syllabus data (dates, grading breakdown, topics) from raw syllabus text/PDF into the syllabus.json schema. Use whenever parsing a syllabus, populating syllabus.json, or handling messy/incomplete syllabus source text (vague grading weights, missing years, table-formatted dates, inconsistent formatting). Make sure to consult this skill for extract_syllabus.py specifically, since this is the highest-risk step in the pipeline and errors here silently corrupt every downstream feature (Q&A, quizzes, deadline reminders).
---

# Syllabus Extraction

Extraction is the highest-risk step in Course Copilot. Everything downstream (grounded Q&A, quiz generation, deadline reminders) trusts `syllabus.json` completely. A wrong or invented date is worse than a missing one, because a missing one is visibly incomplete and a wrong one looks authoritative.

## Output contract

Every extraction must conform exactly to this schema — no additional fields, no free text:

```json
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other"}],
  "grading": [{"component": "string", "weight_pct": 0}],
  "topics": ["string"]
}
```

## Core rule: confidence over completeness

Never guess a value to fill a field. If the source text is ambiguous or missing information:

- **Missing year on a date** (e.g. "Midterm: Oct 14"): do not assume the current year or the year the file was uploaded. Flag it — emit the entry with the year omitted or a `"needs_review": true` marker (extend the schema locally for this, don't silently normalize) and surface it in the extraction summary shown to the user.
- **Vague grading weights** (e.g. "Participation: some amount", "Final exam weighted heavily"): do not invent a percentage. Omit the `weight_pct` value or flag the component as unresolved rather than writing a number that wasn't stated.
- **Table-formatted or multi-column dates**: parse conservatively. If a table row's columns don't map unambiguously to (date, title, type), extract what's certain and flag the rest — don't force a best-guess mapping.
- **Unparseable sections entirely**: report them to the user as "couldn't confidently extract: [excerpt]" rather than either fabricating structure or silently dropping the content.

The failure mode to avoid is *quiet confidence* — extraction that looks complete and clean but contains invented values. Loud, visible gaps are always preferable.

## Type classification for dates

Classify each date entry into exactly one of `exam | assignment | reading | other`. If a syllabus entry doesn't clearly fit (e.g. "project proposal due" — is that an assignment or other?), default to the closest fit and don't create new types. `other` is a legitimate catch-all, not a failure.

## Process

1. Read the full source text first before extracting anything — grading and dates are often split across non-adjacent sections.
2. Extract `course_id` and `course_name` first; these are usually unambiguous and anchor the rest.
3. Extract `grading` — sum the weights you're confident about and report the total. If it doesn't reach ~100%, say so explicitly rather than silently accepting a partial breakdown.
4. Extract `dates` — one pass per date-bearing section (schedule table, assignment list, exam dates section if separate). Don't assume all dates live in one place.
5. Extract `topics` — a flat list is fine; don't try to infer topic-to-date mappings unless the source states them explicitly.
6. Validate the draft JSON against the schema above before it's proposed for writing.
7. **Plan-then-pause**: present the extracted JSON and the list of flagged/uncertain items to the user before writing to `syllabus.json`, especially if this overwrites an existing file. This is a non-negotiable project constraint, not optional politeness.

## Testing against the known stress cases

This project maintains two test syllabi specifically to validate this skill:
- `cs101_clean.txt` — should extract cleanly with no flags; if this one produces uncertain items, the extraction logic itself likely has a bug, not the input.
- `psyc201_messy.txt` — deliberately has vague weights, a missing year, and table-formatted dates. This should produce several flagged items. Zero flags on this file is a signal the extraction is being too permissive (guessing instead of flagging).

## What NOT to do

- Don't normalize a missing year to "this year" or "next occurrence."
- Don't distribute an unstated remainder evenly across grading components to make weights sum to 100.
- Don't invent a `course_id` from the filename if the syllabus text doesn't state one — ask the user or leave it for confirmation.
- Don't write to `syllabus.json` without the plan-then-pause confirmation step, even on first creation.
