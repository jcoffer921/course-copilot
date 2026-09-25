from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agent.services import backups, operations, storage


class Command(BaseCommand):
    help = "Create a checksum-verified backup of SQLite and all private course files."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default=str(settings.BASE_DIR / "backups"))
        parser.add_argument("--keep", type=int, default=14)

    def handle(self, *args, **options):
        try:
            path = backups.create_backup(
                settings.DATABASES["default"]["NAME"], storage.COURSES_DIR,
                options["output_dir"], keep=options["keep"],
            )
        except backups.BackupError as exc:
            operations.record_heartbeat("backup", status="error", detail=type(exc).__name__)
            raise CommandError(str(exc)) from exc
        operations.record_heartbeat("backup", detail=path.name)
        self.stdout.write(self.style.SUCCESS(f"Backup created and verified: {path}"))
