import asyncio

from django.core.management.base import BaseCommand, CommandError

from agent.services import domain_suggestions, storage
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = "Suggest or approve trusted web-search domains for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--suggest", action="store_true",
            help="Ask Claude to propose candidate domains (read-only, nothing written)",
        )
        group.add_argument(
            "--approve", dest="approve", default=None,
            help="Comma-separated domains to write as this course's approved list",
        )

    def handle(self, *args, **options):
        course_id = options["course_id"]

        if options["suggest"]:
            self._suggest(course_id)
        else:
            self._approve(course_id, options["approve"])

    def _suggest(self, course_id):
        try:
            domains = asyncio.run(domain_suggestions.suggest_domains(course_id))
        except CourseNotFoundError as e:
            raise CommandError(str(e))
        except ValueError as e:
            raise CommandError(str(e))

        if not domains:
            self.stdout.write("No domains suggested.")
            return

        self.stdout.write("Suggested domains (not yet approved):")
        for d in domains:
            self.stdout.write(f"  - {d}")
        self.stdout.write(
            f"\nApprove with: python manage.py domains {course_id} --approve " + ",".join(domains)
        )

    def _approve(self, course_id, raw_domains):
        domains = [d.strip() for d in raw_domains.split(",") if d.strip()]
        errors = storage.validate_trusted_domains({"course_id": course_id, "domains": domains})

        if errors:
            self.stdout.write(self.style.ERROR("Validation failed:"))
            for e in errors:
                self.stdout.write(f"  - {e}")
            raise CommandError("invalid domain list")

        try:
            out_path = storage.write_trusted_domains(course_id, domains)
        except storage.InvalidCourseIdError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} with {len(domains)} approved domain(s)."))
