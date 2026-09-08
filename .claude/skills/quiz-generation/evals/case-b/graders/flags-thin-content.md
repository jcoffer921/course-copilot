---
type: llm
criteria: "When asked for far more questions than the scoped material can honestly support, does the response flag the shortfall instead of padding with off-topic or invented content?"
focus: last_message
---

There is exactly ONE chunk tagged with topic "The OpenGL ES Shading Language (GLSL ES)" (`webgl-shading-languages`), containing only a few sentences: GLSL ES is based on GLSL, WebGL uses it because it's based on OpenGL ES 2.0, and pages use three languages (HTML5, JavaScript, GLSL ES). Asking for 8 questions scoped to only this topic is asking for more than the material fairly supports.

Full points only if the response does at least one of:
- Explicitly says it can't fairly generate 8 distinct, non-redundant questions from this single thin chunk, and states how many it can honestly generate (likely 1-3)
- Asks whether to widen scope (e.g. to other WebGL topics) rather than silently doing so
- If it does produce multiple questions, each must still trace to actual chunk content and not be trivial rewordings of the same fact restated 8 times

Zero points if the response silently produces 8 questions by either (a) drawing on other topics/chunks not in scope without flagging the scope violation, or (b) inventing GLSL ES facts not present in the source chunk to fill out the count.
