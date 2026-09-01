from django.core.management.base import BaseCommand, CommandError

from agent.services import pilot_checks


class Command(BaseCommand):
    help = "Check OnTrack's database, migrations, storage, integrations, URL, and latest backup."

    def add_arguments(self, parser):
        parser.add_argument("--live-smtp", action="store_true", help="Authenticate to SMTP without sending email.")
        parser.add_argument("--live-ai", action="store_true", help="Make one tiny Anthropic connectivity request.")
        parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")

    def handle(self, *args, **options):
        results = pilot_checks.run(live_smtp=options["live_smtp"], live_ai=options["live_ai"])
        for result in results:
            style = self.style.SUCCESS if result["status"] == "ok" else self.style.WARNING if result["status"] == "warning" else self.style.ERROR
            self.stdout.write(style(f"{result['status'].upper():7} {result['name']}: {result['detail']}"))
        failing = [row for row in results if row["status"] == "error" or (options["strict"] and row["status"] == "warning")]
        if failing:
            raise CommandError(f"{len(failing)} pilot check(s) failed.")
