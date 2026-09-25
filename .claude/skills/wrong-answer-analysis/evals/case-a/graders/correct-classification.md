---
type: llm
criteria: "Is this correctly classified as a concept gap, with a mastery-score impact matching that classification?"
focus: last_message
---

The student's answer confuses "base case" with "the initial function call" — this is a genuine misunderstanding of the mechanism (the base case is the *terminating* condition, not the *first* call), not a slip on otherwise-correct understanding. This is a textbook concept gap per this skill's own definitions.

Full points only if the response:
- Classifies this as "concept gap" (not carelessness, not ambiguous question)
- Justifies the classification by referencing the specific content of the student's answer (the base-case/initial-call confusion), not a generic "it's wrong so it's a gap" assumption
- States that this should meaningfully lower mastery on this topic, consistent with a concept gap (not "lower only slightly" which is the carelessness treatment)
- Does not flag the question itself as ambiguous — the question is clearly and fairly scoped to what the notes cover

Zero points if it classifies this as carelessness or an ambiguous question, or if it defaults to "concept gap" without engaging with why the specific answer text supports that classification.
