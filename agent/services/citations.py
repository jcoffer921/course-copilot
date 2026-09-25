"""Resolve model source labels into owned, inspectable citation records."""

import hashlib
import json
import re
from urllib.parse import urlparse

from agent.models import CourseMaterial, CourseSession

from . import grades, mastery, sessions, storage


MAX_EXCERPT_CHARS = 360
MAX_CITATIONS = 12
VALID_MATERIAL_TYPES = {"syllabus", "notes", "slides", "reference", "web"}
INTERNAL_SOURCE_TITLES = {
    "recalled_conversations": "Earlier course conversation",
    "quiz_history": "OnTrack quiz history",
    "mastery_scores": "OnTrack mastery scores",
    "flashcards": "OnTrack flashcard progress",
    "grades": "Entered course grades",
    "grade_calculator": "OnTrack grade calculation",
}
WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")


class CitationNotFoundError(Exception):
    pass


def _terms(*values: str) -> set[str]:
    return {word.lower() for value in values for word in WORD_RE.findall(value or "")}


def _excerpt(value: str) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= MAX_EXCERPT_CHARS:
        return normalized
    return normalized[: MAX_EXCERPT_CHARS - 1].rstrip() + "…"


def _best(candidates: list[dict], question: str, answer: str) -> dict:
    if not candidates:
        return {"text": "", "chunk_id": None, "page": None}
    target = _terms(question, answer)
    return max(
        candidates,
        key=lambda item: (len(target & _terms(item.get("text", ""))), -candidates.index(item)),
    )


def _material_rows(user, course_id: str) -> list[CourseMaterial]:
    return list(
        CourseMaterial.objects.filter(
            user=user,
            course_id=course_id,
            processing_status=CourseMaterial.STATUS_READY,
        ).order_by("-uploaded_at")
    )


def _active_material(rows, material_type: str, source_key: str = ""):
    for row in rows:
        if row.material_type != material_type:
            continue
        if source_key and row.source_key != source_key:
            continue
        if row.review_status == CourseMaterial.REVIEW_SUPERSEDED:
            continue
        if material_type == CourseMaterial.TYPE_SYLLABUS and row.review_status != CourseMaterial.REVIEW_CONFIRMED:
            continue
        return row
    return None


def _chunk_images(user, course_id: str, lecture_id: str, chunk) -> list[dict]:
    """Resolves a note chunk's image_ids (set by extract_figures.py) to real,
    still-present figure files. Never claims an image that isn't actually on
    disk — an image_id whose PNG was deleted out from under the manifest is
    silently skipped here rather than surfaced as a broken reference."""
    if not isinstance(chunk, dict):
        return []
    image_ids = chunk.get("image_ids")
    if not isinstance(image_ids, list):
        return []
    images = []
    for image_id in image_ids:
        try:
            path = storage.lecture_image_path(course_id, lecture_id, image_id, user)
        except storage.InvalidImageIdError:
            continue
        if path.exists():
            images.append({"image_id": image_id, "path": str(path)})
    return images


def _base(
    material_id, material_type, title, *,
    lecture_id=None, chunk_id=None, page=None, url=None, excerpt="", images=None,
):
    citation = {
        "material_id": str(material_id),
        "material_type": material_type,
        "title": str(title or material_id),
        "lecture_id": lecture_id,
        "chunk_id": chunk_id,
        "page": page,
        "url": url,
        "excerpt": _excerpt(excerpt),
    }
    # Omitted entirely (not even an empty list) when the grounding chunk has
    # no linked figures — same "absence is a normal state, don't pad every
    # record with an empty field" convention as CourseSession's sources/grounded.
    if images:
        citation["images"] = images
    return citation


def _syllabus_citation(user, course_id, rows, question, answer):
    syllabus = storage.read_syllabus(course_id, user)
    if syllabus is None:
        return None
    candidates = [{"text": f"Course: {syllabus.get('course_name', course_id)}"}]
    candidates.extend(
        {"text": f"{item.get('date', '')}: {item.get('title', '')} ({item.get('type', 'other')})"}
        for item in syllabus.get("dates", []) if isinstance(item, dict)
    )
    candidates.extend(
        {"text": f"{item.get('component', '')}: {item.get('weight_pct', '')}%"}
        for item in syllabus.get("grading", []) if isinstance(item, dict)
    )
    candidates.extend({"text": topic} for topic in syllabus.get("topics", []) if isinstance(topic, str))
    selected = _best(candidates, question, answer)
    row = _active_material(rows, CourseMaterial.TYPE_SYLLABUS)
    return _base(
        row.material_id if row else "legacy-syllabus",
        "syllabus",
        syllabus.get("course_name") or "Course syllabus",
        excerpt=selected["text"],
    )


