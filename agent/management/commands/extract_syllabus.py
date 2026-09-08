import asyncio
import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from agent.services import material_files, materials, storage
from agent.services.cli_owner import resolve_owner_user
from agent.services.syllabus_extraction import MODEL


class Command(BaseCommand):
    help = "Stage and confirm a syllabus from a local PDF/PPTX/DOCX/TXT/MD file."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to syllabus PDF, PPTX, DOCX, TXT, or MD file")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--course-name", dest="course_name", default=None, help="Hint for the course's full name")
        parser.add_argument("--force", action="store_true", help="Overwrite existing syllabus.json without confirmation")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            existing = storage.read_syllabus(options["course_id"], owner)
        except (storage.SyllabusStorageError, storage.InvalidCourseIdError) as e:
            raise CommandError(str(e))
        if not storage.course_or_draft_exists(options["course_id"], owner):
            try:
                storage.write_course_draft(
                    options["course_id"], options["course_name"] or options["course_id"], owner
                )
            except storage.InvalidCourseIdError as e:
                raise CommandError(str(e))

        self.stdout.write(f"Validating upload and calling {MODEL}...")
        try:
            with source_path.open("rb") as handle:
                material = asyncio.run(
                    materials.stage_syllabus(
                        owner,
                        options["course_id"],
                        File(handle, name=source_path.name),
                        options["course_name"],
                    )
                )
        except (material_files.UploadValidationError, storage.InvalidCourseIdError) as e:
            raise CommandError(str(e))
        except materials.MaterialProcessingError as e:
            raise CommandError(e.public_message)

        data = material.extracted_data
        self.stdout.write(
            f"Review candidate: {len(data['dates'])} dates, {len(data['grading'])} grading components, "
            f"{len(data['topics'])} topics"
        )
        self.stdout.write(json.dumps(data, indent=2))
        if not options["force"]:
            prompt = "Replace the current confirmed syllabus? [y/N]: " if existing is not None else "Confirm this syllabus? [y/N]: "
            if input(prompt).strip().lower() != "y":
                self.stdout.write("Not confirmed. The trusted syllabus was not changed; the candidate remains pending review.")
                return

        materials.confirm_syllabus(owner, options["course_id"], material.material_id, data)
        self.stdout.write(self.style.SUCCESS("Confirmed syllabus.json"))
