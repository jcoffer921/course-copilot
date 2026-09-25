---
name: wrong-answer-analysis
description: Analyze an incorrect quiz answer to classify it (concept gap vs. carelessness vs. ambiguous question) before writing the result to quiz_history.json and updating mastery scores. Use this whenever quiz.py records a wrong answer, since the classification determines how much the EWMA mastery score should move and whether the topic should resurface soon.
---

# Wrong Answer Analysis

`quiz_history.json` is an append-only event log; `mastery_scores.json` is a derived, rebuildable view. This skill governs what gets written to the log's classification field and how strongly a miss should move the derived mastery score — getting this wrong quietly degrades quiz targeting over time, since it feeds every future difficulty-calibration decision.

## Classifying a miss

Before writing the event, determine which of these best fits:

- **Concept gap**: the answer reflects a genuine misunderstanding of the underlying idea — wrong mechanism, wrong definition, confused two related concepts. This should meaningfully lower mastery on that topic.
- **Carelessness / slip**: the answer suggests the student knows the material but made an error unrelated to understanding — misread the question, arithmetic slip on an otherwise-correct approach, right concept named incorrectly. This should lower mastery only slightly, if at all — don't let a slip look like a knowledge gap.
- **Ambiguous or poorly-scoped question**: the wrong answer may be defensible given how the question was phrased, or the question itself reached beyond what the notes actually cover. This should not be scored as a mastery miss at all — flag the question as low-quality instead of penalizing the student for it.

Use the student's actual answer text as evidence for the classification — don't default to "concept gap" as a safe assumption just because the answer was wrong.

## What NOT to do

- Don't retroactively rewrite or overwrite past `quiz_history.json` entries to "fix" a classification — it's an append-only log; if a classification turns out wrong, log a correction event rather than editing history.
- Don't infer a broader pattern ("student is weak in this whole unit") from a single miss — mastery scoring is EWMA-based specifically so single events don't overreact; respect that design rather than hand-adjusting scores beyond the formula.
- Don't classify a miss as carelessness just because the student seems otherwise strong on the topic — check the actual answer content each time.

## Relationship to quiz-generation

The mastery scores this skill helps maintain are exactly what `quiz-generation` reads to calibrate future question difficulty. A miscalibrated classification here shows up later as a badly-targeted quiz, not as an obvious bug — treat the classification step with real care rather than as a formality.