def _notes_citation(user, course_id, rows, source_label, question, answer):
    note = storage.read_lecture(course_id, source_label, user)
    if note is None:
        return None
    candidates = [
        {"text": chunk.get("text", ""), "chunk_id": chunk.get("id"), "page": chunk.get("page"), "chunk": chunk}
        for chunk in note.get("chunks", []) if isinstance(chunk, dict) and chunk.get("text")
    ]
    selected = _best(candidates, question, answer)
    kind = CourseMaterial.TYPE_SLIDES if note.get("source") == "slides" else CourseMaterial.TYPE_NOTES
    row = _active_material(rows, kind, source_label)
    material_id = row.material_id if row else f"legacy-{kind}-{source_label}"
    title = row.original_filename if row else source_label
    return _base(
        material_id,
        kind,
        title,
        lecture_id=source_label,
        chunk_id=selected.get("chunk_id"),
        page=(
            selected.get("page")
            if isinstance(selected.get("page"), int)
            and not isinstance(selected.get("page"), bool)
            and selected.get("page") > 0
            else None
        ),
        excerpt=selected.get("text", ""),
        images=_chunk_images(user, course_id, source_label, selected.get("chunk")),
    )


def _reference_citation(user, course_id, rows, source_label, question, answer):
    reference = storage.read_reference(course_id, source_label, user)
    if reference is None:
        return None
    paragraphs = [part for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", reference.get("text", "")) if part.strip()]
    selected = _best([{"text": part} for part in paragraphs], question, answer)
    row = _active_material(rows, CourseMaterial.TYPE_REFERENCE, source_label)
    return _base(
        row.material_id if row else f"legacy-reference-{source_label}",
        "reference",
        reference.get("title") or (row.original_filename if row else source_label),
        excerpt=selected["text"],
    )


def citation_for_chunk(user, course_id: str, lecture_id: str, chunk_id: str):
    """Resolves the exact owned chunk a quiz question came from, for showing
    a source link alongside its explanation in quiz review. Unlike
    _notes_citation (which picks the best-matching chunk by text overlap),
    this looks up chunk_id directly since the caller already knows it."""
    if not lecture_id or not chunk_id:
        return None
    try:
        note = storage.read_lecture(course_id, lecture_id, user)
    except storage.InvalidLectureIdError:
        return None
    if note is None:
        return None
    chunk = next(
        (c for c in note.get("chunks", []) if isinstance(c, dict) and c.get("id") == chunk_id),
        None,
    )
    if chunk is None:
        return None
    rows = _material_rows(user, course_id)
    kind = CourseMaterial.TYPE_SLIDES if note.get("source") == "slides" else CourseMaterial.TYPE_NOTES
    row = _active_material(rows, kind, lecture_id)
    material_id = row.material_id if row else f"legacy-{kind}-{lecture_id}"
    title = row.original_filename if row else lecture_id
    page = chunk.get("page")
    return _base(
        material_id,
        kind,
        title,
        lecture_id=lecture_id,
        chunk_id=chunk.get("id"),
        page=page if isinstance(page, int) and not isinstance(page, bool) and page > 0 else None,
        excerpt=chunk.get("text", ""),
        images=_chunk_images(user, course_id, lecture_id, chunk),
    )


def _web_material_id(url: str) -> str:
    return "web-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def _conversation_fingerprint(message: dict) -> str:
    value = "\0".join(
        str(message.get(key) or "") for key in ("role", "content", "timestamp")
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _conversation_citation(user, course_id: str, question: str, session_id: str = None):
    recalled = sessions.relevant_messages(
        course_id, question, session_id=session_id, user=user, limit=1,
    )
    if not recalled:
        return None
    message = recalled[0]
    return _base(
        f"ontrack-conversation-{message['session_id']}-{_conversation_fingerprint(message)}",
        "reference",
        "Earlier course conversation",
        excerpt=message.get("content", ""),
    )


def _preview_conversation(user, course_id: str, material_id: str):
    prefix = "ontrack-conversation-"
    value = material_id.removeprefix(prefix)
    session_id, separator, fingerprint = value.rpartition("-")
    if not separator or not session_id or not fingerprint:
        return None
    session = CourseSession.objects.prefetch_related("messages").filter(
        user=user, course_id=course_id, session_id=session_id,
    ).first()
    if session is None:
        return None
    for row in session.messages.all():
        message = {"role": row.role, "content": row.content, "timestamp": row.timestamp}
        if _conversation_fingerprint(message) == fingerprint:
            return _base(
                material_id,
                "reference",
                session.title or "Earlier course conversation",
                excerpt=row.content,
            )
    return None


def _approved_web(user, course_id: str, url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower()
    approved = storage.read_trusted_domains(course_id, user)
    saved_sites = storage.list_saved_sites(course_id, user=user)
    saved = next((site for site in saved_sites if site.get("url") == url), None)
    allowed = saved is not None or any(hostname == domain or hostname.endswith("." + domain) for domain in approved)
    if not allowed:
        return None
    return _base(
        _web_material_id(url),
        "web",
        (saved or {}).get("title") or hostname,
        url=url,
        excerpt=(f"Saved course link: {url}" if saved else "Approved external web source. Open the source to inspect it."),
    )


def _saved_site_citation(user, course_id: str, question: str, answer: str):
    sites = storage.list_saved_sites(course_id, user=user)
    selected = _best(
        [
            {
                "text": f"{site.get('title', '')} {site.get('url', '')}",
                "site": site,
            }
            for site in sites
            if isinstance(site, dict) and site.get("url")
        ],
        question,
        answer,
    )
    site = selected.get("site")
    return _approved_web(user, course_id, site["url"]) if site else None


def _internal_citation(
    user, course_id: str, source_label: str, question: str, answer: str,
    session_id: str = None,
):
    title = INTERNAL_SOURCE_TITLES.get(source_label)
    if title is None:
        return None
    if source_label == "recalled_conversations":
        return _conversation_citation(user, course_id, question, session_id=session_id)
    if source_label == "quiz_history":
        value = storage.read_quiz_history(course_id, user=user)
    elif source_label == "mastery_scores":
        value = mastery.weak_topics(course_id, user=user)
    elif source_label == "flashcards":
        value = storage.read_flashcard_progress(course_id, user=user)
    elif source_label == "grades":
        value = storage.read_grades(course_id, user=user)
    elif source_label == "grade_calculator":
        value = grades.current_grade(course_id, user=user)
    selected = _best([{"text": json.dumps(value, ensure_ascii=False, default=str)}], question, answer)
    return _base(f"ontrack-{source_label.replace('_', '-')}", "reference", title, excerpt=selected["text"])


def validate_source_labels(source_labels) -> list[str]:
    """Validate the model-facing source-label shape before it reaches storage."""
    if not isinstance(source_labels, list):
        raise ValueError("Cora returned sources in an invalid format.")
    if len(source_labels) > MAX_CITATIONS:
        raise ValueError(f"Cora returned more than {MAX_CITATIONS} sources.")
    normalized = []
    for raw in source_labels:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Cora returned an invalid source label.")
        label = raw.strip()
        if len(label) > 2048 or (
            not label.startswith(("http://", "https://")) and len(label) > 64
        ):
            raise ValueError("Cora returned an invalid source label.")
        normalized.append(label)
    return normalized


def resolve_citations(
    user, course_id: str, source_labels, question: str, answer: str,
    session_id: str = None,
) -> list[dict]:
    """Resolve only real, owned labels; unknown or unapproved labels are rejected."""
    storage._validate_course_id(course_id)
    source_labels = validate_source_labels(source_labels)
    rows = _material_rows(user, course_id)
    citations = []
    seen = set()
    for label in source_labels:
        if label == "syllabus":
            citation = _syllabus_citation(user, course_id, rows, question, answer)
        elif label == "saved_sites":
            citation = _saved_site_citation(user, course_id, question, answer)
        elif label.startswith(("http://", "https://")):
            citation = _approved_web(user, course_id, label)
        elif label in INTERNAL_SOURCE_TITLES:
            citation = _internal_citation(
                user, course_id, label, question, answer, session_id=session_id,
            )
        else:
            try:
                citation = _notes_citation(user, course_id, rows, label, question, answer)
                if citation is None:
                    citation = _reference_citation(user, course_id, rows, label, question, answer)
            except (storage.InvalidLectureIdError, storage.InvalidReferenceIdError):
                citation = None
        if citation is None:
            raise ValueError(f"Cora cited an unavailable or unapproved source: {label!r}.")
        key = (citation["material_id"], citation.get("chunk_id"), citation.get("url"))
        if key not in seen:
            seen.add(key)
            citations.append(citation)
    return citations


def legacy_source_label(citation) -> str:
    """Convert a stored structured citation back to the model's label vocabulary."""
    if isinstance(citation, str):
        return citation
    if not isinstance(citation, dict):
        return ""
    if citation.get("material_type") == "web":
        return citation.get("url") or ""
    if citation.get("material_type") == "syllabus":
        return "syllabus"
    if citation.get("lecture_id"):
        return citation["lecture_id"]
    material_id = str(citation.get("material_id") or "")
    if material_id.startswith("ontrack-conversation-"):
        return "recalled_conversations"
    if material_id.startswith("ontrack-"):
        return material_id.removeprefix("ontrack-").replace("-", "_")
    return citation.get("title") or material_id


def preview_source(user, course_id: str, citation: dict) -> dict:
    """Re-resolve a client citation from owned source identifiers, ignoring client excerpt/title."""
    material_id = str(citation.get("material_id") or "")
    material_type = citation.get("material_type")
    if material_type not in VALID_MATERIAL_TYPES or not material_id:
        raise CitationNotFoundError("Source not found.")

    if material_type == "web":
        url = str(citation.get("url") or "")
        resolved = _approved_web(user, course_id, url)
        if resolved is None or resolved["material_id"] != material_id:
            raise CitationNotFoundError("Source not found.")
        return resolved

    if material_id.startswith("ontrack-conversation-"):
        if material_type != "reference":
            raise CitationNotFoundError("Source not found.")
        resolved = _preview_conversation(user, course_id, material_id)
        if resolved is None:
            raise CitationNotFoundError("Source not found.")
        return resolved

    if material_id.startswith("ontrack-"):
        if material_type != "reference":
            raise CitationNotFoundError("Source not found.")
        label = material_id.removeprefix("ontrack-").replace("-", "_")
        resolved = _internal_citation(user, course_id, label, "", "")
        if resolved is None:
            raise CitationNotFoundError("Source not found.")
        return resolved

    rows = _material_rows(user, course_id)
    if material_type == "syllabus":
        resolved = _syllabus_citation(user, course_id, rows, "", "")
    elif material_type in {"notes", "slides"}:
        lecture_id = str(citation.get("lecture_id") or "")
        try:
            resolved = _notes_citation(user, course_id, rows, lecture_id, "", "") if lecture_id else None
        except storage.InvalidLectureIdError:
            resolved = None
        if resolved and citation.get("chunk_id"):
            note = storage.read_lecture(course_id, lecture_id, user)
            chunk = next((item for item in note.get("chunks", []) if item.get("id") == citation["chunk_id"]), None)
            if chunk is None:
                resolved = None
            else:
                resolved["chunk_id"] = chunk["id"]
                resolved["excerpt"] = _excerpt(chunk.get("text", ""))
                images = _chunk_images(user, course_id, lecture_id, chunk)
                if images:
                    resolved["images"] = images
                else:
                    resolved.pop("images", None)
    else:
        source_key = ""
        row = next((item for item in rows if str(item.material_id) == material_id), None)
        if row:
            source_key = row.source_key
        elif material_id.startswith("legacy-reference-"):
            source_key = material_id.removeprefix("legacy-reference-")
        try:
            resolved = _reference_citation(user, course_id, rows, source_key, "", "") if source_key else None
        except storage.InvalidReferenceIdError:
            resolved = None

    if (
        resolved is None
        or resolved["material_id"] != material_id
        or resolved["material_type"] != material_type
    ):
        raise CitationNotFoundError("Source not found.")
    return resolved


def preview_stored_source(user, course_id: str, request_data: dict) -> dict:
    """Resolve only a citation attached to the specified owned assistant message.

    Browser-provided source metadata is used solely as a stale-selection check;
    the preview itself is reconstructed from the saved citation.
    """
    session = sessions.get_session(course_id, str(request_data.get("session_id") or ""), user=user)
    if session is None:
        raise CitationNotFoundError("Source not found.")
    message_index = request_data.get("message_index")
    citation_index = request_data.get("citation_index")
    messages = session.get("messages", [])
    if not isinstance(message_index, int) or message_index >= len(messages):
        raise CitationNotFoundError("Source not found.")
    message = messages[message_index]
    sources = message.get("sources", []) if message.get("role") == "assistant" else []
    if not isinstance(citation_index, int) or citation_index >= len(sources):
        raise CitationNotFoundError("Source not found.")
    stored = sources[citation_index]
    if not isinstance(stored, dict):
        raise CitationNotFoundError("Source not found.")
    for field in ("material_id", "material_type", "lecture_id", "chunk_id", "url"):
        if (request_data.get(field) or None) != (stored.get(field) or None):
            raise CitationNotFoundError("Source not found.")
    return preview_source(user, course_id, stored)
