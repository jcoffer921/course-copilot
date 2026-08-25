from django.core.management.base import BaseCommand, CommandError

from agent.services import sessions, storage
from agent.services.cli_owner import resolve_owner_user


class Command(BaseCommand):
    help = "Create, list, or inspect grounded Q&A sessions for a course (standalone, no server needed)."

    def add_arguments(self, parser):
        parser.add_argument("course_id", help="Short course identifier, e.g. cs101")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--create", action="store_true",
            help="Create a new session and print its session_id (use with `ask --session <id>`)",
        )
        group.add_argument("--list", action="store_true", help="List sessions for this course")
        group.add_argument("--show", metavar="SESSION_ID", help="Show a session's full message history")

    def handle(self, *args, **options):
        owner = resolve_owner_user()
        course_id = options["course_id"]

        if options["create"]:
            self._create(course_id, owner)
        elif options["list"]:
            self._list(course_id, owner)
        else:
            self._show(course_id, options["show"], owner)

    def _create(self, course_id, owner):
        try:
            session = sessions.create_session(course_id, user=owner)
        except (storage.CourseNotFoundError, storage.InvalidCourseIdError) as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(f"Created session {session['session_id']}"))
        self.stdout.write(f"Continue it with: python manage.py ask {course_id} \"<question>\" --session {session['session_id']}")

    def _list(self, course_id, owner):
        try:
            summaries = sessions.list_sessions(course_id, user=owner)
        except (storage.InvalidCourseIdError, sessions.SessionStorageError) as e:
            raise CommandError(str(e))

        if not summaries:
            self.stdout.write("No sessions found.")
            return

        for s in summaries:
            self.stdout.write(
                f"{s['session_id']}  created={s['created_at']}  updated={s['updated_at']}  "
                f"messages={s['message_count']}"
            )

    def _show(self, course_id, session_id, owner):
        try:
            session = sessions.get_session(course_id, session_id, user=owner)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError, sessions.SessionStorageError) as e:
            raise CommandError(str(e))

        if session is None:
            raise CommandError(f"no session '{session_id}' found for course '{course_id}'")

        if not session["messages"]:
            self.stdout.write("(no messages yet)")
            return

        for m in session["messages"]:
            self.stdout.write(f"[{m['timestamp']}] {m['role']}: {m['content']}")
            if m["role"] == "assistant":
                sources = ", ".join(m.get("sources", [])) or "none"
                self.stdout.write(f"    grounded={m.get('grounded')} sources={sources}")
