from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response

from .serializers import (
    AskRequestSerializer,
    ChunkNotesRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    RecordAttemptRequestSerializer,
)
from .services import chunk_notes, mastery, quiz, reminders, sessions, storage
from .services.ask import CourseNotFoundError, ask_async
from .services.syllabus_extraction import extract_syllabus_async, read_source_text_from_upload


class ExtractSyllabusView(APIView):
    """
    POST /api/courses/<course_id>/syllabus/extract/
    multipart/form-data: file=<syllabus pdf/txt/md>, course_name=<optional>, overwrite=<bool>

    Plan-then-pause: if syllabus.json already exists for this course_id and
    overwrite=false (default), returns 409 with a preview instead of writing.
    """

    async def post(self, request, course_id):
        serializer = ExtractSyllabusRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload = serializer.validated_data["file"]
        course_name_hint = serializer.validated_data.get("course_name")
        overwrite = serializer.validated_data.get("overwrite", False)

        try:
            existing = await sync_to_async(storage.read_syllabus)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.SyllabusStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if existing is not None and not overwrite:
            return Response(
                {
                    "detail": f"syllabus.json already exists for course '{course_id}'.",
                    "existing_preview": existing,
                    "resolution": "Resend the request with overwrite=true to replace it.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            text = read_source_text_from_upload(upload)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = await extract_syllabus_async(text, course_id, course_name_hint)
        except ValueError as e:
            return Response({"detail": f"extraction failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        errors = storage.validate_syllabus(data)
        blocking = [e for e in errors if not e.startswith("WARNING")]
        warnings = [e for e in errors if e.startswith("WARNING")]

        if blocking:
            return Response(
                {"detail": "extracted data failed schema validation", "errors": blocking, "raw": data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        await sync_to_async(storage.write_syllabus)(course_id, data, overwrite=True)

        return Response(
            {"course_id": course_id, "syllabus": data, "warnings": warnings},
            status=status.HTTP_201_CREATED,
        )


class ChunkNotesView(APIView):
    """
    POST /api/courses/<course_id>/notes/chunk/
    multipart/form-data: file=<notes PDF/TXT/MD or .pptx slide deck>,
    lecture_id=<str>, date=<optional YYYY-MM-DD>, overwrite=<bool>

    Plan-then-pause: if notes/<lecture_id>.json already exists and
    overwrite=false (default), returns 409 with a preview instead of writing.
    404 if no syllabus.json exists yet for course_id (topic reconciliation
    needs the course's official topics list).
    """

    async def post(self, request, course_id):
        serializer = ChunkNotesRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload = serializer.validated_data["file"]
        lecture_id = serializer.validated_data["lecture_id"]
        lecture_date = serializer.validated_data.get("date") or None
        overwrite = serializer.validated_data.get("overwrite", False)

        try:
            existing = await sync_to_async(storage.read_lecture)(course_id, lecture_id)
        except (storage.InvalidCourseIdError, storage.InvalidLectureIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.NotesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if existing is not None and not overwrite:
            return Response(
                {
                    "detail": f"notes/{lecture_id}.json already exists for course '{course_id}'.",
                    "existing_preview": existing,
                    "resolution": "Resend the request with overwrite=true to replace it.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            text, source_type = chunk_notes.read_source_from_upload(upload)
        except (ValueError, chunk_notes.MalformedSourceError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = await chunk_notes.chunk_notes_async(course_id, lecture_id, text, source_type, lecture_date)
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, chunk_notes.MalformedSourceError) as e:
            return Response({"detail": f"chunking failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        errors = storage.validate_notes(data)
        blocking = [e for e in errors if not e.startswith("WARNING")]
        warnings = [e for e in errors if e.startswith("WARNING")]

        if blocking:
            return Response(
                {"detail": "chunked data failed schema validation", "errors": blocking, "raw": data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        await sync_to_async(storage.write_notes)(course_id, lecture_id, data, overwrite=True)

        return Response(
            {"course_id": course_id, "notes": data, "warnings": warnings},
            status=status.HTTP_201_CREATED,
        )


class MasteryView(APIView):
    """GET /api/courses/<course_id>/mastery/ — topic scores, weakest-first.
    [] if mastery_scores.json hasn't been built yet (POST .../mastery/rebuild/ first)."""

    async def get(self, request, course_id):
        try:
            scores = await sync_to_async(mastery.weak_topics)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.QuizStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(scores, status=status.HTTP_200_OK)


class MasteryRebuildView(APIView):
    """POST /api/courses/<course_id>/mastery/rebuild/ — replays quiz_history.json
    into a fresh mastery_scores.json and returns it. Always safe to call —
    it's a pure rebuild of a derived view, never destructive to the event log."""

    async def post(self, request, course_id):
        try:
            data = await sync_to_async(mastery.rebuild_scores)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.QuizStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(data, status=status.HTTP_200_OK)


class QuizGenerateView(APIView):
    """
    POST /api/courses/<course_id>/quiz/generate/
    body: {"topic": "<optional>", "chunk_id": "<optional>"}

    Returns a question including "correct_answer" — the client is
    responsible for not revealing it to the user until they've answered,
    then resending the full question fields to /quiz/record/ to log the
    attempt (no server-side "pending question" state is kept between the
    two calls).

    404 if no syllabus.json for course_id; 422 if this course has no
    chunked notes yet (or none for the requested topic/chunk_id).
    """

    async def post(self, request, course_id):
        serializer = GenerateQuestionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data.get("topic")
        chunk_id = serializer.validated_data.get("chunk_id")

        try:
            q = await quiz.generate_question_async(course_id, topic=topic, chunk_id=chunk_id)
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except quiz.NoChunksAvailableError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ValueError as e:
            return Response({"detail": f"question generation failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(q, status=status.HTTP_200_OK)


class QuizRecordView(APIView):
    """
    POST /api/courses/<course_id>/quiz/record/
    body: {"lecture_id", "chunk_id", "topic", "question", "correct_answer", "user_answer"}

    Logs the attempt to quiz_history.json and immediately rebuilds
    mastery_scores.json from it. Returns {"correct": bool, "correct_answer": str}.
    """

    async def post(self, request, course_id):
        serializer = RecordAttemptRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        try:
            result = await sync_to_async(quiz.record_attempt)(
                course_id, d["lecture_id"], d["chunk_id"], d["topic"],
                d["question"], d["correct_answer"], d["user_answer"],
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class RemindersView(APIView):
    """
    GET /api/reminders/?within_days=<int>&course_id=<optional>
    Read-only deadline digest across all courses (default: next 14 days).
    No writes, no external side effects — distinct from calendar_sync.py,
    which actually commits specific events to Google Calendar.
    """

    async def get(self, request):
        raw_within_days = request.query_params.get("within_days")
        within_days = int(raw_within_days) if raw_within_days else 14
        course_id = request.query_params.get("course_id")
        course_ids = [course_id] if course_id else None

        deadlines = await sync_to_async(reminders.upcoming_deadlines)(
            within_days=within_days, course_ids=course_ids,
        )
        return Response(deadlines, status=status.HTTP_200_OK)


class SyllabusDetailView(APIView):
    """GET /api/courses/<course_id>/syllabus/ — returns the stored syllabus.json, or 404."""

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(storage.read_syllabus)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.SyllabusStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if data is None:
            return Response(
                {"detail": f"no syllabus.json found for course '{course_id}'"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(data)


class AskView(APIView):
    """
    POST /api/courses/<course_id>/ask/
    body: {"question": "...", "session_id": "<optional>"}

    If session_id is given, the question is answered with that session's
    prior turns as conversation history, and both the question and the
    answer are appended to it. Omit it for the original stateless behavior.

    404 if no syllabus.json exists yet for course_id, or if session_id is
    given but doesn't exist for that course. 400 if question is missing/blank.
    """

    async def post(self, request, course_id):
        serializer = AskRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        question = serializer.validated_data["question"]
        session_id = serializer.validated_data.get("session_id")

        try:
            result = await ask_async(course_id, question, session_id=session_id)
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except sessions.SessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.SyllabusStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except ValueError as e:
            return Response({"detail": f"ask failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_200_OK)


class SessionsView(APIView):
    """
    POST /api/courses/<course_id>/sessions/ — creates a new session, 201 with
    {"session_id", "created_at"}. 404 if no syllabus.json exists for course_id.

    GET /api/courses/<course_id>/sessions/ — 200 with a list of session
    summaries (session_id, created_at, updated_at, message_count).
    """

    async def post(self, request, course_id):
        try:
            session = await sync_to_async(sessions.create_session)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {"session_id": session["session_id"], "created_at": session["created_at"]},
            status=status.HTTP_201_CREATED,
        )

    async def get(self, request, course_id):
        try:
            summaries = await sync_to_async(sessions.list_sessions)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(summaries, status=status.HTTP_200_OK)


class SessionDetailView(APIView):
    """GET /api/courses/<course_id>/sessions/<session_id>/ — full session incl. messages, or 404."""

    async def get(self, request, course_id, session_id):
        try:
            session = await sync_to_async(sessions.get_session)(course_id, session_id)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if session is None:
            return Response(
                {"detail": f"no session '{session_id}' found for course '{course_id}'"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(session)
