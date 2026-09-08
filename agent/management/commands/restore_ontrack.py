from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from agent.services import backups, storage


class Command(BaseCommand):
    help = "Restore SQLite and course files from a verified OnTrack backup."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        connections.close_all()
        try:
            result = backups.restore_backup(
                options["archive"], settings.DATABASES["default"]["NAME"],
                storage.COURSES_DIR, settings.BASE_DIR / "backups" / "recovery",
                confirmation=options["confirm"],
            )
        except backups.BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Restore complete. Previous data retained at {result['recovery_path']}"
        ))
