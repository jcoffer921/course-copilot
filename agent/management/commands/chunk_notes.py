import asyncio
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from agent.services import material_files, materials, storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Process lecture material (PDF/PPTX/DOCX/TXT/MD) into notes/<lecture_id>.json."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to lecture PDF, PPTX, DOCX, TXT, or MD file")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("lecture_id", help="Short lecture identifier, e.g. lecture05")
        parser.add_argument("--date", dest="date", default=None, help="Lecture date, YYYY-MM-DD")
        parser.add_argument("--force", action="store_true", help="Overwrite existing notes/<lecture_id>.json without confirmation")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            existing = storage.read_lecture(options["course_id"], options["lecture_id"], owner)
        except (storage.NotesStorageError, storage.InvalidCourseIdError, storage.InvalidLectureIdError) as e:
            raise CommandError(str(e))

        if existing is not None and not options["force"]:
            self.stdout.write(f"\ncourses/{options['course_id']}/notes/{options['lecture_id']}.json already exists.")
            confirm = input("\nOverwrite? [y/N]: ").strip().lower()
            if confirm != "y":
                self.stdout.write("Aborted. No file was written.")
                return

        self.stdout.write("Validating upload and processing grounded chunks...")
        try:
            with source_path.open("rb") as handle:
                material = asyncio.run(
                    materials.process_notes(
                        owner,
                        options["course_id"],
                        File(handle, name=source_path.name),
                        options["lecture_id"],
                        options["date"],
                        overwrite=existing is not None,
                    )
                )
        except (
            material_files.UploadValidationError,
            storage.CourseNotFoundError,
            storage.InvalidCourseIdError,
            storage.InvalidLectureIdError,
        ) as e:
            raise CommandError(str(e))
        except materials.MaterialProcessingError as e:
            raise CommandError(e.public_message)

        data = storage.read_lecture(options["course_id"], options["lecture_id"], owner)
        self.stdout.write(f"  {len(data['chunks'])} chunks, topics: {', '.join(data['topics']) or '(none)'}")
        self.stdout.write(self.style.SUCCESS(f"Ready (material {material.material_id})"))
