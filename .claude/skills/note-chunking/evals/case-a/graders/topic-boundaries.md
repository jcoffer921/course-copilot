---
type: llm
criteria: "Are chunk boundaries drawn by coherent subtopic, matching this lecture's actual structure, rather than by arbitrary size?"
focus: last_message
---

The source notes clearly contain several distinct subtopics in sequence: (1) what recursion is / base case & recursive case, (2) the factorial example, (3) the Fibonacci example and its O(2^n) cost, (4) recursion vs. iteration, (5) common mistakes, (6) the practice problem (reversing a string).

Full points only if:
- The output has multiple chunks (at least 4-5) rather than one giant chunk or two arbitrarily-split halves
- Each chunk maps to one coherent subtopic from the list above rather than splitting a single idea (e.g. the factorial explanation) across two chunks
- Chunk `id`s are stable/descriptive, not just sequence-only artifacts of a fixed-size split
- The factorial and Fibonacci examples are NOT merged into one chunk just because they're both "recursion examples" — they are two different points, each with distinct content (fib's exponential blowup and the mention of memoization is a distinct point from factorial's simple base case)
- `topics` at the file level roughly matches the union of subtopics covered

Zero or near-zero points if the chunking looks like it was done by paragraph count or character count rather than by reading and understanding the content.
