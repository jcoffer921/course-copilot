from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agent.services import extract_figures, storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = (
        "Extract real diagrams/images from a lecture's PDF/PPTX and link them to "
        "notes/<lecture_id>.json chunks by page/slide proximity."
    )

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to the lecture's PDF or PPTX slide file")
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("lecture_id", help="Short lecture identifier, e.g. lecture05 — must already have notes/<lecture_id>.json")
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite an existing images/<lecture_id>/manifest.json without confirmation",
        )

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        source_path = Path(options["source"])

        try:
            plan = extract_figures.build_extraction_plan(
                options["course_id"], options["lecture_id"], source_path, owner,
            )
        except (
            extract_figures.SourceFileError,
            extract_figures.LectureNotFoundError,
            storage.InvalidCourseIdError,
            storage.InvalidLectureIdError,
            storage.ImageManifestStorageError,
        ) as e:
            raise CommandError(str(e))

        if not plan["images"]:
            self.stdout.write("No figures found: every candidate was filtered as decorative, or the source has no images.")

        embedded = sum(1 for image in plan["images"] if image["kind"] == "embedded")
        rasterized = sum(1 for image in plan["images"] if image["kind"] == "rasterized_page")
        linked = sum(1 for image in plan["images"] if image["chunk_ids"])
        self.stdout.write(
            f"Found {len(plan['images'])} figure(s): {embedded} embedded, {rasterized} rasterized page fallback. "
            f"{linked} proximity-linked to at least one chunk."
        )
        if plan["skipped_undecodable"]:
            self.stdout.write(self.style.WARNING(
                f"Skipped {plan['skipped_undecodable']} embedded image object(s) that couldn't be decoded."
            ))

        overwrite = plan["existing_manifest"] is not None
        if overwrite and not options["force"]:
            self.stdout.write(
                f"\ncourses/.../images/{options['lecture_id']}/manifest.json already exists "
                f"({len(plan['existing_manifest'])} figure(s) currently on disk) and will be replaced, "
                f"along with this lecture's chunk page/image_ids links."
            )
            confirm = input("\nOverwrite? [y/N]: ").strip().lower()
            if confirm != "y":
                self.stdout.write("Aborted. No file was written.")
                return

        try:
            result = extract_figures.commit_extraction_plan(plan, owner, overwrite=overwrite)
        except (FileExistsError, storage.ImageManifestStorageError) as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(
            f"Wrote {result['image_count']} figure(s) to images/{options['lecture_id']}/ "
            f"({result['linked_chunk_count']} chunk(s) now have image_ids)."
        ))
