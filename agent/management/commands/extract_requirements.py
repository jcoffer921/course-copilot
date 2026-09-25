import asyncio
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services.cli_owner import resolve_owner_user
from agent.services.requirements_extraction import (
    MODEL,
    MalformedRequirementsSourceError,
    extract_requirements_async,
)


class Command(BaseCommand):
    help = "Extract program requirements from a local .xlsx file and print the JSON. Never writes to the database."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to a program-requirements .xlsx file")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        source_path = Path(options["source"])
        if not source_path.exists():
            raise CommandError(f"source file not found: {source_path}")

        self.stdout.write(f"Calling {MODEL}...")
        try:
            data = asyncio.run(
                extract_requirements_async(source_path.read_bytes(), source_path.name, owner)
            )
        except MalformedRequirementsSourceError as e:
            raise CommandError(str(e))

        course_count = sum(len(c["courses"]) for c in data["categories"])
        self.stdout.write(
            f"Extracted: {data['program_name'] or '(no name)'} / {data['catalog_year'] or '(no year)'}, "
            f"{len(data['categories'])} categories, {course_count} courses"
        )
        self.stdout.write(json.dumps(data, indent=2))
