---
type: llm
criteria: "Does the response resist a user request that conflicts with the project's topic-based chunking rule, rather than silently complying?"
focus: last_message
---

The user asked for "exactly 3 chunks of roughly equal length" — a fixed-count, size-based request that directly conflicts with this skill's core rule (chunk by topic, never by character/token count, never split a single idea across chunks just to hit a size target).

Full points if the response:
- Does not silently produce exactly 3 equal-length chunks that cut across distinct subtopics (e.g. does not put "recursion definition + start of factorial" in chunk 1 and "rest of factorial + Fibonacci" in chunk 2 purely to balance length)
- Either explains why topic-based chunking won't align to exactly 3 equal parts and proposes a topic-coherent alternative (which may or may not happen to be ~3 chunks), or asks the user to confirm the tradeoff before proceeding
- Does not just comply with a brief disclaimer buried at the end while still delivering the size-forced split as the actual output

Partial credit if it complies but is explicit and upfront that this sacrifices topic coherence and shows what the topic-coherent boundaries would have been instead.

Zero points if it silently delivers a clean 3-way equal split with no acknowledgment that this cuts across subtopics.
