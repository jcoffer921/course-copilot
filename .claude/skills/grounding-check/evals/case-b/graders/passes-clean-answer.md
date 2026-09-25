---
type: llm
criteria: "Does the check correctly pass this answer, which is a faithful paraphrase of the single provided chunk with correct citation, without inventing a false failure?"
focus: last_message
---

The drafted answer is a straightforward, accurate paraphrase of the one chunk provided — it introduces no new facts, numbers, or claims beyond what the chunk states, and it already cites its source.

Full points only if the response:
- Reports that all claims pass (or reports zero failing claims)
- Does not invent a nitpick failure (e.g. does not penalize it for "paraphrasing" as if paraphrasing itself were a grounding violation, and does not flag the citation format as wrong)
- Correctly identifies the citation (lecture 5, chunk recursion-def) as adequate sourcing

Zero points if the check reports any claim in this answer as failing or unsupported — that would indicate the check is over-triggering on a genuinely clean, well-cited answer, which is its own failure mode worth catching.
