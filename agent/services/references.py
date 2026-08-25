"""
Ingests a reference document (e.g. a textbook chapter) for a course. Unlike
chunk_notes.py (semantic chunking) or syllabus_extraction.py (structured
field extraction), a reference doc just needs its raw text extracted and
stored whole — no LLM call in this file at all. The whole extracted text
gets stuffed into ask.py's context every time, same as syllabus and notes.
"""

import re
from pathlib import Path

from asgiref.sync import sync_to_async

from . import storage
from .syllabus_extraction import extract_text_from_bytes


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    # Truncate to 50 chars to leave room for -N collision suffix under 64-char limit
    slug = slug[:50].rstrip("-")
    return slug or "reference"


def _unique_reference_id(course_id: str, base_id: str, user) -> str:
    """Appends -2, -3, ... on collision so two references with the same
    title/filename don't clobber each other — reference_id is generated
    here, not supplied by the caller, so there's no user-facing overwrite
    decision to make."""
    candidate = base_id
    n = 1
    while storage.read_reference(course_id, candidate, user) is not None:
        n += 1
        candidate = f"{base_id}-{n}"
    return candidate


async def ingest_reference(course_id: str, file_bytes: bytes, filename: str, user, title: str = None) -> dict:
    text = extract_text_from_bytes(file_bytes, filename)

    resolved_title = (title or "").strip() or Path(filename).stem
    base_id = _slugify(resolved_title)
    reference_id = await sync_to_async(_unique_reference_id)(course_id, base_id, user)

    return {
        "reference_id": reference_id,
        "title": resolved_title,
        "source_filename": filename,
        "text": text,
    }
