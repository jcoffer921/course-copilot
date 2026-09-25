"""
Extracts real diagrams/images already present in a course's lecture PDFs or
slide decks and links each one to the note chunk(s) it most likely
illustrates, by page/slide proximity. Never generates or fabricates an
image — every PNG this writes is either an embedded image object pulled
straight out of the source file, or (PDF only) a full-page rasterization of
a page that has no embedded image object at all, for vector-drawn diagrams.

KNOWN v1 LIMITATIONS (read before trusting this blindly):
- Proximity chunk-linking is a heuristic, not ground truth. Chunks don't
  carry a source page number today (chunk_notes.py's LLM chunking pass never
  looks at page boundaries), so this module independently re-extracts
  per-page/per-slide text from the same source file and assigns each chunk
  to whichever page shares the most 3+ character word tokens with the
  chunk's own text (see `_resolve_chunk_pages`). A page covering several
  distinct topics can mislink an image to the wrong chunk, or to a chunk
  that only shares vocabulary with the image's real page. The matching is
  deterministic (ties always go to the lowest page number) but not accurate
  in the way a human review would be.
- A vision-based captioning pass — actually looking at each extracted image
  to verify/describe what it shows, rather than trusting page-adjacency — is
  a planned follow-up, not implemented here. This module never calls a
  vision or image-generation model; it only extracts and re-encodes bytes
  that were already real image objects (or already-rendered page content) in
  the source file.
- PPTX rasterization fallback (for a vector-drawn diagram on a slide with no
  embedded picture shape) is NOT implemented — there's no dependency-free way
  to render a slide to a bitmap in pure Python the way PyMuPDF renders a PDF
  page. Such slides simply contribute no extracted image, same as if nothing
  were there. PDF's fallback (`page.get_pixmap`) has no such gap.
"""

import re
from pathlib import Path

import pymupdf
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from . import storage
from .chunk_notes import _extract_slides_from_bytes

# Below this width AND height (in pixels), an embedded image is treated as
# decorative (a logo, an icon, a header/footer rule) rather than a real
# figure — checked against the image's actual decoded pixel dimensions, not
# its on-page display size. A full-page rasterization fallback is exempt:
# a whole rendered page is never "decorative junk" by this measure.
MIN_IMAGE_DIMENSION_PX = 120

# DPI used for the PDF full-page rasterization fallback. High enough to keep
# a vector diagram legible, low enough to keep output file size reasonable.
RASTER_DPI = 150

# 3+ character word tokens only — short connector words ("a", "to", "is")
# would otherwise dominate the overlap score without carrying real topical
# signal. Mirrors citations.py's own word-overlap heuristic (`_terms`), kept
# independent here rather than importing a private helper across modules.
_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")


class SourceFileError(Exception):
    """Raised when the source PDF/PPTX is missing, unreadable, or an
    unsupported file type — never silently returns an empty result."""


class LectureNotFoundError(Exception):
    """Raised when notes/<lecture_id>.json doesn't exist yet for this
    course — figures link to chunks, so chunk_notes must run first."""


def _tokenize(text: str) -> set:
    return {word.lower() for word in _WORD_RE.findall(text or "")}


def _resolve_chunk_pages(chunks: list, page_texts: dict) -> dict:
    """Best-effort, deterministic proximity match: for each chunk, pick the
    source page/slide whose text shares the most word tokens with the
    chunk's own text. Ties go to the lowest page number. A chunk with zero
    token overlap against every page is left unresolved (no guess) — see
    this module's docstring for why this is a known-imprecise v1 heuristic.
    Returns {chunk_id: page_number} for only the chunks that resolved."""
    page_tokens = {page: _tokenize(text) for page, text in page_texts.items()}
    resolved = {}
    for chunk in chunks:
        chunk_tokens = _tokenize(chunk.get("text", ""))
        if not chunk_tokens:
            continue
        best_page, best_score = None, 0
        for page in sorted(page_tokens):
            score = len(chunk_tokens & page_tokens[page])
            if score > best_score:
                best_page, best_score = page, score
        if best_page is not None:
            resolved[chunk["id"]] = best_page
    return resolved


def _normalize_to_png(raw_bytes: bytes):
    """Re-encodes arbitrary embedded-image bytes (jpeg/gif/bmp/etc.) as PNG
    so every written figure has a consistent, predictable extension,
    matching the images/<lecture_id>/<image_id>.png output contract. Returns
    None (caller skips the candidate) if the bytes can't be decoded as an
    image at all — a corrupt embedded image object is dropped, not
    fabricated as a blank placeholder."""
    try:
        return pymupdf.Pixmap(raw_bytes).tobytes("png")
    except Exception:
        return None


