import asyncio

from django.core.management.base import BaseCommand, CommandError

from agent.services import sessions
from agent.services.ask import CourseNotFoundError, ask_async
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Ask a grounded question about a course's syllabus/notes (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("question", help="Question to ask about the course")
        parser.add_argument(
            "--session", dest="session_id", default=None,
            help="Existing session_id to continue a multi-turn conversation. "
                 "Must already exist — create one first with `manage.py sessions <course_id> --create`.",
        )

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        try:
            result = asyncio.run(
                ask_async(options["course_id"], options["question"], session_id=options["session_id"], user=owner)
            )
        except CourseNotFoundError as e:
            raise CommandError(str(e))
        except sessions.SessionNotFoundError as e:
            raise CommandError(
                f"{e}. Create one first with: "
                f"python manage.py sessions {options['course_id']} --create"
            )
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(result["answer"])
        self.stdout.write("")
        if result["grounded"]:
            # result["sources"] holds resolved structured citations (dicts), not
            # the model's raw string labels, by the time ask_async returns.
            sources = result["sources"]
            labels = ", ".join(source.get("title") or source.get("material_id", "") for source in sources) or "none"
            self.stdout.write(self.style.SUCCESS(f"grounded: true (sources: {labels})"))
            for source in sources:
                for image in source.get("images", []):
                    self.stdout.write(f"  figure: {image['path']}")
        else:
            self.stdout.write(self.style.WARNING("grounded: false — not covered by this course's materials"))
