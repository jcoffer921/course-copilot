---
name: "Doesn't over-flag a fully grounded answer"
tags: [grounding-check, false-positive-resistance]
runs: 3
---

Run a grounding check on this drafted answer against the given context.

CONTEXT (the only source of truth — a notes chunk for CS101 lecture 5):
```json
{
  "lecture_id": "cs101_lecture05",
  "chunks": [
    {"id": "recursion-def", "text": "A function that calls itself is recursive. Every recursive function needs two parts: a base case that stops the recursion, and a recursive case that breaks the problem into a smaller version of itself. Without a base case, the function calls itself forever and the program crashes with a stack overflow (RecursionError in Python)."}
  ]
}
```

DRAFTED ANSWER (about to be sent to the student):
"Recursion is when a function calls itself. Every recursive function needs a base case (which stops the recursion) and a recursive case (which breaks the problem into a smaller version of itself). If you forget the base case, the function will call itself forever and Python will raise a RecursionError from a stack overflow. (Source: lecture 5, chunk recursion-def.)"

Decompose the drafted answer into claims, check each against the context, and report the result.
