import json

from django.core.management.base import BaseCommand, CommandError

from agent.services import grades, storage
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = "Add, list, configure grading categories for, or run what-if projections against a course's grades (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument(
            "--set-grading", dest="set_grading", default=None, metavar="JSON_FILE",
            help='Replace this course\'s grading categories from a JSON file, e.g. '
                 '{"grading": [{"component": "Homework", "weight_pct": 40, "total_items": 5, "drop_lowest": 1}], '
                 '"grade_scale": {"passing_pct": 60, "cutoffs": [...]}}',
        )
        parser.add_argument(
            "--add", nargs=4, metavar=("COMPONENT", "TITLE", "SCORE", "MAX_POINTS"),
            help="Add a grade item, e.g. --add Homework \"HW 3\" 92 100",
        )
        parser.add_argument("--date", default=None, help="Date for --add, YYYY-MM-DD")
        parser.add_argument("--list", action="store_true", help="List entered items and the current grade")
        parser.add_argument(
            "--whatif", type=float, default=None, metavar="TARGET_PCT",
            help="Show the score needed on remaining work, and per-category missable counts, to hit TARGET_PCT",
        )

    def handle(self, *args, **options):
        course_id = options["course_id"]

        if options["set_grading"]:
            with open(options["set_grading"], "r", encoding="utf-8") as f:
                payload = json.load(f)
            grading = payload.get("grading", [])
            grade_scale = payload.get("grade_scale")

            errors = storage.validate_grading_config(grading, grade_scale)
            blocking = [e for e in errors if not e.startswith("WARNING")]
            if blocking:
                raise CommandError("invalid grading config: " + "; ".join(blocking))
            for w in errors:
                if w.startswith("WARNING"):
                    self.stdout.write(self.style.WARNING(w))

            try:
                storage.write_grading_config(course_id, grading, grade_scale)
            except CourseNotFoundError as e:
                raise CommandError(str(e))
            self.stdout.write(self.style.SUCCESS(f"Updated grading config for '{course_id}'."))
            return

        if options["add"]:
            component, title, score, max_points = options["add"]
            try:
                item = grades.add_item(course_id, component, title, float(score), float(max_points), options["date"])
            except (CourseNotFoundError, ValueError) as e:
                raise CommandError(str(e))
            self.stdout.write(self.style.SUCCESS(
                f"Added {item['title']} ({item['component']}): {item['score']}/{item['max_points']}"
            ))
            return

        if options["list"]:
            try:
                grade = grades.current_grade(course_id)
            except CourseNotFoundError as e:
                raise CommandError(str(e))
            for item in storage.read_grades(course_id)["items"]:
                self.stdout.write(f"  [{item['component']}] {item['title']}: {item['score']}/{item['max_points']}")
            overall = grade["overall_pct"]
            self.stdout.write(self.style.SUCCESS(
                f"Overall: {overall}% ({grade['letter']})" if overall is not None else "Overall: no grades entered yet"
            ))
            return

        if options["whatif"] is not None:
            try:
                needed = grades.grade_needed(course_id, options["whatif"])
                missable = grades.missable_by_category(course_id, options["whatif"])
            except CourseNotFoundError as e:
                raise CommandError(str(e))

            if needed["locked"]:
                self.stdout.write(f"Grade is locked at {needed['ceiling_pct']}% — nothing left to change.")
            elif needed["achievable"]:
                self.stdout.write(f"You need to average {needed['p_needed']}% on everything remaining to hit {options['whatif']}%.")
            else:
                self.stdout.write(f"Not achievable: would need {needed['p_needed']}% (max possible is {needed['ceiling_pct']}%).")
            for note in needed["notes"]:
                self.stdout.write(self.style.WARNING(note))
            for m in missable:
                if m["omitted_reason"]:
                    continue
                self.stdout.write(f"  {m['component']}: can miss {m['missable']} of {m['remaining']} remaining")
            return

        raise CommandError("specify --set-grading, --add, --list, or --whatif")
