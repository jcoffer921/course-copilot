import asyncio
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services import chunk_notes, storage
from agent.services.cli_owner import resolve_owner_user
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = "Chunk a lecture's notes (PDF/TXT/MD) or slide deck (.pptx) into notes/<lecture_id>.json."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to notes file (PDF/TXT/MD) or slide deck (.pptx)")
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
            text, source_type = chunk_notes.read_source_from_path(source_path)
        except (ValueError, chunk_notes.MalformedSourceError) as e:
            raise CommandError(str(e))

        self.stdout.write(f"Extracted {len(text)} characters from a {source_type} source. Calling Claude...")

        try:
            data = asyncio.run(
                chunk_notes.chunk_notes_async(
                    options["course_id"], options["lecture_id"], text, source_type, options["date"], user=owner,
                )
            )
        except CourseNotFoundError as e:
            raise CommandError(str(e))
        except (ValueError, chunk_notes.MalformedSourceError) as e:
            raise CommandError(str(e))

        errors = storage.validate_notes(data)
        blocking = [e for e in errors if not e.startswith("WARNING")]
        warnings = [e for e in errors if e.startswith("WARNING")]

        for w in warnings:
            self.stdout.write(self.style.WARNING(w))

        if blocking:
            self.stdout.write(self.style.ERROR("Schema validation failed:"))
            for e in blocking:
                self.stdout.write(f"  - {e}")
            self.stdout.write("\nNothing written. Raw chunked data:")
            self.stdout.write(json.dumps(data, indent=2))
            raise CommandError("chunking failed schema validation")

        self.stdout.write(f"  {len(data['chunks'])} chunks, topics: {', '.join(data['topics']) or '(none)'}")

        try:
            existing = storage.read_lecture(options["course_id"], options["lecture_id"], owner)
        except (storage.NotesStorageError, storage.InvalidCourseIdError, storage.InvalidLectureIdError) as e:
            raise CommandError(str(e))

        if existing is not None and not options["force"]:
            self.stdout.write(f"\ncourses/{options['course_id']}/notes/{options['lecture_id']}.json already exists.")
            self.stdout.write("Preview of new data:")
            self.stdout.write(json.dumps(data, indent=2)[:1000])
            confirm = input("\nOverwrite? [y/N]: ").strip().lower()
            if confirm != "y":
                self.stdout.write("Aborted. No file was written.")
                return

        out_path = storage.write_notes(options["course_id"], options["lecture_id"], data, owner, overwrite=True)
        self.stdout.write(self.style.SUCCESS(f"\nWrote {out_path}"))
