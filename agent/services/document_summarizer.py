"""Summarizes one lecture's notes or one reference document — a quick bullet
recap (Haiku) or a deep academic breakdown (Sonnet). Reads only the one
targeted document's text via storage.read_notes/read_references; no
retrieval system, matching the project's existing full-context-stuffing
decision (CLAUDE.md's "Open decisions" section).

See agent/services/cora_skills/document_summarizer.py for the full routing
contract and validation rules this implements.
"""

from asgiref.sync import sync_to_async

from . import storage
from .client import CORA_MODELS, get_client
from .cora_json import parse_model_json

QUICK_SYSTEM_PROMPT = """You are Cora's quick-summary tool for OnTrack. Write a short, plain-language recap of \
the provided document — enough for a student to remember what it covers, not a deep study aid.

Rules:
- 3-6 short bullet points, each one sentence.
- Every point must be traceable to the provided text. Never add an outside fact, example, or \
technique the document doesn't contain.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{"summary": "string (markdown bullet list, \\n-separated)"}
"""

DEEP_SYSTEM_PROMPT = """You are Cora's deep-summary tool for OnTrack, building real study material from ONE \
document — not just shortening it. Extract what a student actually needs to understand and remember.

Rules:
- "key_concepts": the main ideas a student must come away understanding, in the document's own order.
- "definitions": only terms the document actually defines or clearly explains — term + a concise \
student-facing definition, never a definition invented from outside knowledge.
- "relationships": how ideas in this document depend on or build on each other (e.g. "X requires \
understanding Y first", "A and B are contrasted as..."). Omit this entirely (empty list) if the \
document is a flat list of facts with no real relationships between them — do not invent one.
- "likely_testable": specific points a student should expect to be asked about, grounded only in what \
this document emphasizes (repeated, defined, worked through an example, or explicitly flagged as \
important) — never a generic exam-prep platitude.
- Every field must be traceable to the provided text. Never introduce an outside fact, technique, or \
example the document doesn't contain.
- Output ONLY valid JSON matching the schema below. No preamble, no markdown fences, no commentary.

Schema:
{
  "key_concepts": ["string", ...],
  "definitions": [{"term": "string", "definition": "string"}, ...],
  "relationships": ["string", ...],
  "likely_testable": ["string", ...]
}
"""


class NoTargetDocumentError(Exception):
    """Raised when lecture_id/reference_id don't resolve to real content for this course."""


def _chunk_text(note: dict) -> str:
    return "\n\n".join(str(chunk.get("text", "")) for chunk in note.get("chunks", []))


def _resolve_target(course_id: str, lecture_id: str, reference_id: str, user) -> tuple[str, str, str]:
    """Returns (source_id, title, text). source_id is the exact lecture_id/
    reference_id a caller can cite (via citations.py) — distinct from
    "title", which is only for display and isn't always the same string
    (a reference's display title is often not its reference_id)."""
    if lecture_id:
        for note in storage.read_notes(course_id, user):
            if note.get("lecture_id") == lecture_id:
                return lecture_id, lecture_id, _chunk_text(note)
        raise NoTargetDocumentError(f"no notes found for lecture_id '{lecture_id}' in course '{course_id}'")

    if reference_id:
        for reference in storage.read_references(course_id, user):
            if reference.get("reference_id") == reference_id:
                return reference_id, reference.get("title") or reference_id, str(reference.get("text", ""))
        raise NoTargetDocumentError(f"no reference found for reference_id '{reference_id}' in course '{course_id}'")

    # Neither given — "summarize today's lecture" with no explicit target
    # falls back to the most recently added lecture's notes.
    notes = storage.read_notes(course_id, user)
    if notes:
        latest = notes[-1]
        latest_id = latest.get("lecture_id", "latest lecture")
        return latest_id, latest_id, _chunk_text(latest)

    raise NoTargetDocumentError(f"no notes or references available yet for course '{course_id}'")


async def summarize(
    course_id: str, lecture_id: str = None, reference_id: str = None, depth: str = "quick", user=None,
) -> dict:
    source_id, title, text = await sync_to_async(_resolve_target)(course_id, lecture_id, reference_id, user)
    if not text.strip():
        raise NoTargetDocumentError(f"'{title}' has no text content to summarize")

    client = get_client()

    if depth == "deep":
        response = await client.messages.create(
            model=CORA_MODELS["reasoning"],
            max_tokens=2000,
            system=DEEP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Document: {title}\n\n{text}"}],
        )
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        data = parse_model_json(raw, required_keys={"key_concepts", "definitions", "relationships", "likely_testable"})
        return {
            "source_id": source_id,
            "title": title,
            "depth": "deep",
            "key_concepts": [str(x) for x in data.get("key_concepts") or []],
            "definitions": [
                {"term": str(d.get("term", "")), "definition": str(d.get("definition", ""))}
                for d in data.get("definitions") or []
                if isinstance(d, dict) and d.get("term")
            ],
            "relationships": [str(x) for x in data.get("relationships") or []],
            "likely_testable": [str(x) for x in data.get("likely_testable") or []],
        }

    response = await client.messages.create(
        model=CORA_MODELS["fast"],
        max_tokens=600,
        system=QUICK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Document: {title}\n\n{text}"}],
    )
    raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    data = parse_model_json(raw, required_keys={"summary"})
    return {"source_id": source_id, "title": title, "depth": "quick", "summary": str(data.get("summary", "")).strip()}
