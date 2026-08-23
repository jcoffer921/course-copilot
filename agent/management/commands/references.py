import asyncio
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services import references, storage


class Command(BaseCommand):
    help = "Ingest a reference document (PDF/TXT/MD) for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to reference file (PDF/TXT/MD)")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--title", dest="title", default=None, help="Reference title (defaults to the filename)")

    def handle(self, *args, **options):
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        try:
            data = asyncio.run(
                references.ingest_reference(
                    options["course_id"], source_path.read_bytes(), source_path.name, title=options["title"],
                )
            )
        except ValueError as e:
            raise CommandError(str(e))

        errors = storage.validate_reference(data)
        if errors:
            self.stdout.write(self.style.ERROR("Schema validation failed:"))
            for e in errors:
                self.stdout.write(f"  - {e}")
            raise CommandError("reference ingestion failed schema validation")

        out_path = storage.write_reference(options["course_id"], data["reference_id"], data)
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} (reference_id: {data['reference_id']})"))
