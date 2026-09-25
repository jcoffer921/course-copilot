---
type: llm
criteria: "Is the question traceable to a specific chunk in the source, self-contained, and moderate difficulty (since no mastery data exists yet)?"
focus: last_message
---

The chunk file has two chunks under "Overview of WebGL": `webgl-overview-intro` (why WebGL was created, what it fills the role of) and `webgl-advantages` (the numbered list of WebGL's advantages).

Full points only if the response:
- Names a specific source chunk id (webgl-overview-intro or webgl-advantages) the question is drawn from, and the question content actually matches that chunk's material
- Is self-contained — answerable from the question text alone, not requiring the chunk to be open, and does not quote large verbatim blocks from the chunk into the question
- Is neither trivially easy recall-of-a-single-word nor an advanced application/edge-case question — since there's no mastery data, the skill calls for a moderate default, not an assumption of strength or weakness
- Does not invent WebGL facts beyond what's in the two chunks (e.g. does not bring in outside knowledge about WebGL 2 or specific browser support details not stated in the source)

Zero points if the question can't be traced to specific chunk content, or if it fabricates a WebGL fact not present in the source.
