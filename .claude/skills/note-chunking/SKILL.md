---
name: note-chunking
description: Split raw lecture notes into topic-bounded chunks conforming to the notes/<lecture_id>.json schema. Use whenever running chunk_notes.py, deciding chunk boundaries, or converting free-form notes into structured chunks. Make sure to consult this skill any time notes are being segmented, since chunk quality directly determines quiz question quality and Q&A retrieval accuracy later.
---

# Note Chunking

Chunk by **topic**, not by character count or paragraph count. Notes get stuffed into context whole in v1 (no retrieval yet), but chunk boundaries still matter — they're what quiz generation samples from and what grounded answers cite back to. A chunk that spans two unrelated topics makes both quiz questions and citations muddier than they need to be.

## Output contract

```json
{
  "lecture_id": "string",
  "date": "YYYY-MM-DD",
  "topics": ["string"],
  "chunks": [{"id": "string", "text": "string"}]
}
```

## Chunk boundary rules

1. **A chunk should represent one coherent idea or subtopic**, not an arbitrary slice. If the lecture covers "recursion" then "dynamic programming," those are at least two chunks even if the notes run together without a heading.
2. **Prefer the source's own structure first.** Headings, bullet groupings, and slide breaks in the raw notes are strong signals — use them before inventing your own boundaries.
3. **Don't split a single idea across chunks just to hit a size target.** A long, dense explanation of one concept is one chunk. A short chunk is fine if the topic is genuinely small.
4. **Don't merge unrelated topics into one chunk just because they're short.** Two one-sentence topics are two chunks, not one.
5. Each chunk needs a stable, unique `id` within the lecture file (e.g. `"01"`, `"02"`, or a short topic slug like `"recursion-base-case"`) — used later for citation in grounded answers.

## Topics field vs. chunk-level content

`topics` at the file level is the lecture's topic list overall (used for syllabus cross-referencing and quiz scoping). It should roughly match the union of what the individual chunks cover, but doesn't need a strict 1:1 mapping to chunk count — a lecture can have 3 listed topics and 7 chunks if a topic took several distinct points to cover.

## Process

1. Read the full raw notes file before chunking anything — topic boundaries are sometimes only clear once you've seen where a thread picks back up later.
2. Draft chunk boundaries first as an outline (topic labels only), then fill in chunk text — this avoids drifting into character-count thinking mid-pass.
3. Validate against the schema before writing.
4. If the raw notes are malformed, empty, or unreadable (not just messy — actually unusable), fail loudly and report it rather than producing an empty or near-empty `chunks` array silently.

## Open decision to flag, not resolve unilaterally

This project has an explicit open decision on chunking granularity (by lecture vs. by topic) and whether retrieval becomes necessary once chunk count grows past full-context-stuffing size. Don't silently pick a new granularity strategy mid-project — if a lecture's content genuinely doesn't fit the current topic-chunking approach (e.g. it's unusually long or unusually unstructured), flag that to the user rather than quietly changing the pattern.

## What NOT to do

- Don't chunk by fixed character/token count.
- Don't invent topic labels not present in or reasonably inferable from the source notes.
- Don't collapse an entire lecture into a single chunk "to be safe" — that defeats the purpose of chunking.
- Don't silently drop chunks that seem redundant; note-taking redundancy is often intentional (recap, worked example).
