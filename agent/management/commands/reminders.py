from django.core.management.base import BaseCommand

from agent.services import reminders
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Read-only deadline digest across all courses (no writes, no external calls)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--within-days", type=int, default=14,
            help="Only show deadlines in the next N days (default 14)",
        )
        parser.add_argument("--course-id", dest="course_id", default=None, help="Limit to one course")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        course_ids = [options["course_id"]] if options["course_id"] else None
        deadlines = reminders.upcoming_deadlines(owner, within_days=options["within_days"], course_ids=course_ids)

        if not deadlines:
            self.stdout.write("No upcoming deadlines found.")
            return

        for d in deadlines:
            self.stdout.write(f"{d['date']}  [{d['course_id']}]  {d['title']}  ({d['type']})")
