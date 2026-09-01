---
name: "Doesn't treat a naming slip as a concept gap"
tags: [wrong-answer-analysis, carelessness]
runs: 3
---

Quiz question: "In the naive recursive Fibonacci implementation discussed in class, why does it get slow for larger n?"

Course material (chunk `fib-example`): "This works but recomputes the same values many times — fib(5) calls fib(3) twice, fib(2) three times, etc. This is a preview of why we'll care about Big-O later in the course: naive recursive fib is O(2^n), which gets slow fast."

Student's answer: "Because it does the same calculations over and over — like fib(3) gets called multiple times when computing fib(5). I think the complexity is like O(n^2) or something exponential, I don't remember the exact notation."

Classify this miss (concept gap / carelessness / ambiguous question) and explain how it should affect the topic's mastery score.
