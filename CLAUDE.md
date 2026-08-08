# Course Copilot — Project Instructions

## What this project is
An AI agent scoped to the current semester's coursework, built on the Anthropic API. It answers questions, tracks deadlines, and generates quizzes grounded in the user's actual syllabi and notes — not generic content.

## Stack
- Anthropic API (Messages endpoint), Python
- Sonnet for extraction/quiz/chat; reserve Opus for rubric critique if reasoning quality matters more than cost
- Structured JSON per course as the knowledge store (no vector DB in v1)
- Optional: Google Calendar API for deadline sync (later phase, not v1)

## Non-negotiable constraints
- Never fabricate course content. If the knowledge base doesn't contain something, say so — don't answer from training data or general knowledge as if it's the course's material.
- Rubric critique mode never writes the assignment for the user. Scaffold, question, and critique only.
- All extracted data (dates, topics, notes chunks) goes through a defined JSON schema — no free-text dumps into course files.
- Plan-then-pause: before any destructive or bulk write (overwriting a course's JSON, bulk re-parsing notes), pause and confirm.

## File structure
```
course-copilot/
  courses/
    <course_id>/
      syllabus.json       # extracted dates, topics, grading breakdown
      notes/
        <lecture_id>.json # chunked notes, one file per lecture/topic
      quiz_history.json   # questions asked, correct/incorrect, timestamps
  scripts/
    extract_syllabus.py   # PDF/text -> syllabus.json
    chunk_notes.py        # raw notes -> notes/<lecture_id>.json
    quiz.py                # generates + tracks quiz questions
    ask.py                  # loads course context, answers grounded questions
  CLAUDE.md               # this file
```

## Schemas (v1)

**syllabus.json**
```json
{
  "course_id": "string",
  "course_name": "string",
  "dates": [{"date": "YYYY-MM-DD", "title": "string", "type": "exam|assignment|reading|other"}],
  "grading": [{"component": "string", "weight_pct": 0}],
  "topics": ["string"]
}
```

**notes/<lecture_id>.json**
```json
{
  "lecture_id": "string",
  "date": "YYYY-MM-DD",
  "topics": ["string"],
  "chunks": [{"id": "string", "text": "string"}]
}
```

## Build order (don't skip ahead)
1. `extract_syllabus.py` — test extraction reliability first; this is the highest-risk step
2. `ask.py` — simplest possible grounded Q&A loop, single course, notes stuffed into context
3. `quiz.py` — question generation + wrong-answer tracking
4. Rubric critique mode
5. Calendar sync (only after 1–4 are solid)

## Definition of "working" for each script
- Runs standalone from CLI with no manual context-pasting
- Fails loudly (no silent empty results) if the source file is missing or malformed
- Output validated against the JSON schema before writing to disk

## Open decisions (revisit before scaling past one course)
- Chunking granularity for notes (by lecture vs. by topic) — affects quiz quality and when retrieval becomes necessary instead of full-context stuffing
- Whether quiz_history feeds back into anything (e.g., resurfacing weak topics) or stays a passive log in v1
