import asyncio

from django.core.management.base import BaseCommand, CommandError

from agent.services import quiz
from agent.services.cli_owner import resolve_owner_user
from agent.services.storage import CourseNotFoundError


class Command(BaseCommand):
    help = (
        "Generate one quiz question from a course's chunked notes, prompt for an "
        "answer, and record the attempt (standalone, no server needed)."
    )

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        parser.add_argument("--topic", default=None, help="Quiz on a specific topic (default: biased toward the weakest topic)")
        parser.add_argument("--chunk-id", dest="chunk_id", default=None, help="Quiz on a specific chunk by id")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        course_id = options["course_id"]

        try:
            q = asyncio.run(
                quiz.generate_question_async(course_id, topic=options["topic"], chunk_id=options["chunk_id"], user=owner)
            )
        except CourseNotFoundError as e:
            raise CommandError(str(e))
        except (quiz.NoChunksAvailableError, ValueError) as e:
            raise CommandError(str(e))

        self.stdout.write(f"[{q['topic']}] ({q['lecture_id']} / {q['chunk_id']})")
        self.stdout.write(q["question"])
        for i, choice in enumerate(q["choices"], start=1):
            self.stdout.write(f"  {i}. {choice}")

        raw = input("\nYour answer [1-4]: ").strip()
        try:
            user_answer = q["choices"][int(raw) - 1]
        except (ValueError, IndexError):
            raise CommandError(f"'{raw}' isn't a valid choice — enter a number 1-{len(q['choices'])}")

        result = quiz.record_attempt(
            course_id, q["lecture_id"], q["chunk_id"], q["topic"],
            q["question"], q["correct_answer"], user_answer, user=owner,
        )

        if result["correct"]:
            self.stdout.write(self.style.SUCCESS("Correct!"))
        else:
            self.stdout.write(self.style.ERROR(f"Incorrect. Correct answer: {result['correct_answer']}"))
