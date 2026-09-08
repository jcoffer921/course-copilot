"""Owned course-material lifecycle over operational DB metadata and JSON content."""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from asgiref.sync import sync_to_async
from anthropic import AuthenticationError
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from agent.models import CourseMaterial

from . import chunk_notes, material_files, references, storage
from .syllabus_extraction import extract_syllabus_async, extract_text_from_bytes


DEFAULT_PROCESSING_TIMEOUT_SECONDS = 90
DEFAULT_MAX_UPLOAD_BYTES_PER_USER = 200 * 1024 * 1024
_API_AUTH_MESSAGE = 'Anthropic rejected the configured API key. Update ANTHROPIC_API_KEY in .env, then restart OnTrack.'


class MaterialNotFoundError(Exception):
    pass


class MaterialConflictError(Exception):
    def __init__(self, message, existing_preview=None):
        super().__init__(message)
        self.existing_preview = existing_preview


@dataclass
class MaterialProcessingError(Exception):
    material: CourseMaterial
    code: str
    public_message: str
    http_status: int = 422

    def __str__(self):
        return self.public_message


def _processing_timeout() -> int:
    try:
        return max(1, int(os.environ.get("ONTRACK_MATERIAL_PROCESSING_TIMEOUT_SECONDS", DEFAULT_PROCESSING_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_PROCESSING_TIMEOUT_SECONDS


def _serialize(material: CourseMaterial, *, include_candidate=False) -> dict:
    data = {
        "material_id": str(material.material_id),
        "course_id": material.course_id,
        "original_filename": material.original_filename,
        "material_type": material.material_type,
        "source_key": material.source_key or None,
        "source_date": material.source_date,
        "uploaded_at": material.uploaded_at.isoformat(),
        "processing_status": material.processing_status,
        "review_status": material.review_status,
        "failure_code": material.failure_code or None,
        "failure_message": material.failure_message or None,
        "size_bytes": material.size_bytes,
        "confirmed_at": material.confirmed_at.isoformat() if material.confirmed_at else None,
        "legacy": False,
    }
    if include_candidate and material.processing_status == CourseMaterial.STATUS_NEEDS_REVIEW:
        data["candidate"] = material.extracted_data
    return data


def serialize_material(material: CourseMaterial, *, include_candidate=False) -> dict:
    return _serialize(material, include_candidate=include_candidate)


def _get_owned(user, course_id: str, material_id) -> CourseMaterial:
    storage._validate_course_id(course_id)
    try:
        return CourseMaterial.objects.get(user=user, course_id=course_id, material_id=material_id)
    except (CourseMaterial.DoesNotExist, ValueError, ValidationError) as exc:
        raise MaterialNotFoundError("Material not found.") from exc


def get_material(user, course_id: str, material_id) -> dict:
    return _serialize(_get_owned(user, course_id, material_id), include_candidate=True)


def _legacy_materials(user, course_id: str, represented: set[tuple[str, str]]) -> list[dict]:
    legacy = []
    syllabus = storage.read_syllabus(course_id, user)
    if syllabus is not None and (CourseMaterial.TYPE_SYLLABUS, "syllabus") not in represented:
        legacy.append({
            "material_id": "legacy-syllabus",
            "course_id": course_id,
            "original_filename": "Existing syllabus",
            "material_type": CourseMaterial.TYPE_SYLLABUS,
            "source_key": "syllabus",
            "source_date": None,
            "uploaded_at": None,
            "processing_status": CourseMaterial.STATUS_READY,
            "review_status": CourseMaterial.REVIEW_CONFIRMED,
            "failure_code": None,
            "failure_message": None,
            "size_bytes": None,
            "confirmed_at": None,
            "legacy": True,
        })
    for note in storage.read_notes(course_id, user):
        key = str(note.get("lecture_id") or "notes")
        kind = CourseMaterial.TYPE_SLIDES if note.get("source") == "slides" else CourseMaterial.TYPE_NOTES
        if (kind, key) in represented:
            continue
        legacy.append({
            "material_id": f"legacy-{kind}-{key}", "course_id": course_id,
            "original_filename": key, "material_type": kind, "source_key": key,
            "source_date": note.get("date"), "uploaded_at": None,
            "processing_status": CourseMaterial.STATUS_READY,
            "review_status": CourseMaterial.REVIEW_NOT_REQUIRED,
            "failure_code": None, "failure_message": None, "size_bytes": None,
            "confirmed_at": None, "legacy": True,
        })
    for reference in storage.read_references(course_id, user):
        key = str(reference.get("reference_id") or "reference")
        if (CourseMaterial.TYPE_REFERENCE, key) in represented:
            continue
        legacy.append({
            "material_id": f"legacy-reference-{key}", "course_id": course_id,
            "original_filename": reference.get("source_filename") or reference.get("title") or key,
            "material_type": CourseMaterial.TYPE_REFERENCE, "source_key": key,
            "source_date": None, "uploaded_at": None,
            "processing_status": CourseMaterial.STATUS_READY,
            "review_status": CourseMaterial.REVIEW_NOT_REQUIRED,
            "failure_code": None, "failure_message": None, "size_bytes": None,
            "confirmed_at": None, "legacy": True,
        })
    return legacy


def list_materials(user, course_id: str) -> list[dict]:
    storage._validate_course_id(course_id)
    rows = list(CourseMaterial.objects.filter(user=user, course_id=course_id).order_by("-uploaded_at"))
    represented = {
        (row.material_type, row.source_key or "syllabus")
        for row in rows
        if row.processing_status == CourseMaterial.STATUS_READY
    }
    return [_serialize(row) for row in rows] + _legacy_materials(user, course_id, represented)


def _quota_limit_bytes() -> int:
    try:
        return max(1, int(os.environ.get("ONTRACK_MAX_UPLOAD_BYTES_PER_USER", DEFAULT_MAX_UPLOAD_BYTES_PER_USER)))
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES_PER_USER


def _create_record(user, course_id: str, prepared, material_type: str, *, source_key="", source_date=None):
    storage._validate_course_id(course_id)
    if not storage.course_or_draft_exists(course_id, user):
        raise storage.CourseNotFoundError(f"no course '{course_id}' found")
    # The aggregate-then-create pair is wrapped in one transaction so a
    # concurrent upload can't both pass the check before either commits.
    # This relies on SQLite's whole-database write lock during an open
    # transaction (the same soft guarantee confirm_syllabus/commit_notes
    # already lean on below) — a future Postgres migration would need a
    # real per-user counter row instead.
    with transaction.atomic():
        current_total = CourseMaterial.objects.filter(user=user).aggregate(total=Sum("size_bytes"))["total"] or 0
        limit = _quota_limit_bytes()
        if current_total + prepared.size_bytes > limit:
            raise material_files.UploadValidationError(
                "storage_quota_exceeded",
                f"This upload would exceed your {limit // (1024 * 1024)} MB storage limit.",
            )
        storage_key = material_files.object_storage.save(user, course_id, prepared.suffix, prepared.data)
        try:
            return CourseMaterial.objects.create(
                user=user,
                course_id=course_id,
                original_filename=prepared.display_filename,
                material_type=material_type,
                source_key=source_key,
                source_date=source_date,
                storage_key=storage_key,
                size_bytes=prepared.size_bytes,
                content_type=prepared.content_type,
            )
        except Exception:
            material_files.object_storage.delete(user, course_id, storage_key)
            raise


def _mark_processing(material):
    material.processing_status = CourseMaterial.STATUS_PROCESSING
    material.failure_code = ""
    material.failure_message = ""
    material.save(update_fields=["processing_status", "failure_code", "failure_message", "updated_at"])


def _mark_failed(material, code: str, message: str):
    material.processing_status = CourseMaterial.STATUS_FAILED
    material.failure_code = code
    material.failure_message = message
    material.save(update_fields=["processing_status", "failure_code", "failure_message", "updated_at"])


async def _fail(material, code, message, http_status=422):
    await sync_to_async(_mark_failed)(material, code, message)
    await sync_to_async(material.refresh_from_db)()
    raise MaterialProcessingError(material, code, message, http_status)


def _llm_failure_details(exc: Exception, default_code: str, default_message: str):
    '''Return an actionable error without exposing the provider exception.'''
    missing_key = isinstance(exc, ValueError) and 'ANTHROPIC_API_KEY' in str(exc)
    if isinstance(exc, AuthenticationError) or missing_key:
        return 'api_authentication_failed', _API_AUTH_MESSAGE, 503
    return default_code, default_message, 422


async def _run_syllabus_extraction(material, data: bytes, filename: str, course_id: str, course_name_hint=None) -> CourseMaterial:
    timeout = _processing_timeout()
    try:
        source_text = await asyncio.wait_for(
            sync_to_async(extract_text_from_bytes, thread_sensitive=False)(data, filename),
            timeout,
        )
        candidate = await asyncio.wait_for(extract_syllabus_async(source_text, course_id, course_name_hint), timeout)
    except asyncio.TimeoutError:
        await _fail(material, "processing_timeout", "Processing took too long. Try a smaller or simpler document.", 504)
    except Exception as exc:
        await _fail(material, *_llm_failure_details(
            exc, "extraction_failed", "OnTrack could not safely extract this syllabus."
        ))

    errors = storage.validate_syllabus(candidate)
    blocking = [error for error in errors if not error.startswith("WARNING")]
    if blocking:
        await _fail(material, "invalid_extraction", "The extracted syllabus failed validation and was not saved.", 422)

    def mark_review():
        material.processing_status = CourseMaterial.STATUS_NEEDS_REVIEW
        material.review_status = CourseMaterial.REVIEW_PENDING
        material.extracted_data = candidate
        material.save(update_fields=["processing_status", "review_status", "extracted_data", "updated_at"])

    await sync_to_async(mark_review)()
    await sync_to_async(material.refresh_from_db)()
    return material


async def stage_syllabus(user, course_id: str, upload, course_name_hint=None) -> CourseMaterial:
    prepared = await sync_to_async(material_files.prepare_upload)(upload)
    material = await sync_to_async(_create_record)(user, course_id, prepared, CourseMaterial.TYPE_SYLLABUS, source_key="syllabus")
    await sync_to_async(_mark_processing)(material)
    return await _run_syllabus_extraction(material, prepared.data, prepared.display_filename, course_id, course_name_hint)


def confirm_syllabus(user, course_id: str, material_id, candidate: dict) -> CourseMaterial:
    storage._validate_course_id(course_id)
    if not isinstance(candidate, dict) or candidate.get("course_id") != course_id:
        raise ValueError("Reviewed syllabus course_id must match the course URL.")
    blocking = [error for error in storage.validate_syllabus(candidate) if not error.startswith("WARNING")]
    if blocking:
        raise ValueError("Reviewed syllabus failed validation: " + "; ".join(blocking))

    with transaction.atomic():
        syllabus_materials = list(CourseMaterial.objects.select_for_update().filter(
            user=user,
            course_id=course_id,
            material_type=CourseMaterial.TYPE_SYLLABUS,
        ))
        material = next((row for row in syllabus_materials if str(row.material_id) == str(material_id)), None)
        if material is None:
            raise MaterialNotFoundError("Material not found.")
        if (
            material.processing_status == CourseMaterial.STATUS_READY
            and material.review_status == CourseMaterial.REVIEW_CONFIRMED
            and material.extracted_data == candidate
            and storage.read_syllabus(course_id, user) == candidate
        ):
            return material
        if material.processing_status != CourseMaterial.STATUS_NEEDS_REVIEW:
            raise MaterialConflictError("This material is not awaiting syllabus review.")

        previous = storage.read_syllabus(course_id, user)
        storage.write_syllabus(course_id, candidate, user, overwrite=True)
        try:
            CourseMaterial.objects.filter(
                user=user,
                course_id=course_id,
                material_type=CourseMaterial.TYPE_SYLLABUS,
                review_status=CourseMaterial.REVIEW_CONFIRMED,
            ).exclude(pk=material.pk).update(review_status=CourseMaterial.REVIEW_SUPERSEDED)
            material.processing_status = CourseMaterial.STATUS_READY
            material.review_status = CourseMaterial.REVIEW_CONFIRMED
            material.extracted_data = candidate
            material.confirmed_at = timezone.now()
            material.failure_code = ""
            material.failure_message = ""
            material.save()
        except Exception:
            if previous is None:
                storage.delete_syllabus_preserving_course(course_id, user)
            else:
                storage.write_syllabus(course_id, previous, user, overwrite=True)
            raise
    return material


async def _run_notes_extraction(
    material, data: bytes, filename: str, user, course_id: str, lecture_id: str, source_date, *, overwrite: bool,
) -> CourseMaterial:
    timeout = _processing_timeout()
    try:
        source_text, source_type = await asyncio.wait_for(
            sync_to_async(chunk_notes.extract_text_from_source, thread_sensitive=False)(data, filename),
            timeout,
        )
        chunked = await asyncio.wait_for(
            chunk_notes.chunk_notes_async(course_id, lecture_id, source_text, source_type, source_date, user=user),
            timeout,
        )
    except asyncio.TimeoutError:
        await _fail(material, "processing_timeout", "Processing took too long. Try a smaller or simpler document.", 504)
    except Exception as exc:
        await _fail(material, *_llm_failure_details(
            exc, "chunking_failed", "OnTrack could not safely process this lecture material."
        ))

    blocking = [error for error in storage.validate_notes(chunked) if not error.startswith("WARNING")]
    if blocking:
        await _fail(material, "invalid_extraction", "The processed notes failed validation and were not saved.", 422)
    def commit_notes():
        with transaction.atomic():
            list(CourseMaterial.objects.select_for_update().filter(
                user=user,
                course_id=course_id,
                material_type__in=[CourseMaterial.TYPE_NOTES, CourseMaterial.TYPE_SLIDES],
                source_key=lecture_id,
            ))
            previous = storage.read_lecture(course_id, lecture_id, user)
            storage.write_notes(course_id, lecture_id, chunked, user, overwrite=overwrite)
            try:
                CourseMaterial.objects.filter(
                    user=user,
                    course_id=course_id,
                    material_type__in=[CourseMaterial.TYPE_NOTES, CourseMaterial.TYPE_SLIDES],
                    source_key=lecture_id,
                    processing_status=CourseMaterial.STATUS_READY,
                ).exclude(pk=material.pk).update(review_status=CourseMaterial.REVIEW_SUPERSEDED)
                material.processing_status = CourseMaterial.STATUS_READY
                material.review_status = CourseMaterial.REVIEW_NOT_REQUIRED
                material.extracted_data = None
                material.save(update_fields=["processing_status", "review_status", "extracted_data", "updated_at"])
            except Exception:
                if previous is None:
                    storage.delete_lecture(course_id, lecture_id, user)
                else:
                    storage.write_notes(course_id, lecture_id, previous, user, overwrite=True)
                raise

    try:
        await sync_to_async(commit_notes)()
    except FileExistsError:
        await _fail(material, "write_conflict", "Another upload created this lecture while processing. Review it before replacing anything.", 409)
    await sync_to_async(material.refresh_from_db)()
    return material


async def process_notes(user, course_id: str, upload, lecture_id: str, source_date=None, *, overwrite=False) -> CourseMaterial:
    try:
        existing = await sync_to_async(storage.read_lecture)(course_id, lecture_id, user)
    except storage.InvalidLectureIdError:
        raise
    if existing is not None and not overwrite:
        raise MaterialConflictError("A lecture with this ID already exists.", existing)
    if await sync_to_async(storage.read_syllabus)(course_id, user) is None:
        raise storage.CourseNotFoundError(f"no syllabus.json found for course '{course_id}'")

    prepared = await sync_to_async(material_files.prepare_upload)(upload)
    material_type = CourseMaterial.TYPE_SLIDES if prepared.suffix == ".pptx" else CourseMaterial.TYPE_NOTES
    material = await sync_to_async(_create_record)(
        user, course_id, prepared, material_type, source_key=lecture_id, source_date=source_date,
    )
    await sync_to_async(_mark_processing)(material)
    return await _run_notes_extraction(
        material, prepared.data, prepared.display_filename, user, course_id, lecture_id, source_date, overwrite=overwrite,
    )


async def _run_reference_extraction(material, data: bytes, filename: str, course_id: str, user, *, title=None) -> CourseMaterial:
    try:
        reference = await asyncio.wait_for(
            references.ingest_reference(course_id, data, filename, user, title=title),
            _processing_timeout(),
        )
    except asyncio.TimeoutError:
        await _fail(material, "processing_timeout", "Processing took too long. Try a smaller document.", 504)
    except Exception:
        await _fail(material, "reference_failed", "OnTrack could not safely process this reference.", 422)
    errors = storage.validate_reference(reference)
    if errors:
        await _fail(material, "invalid_extraction", "The processed reference failed validation and was not saved.", 422)
    await sync_to_async(storage.write_reference)(course_id, reference["reference_id"], reference, user, overwrite=False)

    def mark_ready():
        material.source_key = reference["reference_id"]
        material.processing_status = CourseMaterial.STATUS_READY
        material.review_status = CourseMaterial.REVIEW_NOT_REQUIRED
        material.save(update_fields=["source_key", "processing_status", "review_status", "updated_at"])

    await sync_to_async(mark_ready)()
    await sync_to_async(material.refresh_from_db)()
    return material


async def process_reference(user, course_id: str, upload, *, title=None) -> CourseMaterial:
    prepared = await sync_to_async(material_files.prepare_upload)(upload)
    material = await sync_to_async(_create_record)(user, course_id, prepared, CourseMaterial.TYPE_REFERENCE)
    await sync_to_async(_mark_processing)(material)
    return await _run_reference_extraction(material, prepared.data, prepared.display_filename, course_id, user, title=title)


def delete_material(user, course_id: str, material_id, confirmation: str) -> None:
    if confirmation != "DELETE":
        raise ValueError('Type "DELETE" to confirm material deletion.')
    material = _get_owned(user, course_id, material_id)
    if material.processing_status == CourseMaterial.STATUS_READY:
        if material.material_type == CourseMaterial.TYPE_SYLLABUS and material.review_status == CourseMaterial.REVIEW_CONFIRMED:
            storage.delete_syllabus_preserving_course(course_id, user)
        elif (
            material.material_type in {CourseMaterial.TYPE_NOTES, CourseMaterial.TYPE_SLIDES}
            and material.source_key
            and material.review_status != CourseMaterial.REVIEW_SUPERSEDED
        ):
            storage.delete_lecture(course_id, material.source_key, user)
        elif material.material_type == CourseMaterial.TYPE_REFERENCE and material.source_key:
            storage.delete_reference(course_id, material.source_key, user)
    material_files.object_storage.delete(user, course_id, material.storage_key)
    material.delete()


async def retry_material(user, course_id: str, material_id) -> CourseMaterial:
    """Re-run processing on an already-failed material's stored file in
    place, without a new upload or a new CourseMaterial row."""
    material = await sync_to_async(_get_owned)(user, course_id, material_id)
    if material.processing_status != CourseMaterial.STATUS_FAILED:
        raise MaterialConflictError("This material is not in a failed state.")
    # FileNotFoundError deliberately propagates uncaught here: the DB row
    # exists and is owned, but its stored file is gone, which is a server-
    # side integrity fault (500), not a client-facing 404/409.
    data = await sync_to_async(material_files.object_storage.read)(user, course_id, material.storage_key)
    filename = material.original_filename
    await sync_to_async(_mark_processing)(material)
    if material.material_type == CourseMaterial.TYPE_SYLLABUS:
        return await _run_syllabus_extraction(material, data, filename, course_id)
    if material.material_type in (CourseMaterial.TYPE_NOTES, CourseMaterial.TYPE_SLIDES):
        # Always overwrite: a failed row's stored bytes were never actually
        # committed to notes/<lecture_id>.json (extraction/validation failed
        # before that point), so there's nothing of this row's own to
        # collide with. If the row was originally a "replace" upload, the
        # user's overwrite intent isn't persisted on the model — forcing
        # True on retry honors that common case; the narrow risk (an
        # unrelated newer upload claimed the same lecture_id in the
        # meantime) is an acceptable trade explicitly noted here.
        return await _run_notes_extraction(
            material, data, filename, user, course_id, material.source_key, material.source_date, overwrite=True,
        )
    if material.material_type == CourseMaterial.TYPE_REFERENCE:
        return await _run_reference_extraction(material, data, filename, course_id, user)
    raise MaterialConflictError("This material type cannot be retried.")


def read_material_bytes(user, course_id: str, material_id) -> tuple[CourseMaterial, bytes]:
    material = _get_owned(user, course_id, material_id)
    # FileNotFoundError deliberately propagates uncaught: the row is owned
    # and exists, but a missing stored file is a server-side integrity
    # fault (500), not a client-facing 404.
    data = material_files.object_storage.read(user, course_id, material.storage_key)
    return material, data
