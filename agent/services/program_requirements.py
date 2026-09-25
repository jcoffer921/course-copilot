"""
Confirm/store layer for faculty-reviewed program requirements. Import (the
extraction call) never touches the database — see requirements_extraction.py.
This module owns the one place a ProgramRequirement row gets written, so the
collision/overwrite rule lives in exactly one spot.
"""

from django.db import transaction

from .requirements_extraction import MalformedRequirementsSourceError, _normalize_extracted_requirements
from ..models import ProgramRequirement


class ProgramRequirementConflictError(Exception):
    """Raised when (user, program_name, catalog_year) already has a
    confirmed row and the caller didn't pass overwrite=True."""

    def __init__(self, existing: ProgramRequirement):
        self.existing = existing
        super().__init__("A program requirement with this name and catalog year already exists.")


def serialize(row: ProgramRequirement) -> dict:
    return {
        "requirement_id": str(row.requirement_id),
        "program_name": row.program_name,
        "catalog_year": row.catalog_year,
        "requirements": row.requirements,
        "source_filename": row.source_filename,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_summary(row: ProgramRequirement) -> dict:
    """Enough for the client to show "you're about to overwrite X" — not
    the full requirements payload."""
    category_count = len(row.requirements.get("categories") or [])
    course_count = sum(len(c.get("courses") or []) for c in row.requirements.get("categories") or [])
    return {
        "requirement_id": str(row.requirement_id),
        "program_name": row.program_name,
        "catalog_year": row.catalog_year,
        "category_count": category_count,
        "course_count": course_count,
        "updated_at": row.updated_at.isoformat(),
    }


def confirm_requirements(user, data: dict, overwrite: bool, source_filename: str = "") -> tuple[ProgramRequirement, bool]:
    """Validates `data` against the Task 2 schema, then creates or updates
    the matching ProgramRequirement row. Raises ProgramRequirementConflictError
    when a row already exists and overwrite is False; raises
    MalformedRequirementsSourceError if `data` doesn't match the schema.

    Returns (row, created)."""
    normalized = _normalize_extracted_requirements(data)

    with transaction.atomic():
        existing = ProgramRequirement.objects.select_for_update().filter(
            user=user,
            program_name=normalized["program_name"],
            catalog_year=normalized["catalog_year"],
        ).first()

        if existing is not None and not overwrite:
            raise ProgramRequirementConflictError(existing)

        if existing is not None:
            existing.requirements = normalized
            existing.source_filename = source_filename
            existing.save(update_fields=["requirements", "source_filename", "updated_at"])
            return existing, False

        created = ProgramRequirement.objects.create(
            user=user,
            program_name=normalized["program_name"],
            catalog_year=normalized["catalog_year"],
            requirements=normalized,
            source_filename=source_filename,
        )
        return created, True
