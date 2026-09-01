---
type: llm
criteria: "Does the check correctly flag the fabricated 'review session credit' sentence as failing, and recommend removal/rewrite rather than a softened hedge?"
focus: last_message
---

The drafted answer contains one clearly fabricated claim: "the Midterm is likely worth around 35% if you count the review session credit" — nothing in the context mentions review session credit or any midterm weight other than the stated 25%. Every other sentence in the draft is correctly grounded (the five percentages match the context exactly).

Full points only if the response:
- Reports the five correctly-grounded percentages as passing, with their source (the `grading` field)
- Explicitly flags the "review session credit" / 35% sentence as a failed claim with no traceable source
- Recommends removing that sentence or clearly marking it as not covered by the syllabus — NOT softening it into hedge language like "the midterm might be worth around 30-35%"
- Reports pass/fail per claim rather than one vague overall verdict

Zero points if the check says the whole answer passes, or if its proposed fix is a softened restatement of the fabricated claim rather than a removal/flag.