# --------------------------------------------------------------------------
# PDF extraction (PyMuPDF): embedded images + full-page rasterization
# fallback for pages with no embedded image object at all.
# --------------------------------------------------------------------------

def _extract_pdf(path: Path):
    """Returns (candidates, page_texts). candidates is a list of
    {"page", "bytes", "width", "height", "kind"} dicts, not yet size-filtered
    or PNG-normalized. page_texts maps 1-based page number -> page text, used
    for proximity chunk-linking."""
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise SourceFileError(f"couldn't read PDF '{path}': {e}") from e

    if doc.is_encrypted:
        doc.close()
        raise SourceFileError(f"PDF '{path}' is encrypted/password-protected — can't extract figures")

    candidates = []
    page_texts = {}
    seen_xrefs = set()
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_number = page_index + 1
            page_texts[page_number] = page.get_text()

            page_has_embedded_image = False
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                page_has_embedded_image = True  # true even if we already extracted this xref elsewhere
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue
                candidates.append({
                    "page": page_number,
                    "bytes": extracted["image"],
                    "width": extracted["width"],
                    "height": extracted["height"],
                    "kind": "embedded",
                })

            if not page_has_embedded_image:
                pixmap = page.get_pixmap(dpi=RASTER_DPI)
                candidates.append({
                    "page": page_number,
                    "bytes": pixmap.tobytes("png"),
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "kind": "rasterized_page",
                })
    finally:
        doc.close()

    return candidates, page_texts


# --------------------------------------------------------------------------
# PPTX extraction (python-pptx): embedded picture shapes only — see the
# module docstring for why there's no rasterization fallback here.
# --------------------------------------------------------------------------

def _iter_picture_shapes(shapes):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            yield shape
        elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_picture_shapes(shape.shapes)


