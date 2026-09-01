---
name: grounding-check
description: Verify a drafted answer against the loaded course context before it's returned to the user, checking that every factual claim traces to a specific syllabus field or notes chunk. Use this as a post-draft verification pass in ask.py, distinct from grounded-answering (which governs how the draft is written) — this is the structural check that catches fabrication that slipped through despite following the grounded-answering rules. Trigger this whenever a grounded answer is about to be finalized and returned, not just when fabrication is suspected.
---

# Grounding Check

This is the enforcement layer, not the drafting layer. `grounded-answering` tells the model how to write an answer correctly; this skill is the second pass that catches it when that didn't fully work. Prompt-only fabrication prevention is soft — this check exists because Course Copilot's non-negotiable constraint deserves a structural backstop, not just good instructions.

## What this check does

Given a drafted answer and the context it was supposedly grounded in:

1. **Decompose the answer into individual factual claims.** A claim is any statement of fact — a date, a definition, a grading weight, a topic explanation, a policy. Opinions, summarization framing, and meta-commentary ("here's what I found") aren't claims and don't need tracing.
2. **For each claim, locate the specific source.** Which chunk id, which syllabus field, which notes entry supports it? If you can't point to a specific source, the claim fails the check.
3. **Flag any claim that fails.** A failed claim means either: (a) it should be removed from the answer, or (b) the answer needs to be rewritten to explicitly mark that part as not covered by the course material.
4. **Do not silently patch a failed claim by softening its wording.** Turning "the midterm is worth 30%" into "the midterm is likely worth around 30%" when 30% isn't actually in the syllabus is still fabrication with a hedge on it — the correct fix is removing the claim or flagging the gap, not softening the confidence.

## When this catches something grounded-answering missed

Typical failure patterns worth specifically checking for:
- A number (percentage, date, page count) that's close to but not exactly what's in the source — transcription drift during answer generation.
- A concept correctly attributed to "the course" but actually filled in from general knowledge because the notes only partially covered it.
- A synthesis across multiple chunks that's individually grounded per-chunk but combines them into a claim neither chunk actually makes on its own.

## Output of the check

Report pass/fail per claim, not just an overall verdict — this makes it possible to fix a specific sentence rather than regenerating the whole answer. If all claims pass, the answer proceeds as drafted. If any fail, revise only the failing portions and re-check before returning to the user.

## Relationship to other skills

Use `grounded-answering` to draft; use this skill to verify before the answer leaves the system. Both exist because Course Copilot's constraint is "never fabricate" — a rule serious enough to warrant belt-and-suspenders rather than trusting a single well-written prompt.
