import asyncio
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services import storage
from agent.services.syllabus_extraction import MODEL, extract_syllabus_async, read_source_text_from_path


class Command(BaseCommand):
    help = "Extract syllabus.json from a local PDF/TXT/MD file (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to syllabus PDF, TXT, or MD file")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--course-name", dest="course_name", default=None, help="Hint for the course's full name")
        parser.add_argument("--force", action="store_true", help="Overwrite existing syllabus.json without confirmation")

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            text = read_source_text_from_path(source_path)
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(f"Extracted {len(text)} characters. Calling {MODEL}...")

        try:
            data = asyncio.run(
                extract_syllabus_async(text, options["course_id"], options["course_name"])
            )
        except ValueError as e:
            raise CommandError(str(e))

        errors = storage.validate_syllabus(data)
        blocking = [e for e in errors if not e.startswith("WARNING")]
        warnings = [e for e in errors if e.startswith("WARNING")]

        for w in warnings:
            self.stdout.write(self.style.WARNING(w))

        if blocking:
            self.stdout.write(self.style.ERROR("Schema validation failed:"))
            for e in blocking:
                self.stdout.write(f"  - {e}")
            self.stdout.write("\nNothing written. Raw extracted data:")
            self.stdout.write(json.dumps(data, indent=2))
            raise CommandError("extraction failed schema validation")

        self.stdout.write(
            f"  {len(data['dates'])} dates, {len(data['grading'])} grading components, "
            f"{len(data['topics'])} topics"
        )

        try:
            existing = storage.read_syllabus(options["course_id"])
        except (storage.SyllabusStorageError, storage.InvalidCourseIdError) as e:
            raise CommandError(str(e))

        if existing is not None and not options["force"]:
            self.stdout.write(f"\ncourses/{options['course_id']}/syllabus.json already exists.")
            self.stdout.write("Preview of new data:")
            self.stdout.write(json.dumps(data, indent=2)[:1000])
            confirm = input("\nOverwrite? [y/N]: ").strip().lower()
            if confirm != "y":
                self.stdout.write("Aborted. No file was written.")
                return

        out_path = storage.write_syllabus(options["course_id"], data, overwrite=True)
        self.stdout.write(self.style.SUCCESS(f"\nWrote {out_path}"))
