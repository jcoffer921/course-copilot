import asyncio
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from agent.services import material_files, materials, storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Ingest a reference document (PDF/PPTX/DOCX/TXT/MD) for a course."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to reference PDF, PPTX, DOCX, TXT, or MD file")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--title", dest="title", default=None, help="Reference title (defaults to the filename)")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            with source_path.open("rb") as handle:
                material = asyncio.run(
                    materials.process_reference(
                        owner,
                        options["course_id"],
                        File(handle, name=source_path.name),
                        title=options["title"],
                    )
                )
        except (material_files.UploadValidationError, storage.CourseNotFoundError, storage.InvalidCourseIdError) as e:
            raise CommandError(str(e))
        except materials.MaterialProcessingError as e:
            raise CommandError(e.public_message)

        self.stdout.write(self.style.SUCCESS(f"Ready (reference_id: {material.source_key})"))
