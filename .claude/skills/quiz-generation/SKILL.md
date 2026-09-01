---
name: quiz-generation
description: Generate quiz questions grounded strictly in a course's syllabus.json and notes chunks, calibrated to mastery scores and avoiding recent repeats. Use for every call in quiz.py that produces a new question or question set. Make sure to consult this skill whenever generating, scoping, or difficulty-tuning quiz questions, since quiz quality depends on both grounding fidelity and honoring the mastery-scoring system already in place.
---

# Quiz Generation

Quiz questions carry the same grounding constraint as `ask.py` — never invent content not present in the course material. A quiz question about something the notes don't cover is worse than no question at all, because it can teach the student something false or untaught as if it were examinable.

## Source of truth

Every question must be traceable to a specific notes chunk or syllabus field. Before finalizing a question, confirm you can point to the exact source it was drawn from — same discipline as the `grounding-check` skill, applied to generated questions instead of drafted answers.

## Difficulty calibration from mastery scores

Pull the topic's current mastery score (from the EWMA-based `mastery_scores.json`) before generating a question on that topic:

- **Low mastery / recently weak**: favor recall and definition-level questions — reinforce fundamentals before testing application.
- **High mastery**: favor application, comparison, or edge-case questions — don't keep asking easy questions on something already mastered.
- **No mastery data yet** (topic never quizzed): default to a moderate-difficulty question; don't assume either strength or weakness.

## Avoiding repeats

Check `quiz_history.json` before generating — don't resurface a question asked in the last N sessions on the same topic (exact wording or trivial rewording both count as repeats). Vary the angle (different chunk within the same topic, different question type) rather than reusing the same question with cosmetic changes.

## Question format

Keep questions self-contained — a student should be able to answer using only the question text plus their own course knowledge, not requiring them to have the source chunk open. Don't quote large verbatim blocks from notes into the question; paraphrase the setup and ask about the underlying concept.

## Process

1. Determine topic scope for this quiz session (single lecture, single topic, or course-wide — whatever the caller requests).
2. Pull mastery scores for candidate topics within scope.
3. Pull recent quiz history for those topics to avoid repeats.
4. Select topics/chunks to draw from, weighted toward lower-mastery topics unless the user requested otherwise (e.g. "quiz me on what I already know" is a valid override).
5. Draft questions, each traceable to a specific chunk or syllabus field.
6. Validate the question set doesn't duplicate recent history before returning.

## What NOT to do

- Don't generate a question and then loosely justify it against the notes after the fact — select the source chunk first, then write the question from it.
- Don't pad a quiz to a target question count by drawing on topics outside the requested scope.
- Don't silently skip low-mastery topics because they're harder to write good questions for — flag it if a topic's chunk content is too thin to generate a fair question, rather than quietly avoiding it.
