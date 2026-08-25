"""One-time migration: moves each existing flat courses/<course_id>/
directory (from before storage became user-scoped) into
courses/<owner.pk>/<course_id>/. Safe to re-run — already-migrated or
non-course entries are skipped, not errored on. Dry-run by default; pass
--apply to actually move directories."""

from django.core.management.base import BaseCommand

from agent.services import storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Moves existing flat courses/<course_id>/ directories under courses/<owner.pk>/<course_id>/."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually move directories (default: dry-run preview only).")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        courses_dir = storage.COURSES_DIR
        if not courses_dir.exists():
            self.stdout.write("courses/ does not exist yet — nothing to migrate.")
            return

        owner_dir = courses_dir / str(owner.pk)
        to_move = []
        for entry in sorted(courses_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                self.stdout.write(f"skip (not a directory): {entry.name}")
                continue
            if entry == owner_dir or entry.name.isdigit():
                self.stdout.write(f"skip (already looks migrated): {entry.name}")
                continue
            if not (entry / "syllabus.json").exists() and not (entry / "course.json").exists():
                self.stdout.write(f"skip (not a course directory): {entry.name}")
                continue
            to_move.append(entry)

        if not to_move:
            self.stdout.write(self.style.SUCCESS("Nothing to migrate."))
            return

        for entry in to_move:
            destination = owner_dir / entry.name
            if options["apply"]:
                owner_dir.mkdir(parents=True, exist_ok=True)
                entry.rename(destination)
                self.stdout.write(self.style.SUCCESS(f"moved {entry.name} -> {destination}"))
            else:
                self.stdout.write(f"would move: {entry.name} -> {destination}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nDry run only — re-run with --apply to actually move these directories."))
