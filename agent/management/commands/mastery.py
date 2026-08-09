from django.core.management.base import BaseCommand, CommandError

from agent.services import mastery, storage


class Command(BaseCommand):
    help = "Rebuild or inspect topic mastery scores for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--rebuild", action="store_true",
            help="Rebuild mastery_scores.json from quiz_history.json",
        )
        group.add_argument(
            "--weak-topics", action="store_true",
            help="List this course's topics sorted weakest-first",
        )
        parser.add_argument("--limit", type=int, default=None, help="Limit --weak-topics output to N topics")

    def handle(self, *args, **options):
        course_id = options["course_id"]

        if options["rebuild"]:
            self._rebuild(course_id)
        else:
            self._weak_topics(course_id, options["limit"])

    def _rebuild(self, course_id):
        try:
            data = mastery.rebuild_scores(course_id)
        except storage.InvalidCourseIdError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(f"Rebuilt {len(data['scores'])} topic scores."))
        for s in data["scores"]:
            self.stdout.write(f"  {s['topic']}: {s['score']:.2f} ({s['status']}, {s['attempts']} attempts)")

    def _weak_topics(self, course_id, limit):
        try:
            scores = mastery.weak_topics(course_id, limit=limit)
        except storage.InvalidCourseIdError as e:
            raise CommandError(str(e))

        if not scores:
            self.stdout.write("No mastery scores yet — run --rebuild first (after some quiz attempts).")
            return

        for s in scores:
            self.stdout.write(
                f"{s['topic']}: {s['score']:.2f} ({s['status']}, {s['attempts']} attempts, "
                f"last seen {s['last_seen']})"
            )