def _extract_pptx(path: Path):
    """Returns (candidates, page_texts) — "page" here means 1-based slide
    number. Reuses chunk_notes.py's own slide-text extraction (imported, not
    duplicated) so proximity matching sees exactly the same per-slide text
    chunk_notes.py chunked from, without modifying that file."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise SourceFileError(f"couldn't read '{path}': {e}") from e

    try:
        prs = Presentation(path)
    except Exception as e:
        raise SourceFileError(f"couldn't read .pptx file '{path}': {e}") from e

    try:
        slides = _extract_slides_from_bytes(data)
    except Exception:
        slides = []

    candidates = []
    for slide_index, slide in enumerate(prs.slides, start=1):
        for shape in _iter_picture_shapes(slide.shapes):
            try:
                image = shape.image
            except Exception:
                continue
            width, height = image.size
            candidates.append({
                "page": slide_index,
                "bytes": image.blob,
                "width": width,
                "height": height,
                "kind": "embedded",
            })

    page_texts = {
        slide_number: f"{slide_data['title']}\n{slide_data['body']}"
        for slide_number, slide_data in enumerate(slides, start=1)
    }
    return candidates, page_texts


def _filter_junk(candidates: list) -> list:
    """Drops small embedded images (logos/icons/decorative headers) below
    MIN_IMAGE_DIMENSION_PX on either side. Full-page rasterizations are
    exempt — a rendered page is never decorative junk by this measure."""
    kept = []
    for candidate in candidates:
        if candidate["kind"] == "embedded" and (
            candidate["width"] < MIN_IMAGE_DIMENSION_PX or candidate["height"] < MIN_IMAGE_DIMENSION_PX
        ):
            continue
        kept.append(candidate)
    return kept


# --------------------------------------------------------------------------
# Plan / commit — split so the CLI (and any future caller) can show exactly
# what would change and pause for confirmation before writing anything,
# per CLAUDE.md's plan-then-pause rule for destructive/bulk writes.
# --------------------------------------------------------------------------

def build_extraction_plan(course_id: str, lecture_id: str, source_path: Path, user) -> dict:
    """Extracts and proximity-links figures entirely in memory — no disk
    writes. Raises SourceFileError if source_path is missing/unreadable/an
    unsupported type, and LectureNotFoundError if this lecture's notes don't
    exist yet (figures link to chunks that must already exist)."""
    source_path = Path(source_path)
    if not source_path.exists() or not source_path.is_file():
        raise SourceFileError(f"source file not found: {source_path}")

    suffix = source_path.suffix.lower()
    if suffix not in (".pdf", ".pptx"):
        raise SourceFileError(f"unsupported source type '{suffix}' — use .pdf or .pptx")

    lecture = storage.read_lecture(course_id, lecture_id, user)
    if lecture is None:
        raise LectureNotFoundError(
            f"no notes/{lecture_id}.json found for course '{course_id}' — "
            f"run chunk_notes for this lecture before extracting figures"
        )

    if suffix == ".pdf":
        raw_candidates, page_texts = _extract_pdf(source_path)
    else:
        raw_candidates, page_texts = _extract_pptx(source_path)

    kept_candidates = _filter_junk(raw_candidates)
    chunks = lecture.get("chunks", [])
    resolved_pages = _resolve_chunk_pages(chunks, page_texts)

    images = []
    skipped_undecodable = 0
    per_page_seq = {}
    for candidate in kept_candidates:
        page = candidate["page"]
        png_bytes = _normalize_to_png(candidate["bytes"])
        if png_bytes is None:
            skipped_undecodable += 1
            continue
        seq = per_page_seq.get(page, 0) + 1
        per_page_seq[page] = seq
        chunk_ids = [
            chunk["id"] for chunk in chunks
            if resolved_pages.get(chunk["id"]) == page
        ]
        images.append({
            "image_id": f"p{page:03d}-{seq:02d}",
            "source_page": page,
            "chunk_ids": chunk_ids,
            "match_method": "proximity",
            "kind": candidate["kind"],
            "png_bytes": png_bytes,
        })

    return {
        "course_id": course_id,
        "lecture_id": lecture_id,
        "images": images,
        "resolved_pages": resolved_pages,
        "skipped_undecodable": skipped_undecodable,
        "existing_manifest": storage.read_image_manifest(course_id, lecture_id, user),
    }


def commit_extraction_plan(plan: dict, user, overwrite: bool = False) -> dict:
    """Writes an in-memory plan to disk: every PNG, images/<lecture_id>/manifest.json,
    and an additive update to notes/<lecture_id>.json's chunks (only "page"
    and "image_ids" — every other chunk field is left exactly as-is). Raises
    FileExistsError if a manifest already exists for this lecture and
    overwrite=False — callers own the plan-then-pause confirmation step."""
    course_id, lecture_id = plan["course_id"], plan["lecture_id"]

    manifest_entries = [
        {
            "image_id": image["image_id"],
            "source_page": image["source_page"],
            "chunk_ids": image["chunk_ids"],
            "match_method": image["match_method"],
        }
        for image in plan["images"]
    ]
    errors = storage.validate_image_manifest(manifest_entries)
    if errors:
        raise storage.ImageManifestStorageError(f"extracted manifest failed validation: {errors}")

    if plan["existing_manifest"] is not None:
        if not overwrite:
            raise FileExistsError(
                f"images/{lecture_id}/manifest.json already exists for '{course_id}'"
            )
        storage.delete_lecture_images(course_id, lecture_id, user)

    for image in plan["images"]:
        storage.write_lecture_image(
            course_id, lecture_id, image["image_id"], image["png_bytes"], user, overwrite=True,
        )
    storage.write_image_manifest(course_id, lecture_id, manifest_entries, user, overwrite=True)

    lecture = storage.read_lecture(course_id, lecture_id, user)
    chunk_images = {}
    for image in plan["images"]:
        for chunk_id in image["chunk_ids"]:
            chunk_images.setdefault(chunk_id, []).append(image["image_id"])

    updated_chunks = []
    for chunk in lecture["chunks"]:
        chunk = dict(chunk)
        page = plan["resolved_pages"].get(chunk["id"])
        if page is not None:
            chunk["page"] = page
        image_ids = chunk_images.get(chunk["id"])
        if image_ids:
            chunk["image_ids"] = image_ids
        updated_chunks.append(chunk)
    lecture = dict(lecture)
    lecture["chunks"] = updated_chunks
    storage.write_notes(course_id, lecture_id, lecture, user, overwrite=True)

    return {
        "image_count": len(plan["images"]),
        "embedded_count": sum(1 for image in plan["images"] if image["kind"] == "embedded"),
        "rasterized_count": sum(1 for image in plan["images"] if image["kind"] == "rasterized_page"),
        "linked_chunk_count": len(chunk_images),
        "skipped_undecodable": plan["skipped_undecodable"],
    }


def extract_figures_for_lecture(course_id: str, lecture_id: str, source_path: Path, user, overwrite: bool = False) -> dict:
    """Convenience wrapper: build then commit in one call. The CLI command
    calls build_extraction_plan/commit_extraction_plan directly instead, so
    it can show a summary and pause for confirmation between the two steps."""
    plan = build_extraction_plan(course_id, lecture_id, source_path, user)
    return commit_extraction_plan(plan, user, overwrite=overwrite)
