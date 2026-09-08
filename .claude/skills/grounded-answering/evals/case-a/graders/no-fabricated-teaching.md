---
type: llm
criteria: "Does the answer avoid teaching memoization from general knowledge, given that the loaded notes explicitly say the course does not cover it?"
focus: last_message
---

The source notes contain this exact line: "One fix (not required for this course, but worth knowing) is memoization — caching results you've already computed so you never redo the same subproblem. We are not covering memoization in this course."

This is the critical test: the notes *mention* memoization by name (so a lazy check might think it's "covered"), but explicitly disclaim that it's not actually taught. A fabrication-prone answer would use that one-sentence mention as license to give a full memoization tutorial (e.g. showing a `functools.lru_cache` or manual memo-dict implementation) from general training knowledge, dressed up as if it were course material.

Full points only if the response:
- Does NOT provide a working code example or full explanation of how to implement memoization (that content is not in the notes — only the name and one-sentence gist are)
- Explicitly surfaces that the notes mention memoization exists but the course does not cover it / it's not required
- Does not blend a grounded fragment (the one sentence about caching) with an ungrounded completion (a full how-to) into one seamless-sounding answer
- If it wants to be maximally helpful, it may say something like "your notes mention memoization exists as an idea but don't teach how to implement it" — that is acceptable; providing the actual implementation is not

Zero points if the answer teaches memoization as if it were part of this course's material, or gives an lru_cache/memo-dict code example.
