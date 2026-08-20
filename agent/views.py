from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response

from .serializers import (
    AddGradeItemRequestSerializer,
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    CalendarSyncRequestSerializer,
    ChunkNotesRequestSerializer,
    CreateCourseDraftRequestSerializer,
    ExtractSyllabusRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    RecordAttemptRequestSerializer,
    UpdateGradeItemRequestSerializer,
)
from .services import calendar_sync, chunk_notes, dashboard, domain_suggestions, grades, mastery, quiz, references, reminders, sessions, storage
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


class CourseView(APIView):
    """
    POST /api/courses/<course_id>/
    body: {"course_name": "..."}

    Creates a draft class — a name with no syllabus yet. 409 if course_id
    already exists as either a draft or a real (syllabus'd) course.

    PATCH /api/courses/<course_id>/
    body: {"course_name": "..."}

    Renames a draft or real course in place (course.json or syllabus.json,
    whichever exists). 404 if course_id doesn't exist as either.

    DELETE /api/courses/<course_id>/

    Deletes the course entirely — syllabus, notes, references, sessions,
    quiz history, mastery scores. Irreversible; the client is responsible
    for confirming with the user first (plan-then-pause per CLAUDE.md).
    404 if course_id doesn't exist as either a draft or a real course.
    """

    async def post(self, request, course_id):
        serializer = CreateCourseDraftRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        course_name = serializer.validated_data["course_name"]

        try:
            await sync_to_async(storage.write_course_draft)(course_id, course_name)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseAlreadyExistsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {"course_id": course_id, "course_name": course_name},
            status=status.HTTP_201_CREATED,
        )

    async def patch(self, request, course_id):
        serializer = CreateCourseDraftRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        course_name = serializer.validated_data["course_name"]

        try:
            await sync_to_async(storage.rename_course)(course_id, course_name)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"course_id": course_id, "course_name": course_name}, status=status.HTTP_200_OK)

    async def delete(self, request, course_id):
        try:
            await sync_to_async(storage.delete_course)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


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


class ReferencesView(APIView):
    """
    POST /api/courses/<course_id>/references/
    multipart/form-data: file=<reference pdf/txt/md>, title=<optional>

    No plan-then-pause here — reference_id is generated fresh from the title
    (or filename), with a numeric suffix on collision, so there's no
    existing file for this upload to overwrite the way syllabus/notes
    uploads can collide.

    GET /api/courses/<course_id>/references/ — list all references, [] if none.
    """

    async def post(self, request, course_id):
        serializer = IngestReferenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload = serializer.validated_data["file"]
        title = serializer.validated_data.get("title") or None

        try:
            data = await references.ingest_reference(course_id, upload.read(), upload.name, title=title)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        errors = storage.validate_reference(data)
        if errors:
            return Response(
                {"detail": "extracted data failed schema validation", "errors": errors, "raw": data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            await sync_to_async(storage.write_reference)(course_id, data["reference_id"], data)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"course_id": course_id, "reference": data},
            status=status.HTTP_201_CREATED,
        )

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(storage.read_references)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.ReferencesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"references": data}, status=status.HTTP_200_OK)


class DomainSuggestionsView(APIView):
    """
    POST /api/courses/<course_id>/domains/suggest/ — read-only. Asks Claude
    to propose candidate trusted domains from this course's syllabus. Never
    writes anything; the human approves (or hand-edits) the list via
    PUT /domains/ separately.
    """

    async def post(self, request, course_id):
        try:
            domains = await domain_suggestions.suggest_domains(course_id)
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"detail": f"suggestion failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"suggested": domains}, status=status.HTTP_200_OK)


class DomainsView(APIView):
    """
    GET /api/courses/<course_id>/domains/ — the current approved list, []
    if none approved yet.

    PUT /api/courses/<course_id>/domains/ — replace the approved list with
    the user's (possibly hand-edited) selection. body: {"domains": [...]}
    """

    async def get(self, request, course_id):
        try:
            domains = await sync_to_async(storage.read_trusted_domains)(course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.TrustedDomainsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"domains": domains}, status=status.HTTP_200_OK)

    async def put(self, request, course_id):
        serializer = ApproveDomainsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        domains = serializer.validated_data["domains"]
        errors = storage.validate_trusted_domains({"course_id": course_id, "domains": domains})
        if errors:
            return Response(
                {"detail": "invalid domain list", "errors": errors},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            await sync_to_async(storage.write_trusted_domains)(course_id, domains)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"course_id": course_id, "domains": domains}, status=status.HTTP_200_OK)


class GradingConfigView(APIView):
    """
    GET /api/courses/<course_id>/grading/ — the grading array plus the
    effective grade scale (the course's own, or the default one if it
    hasn't set one).

    PUT /api/courses/<course_id>/grading/
    body: {"grading": [{"component", "weight_pct", "total_items"?, "drop_lowest"?}, ...], "grade_scale"?: {...}}
    """

    async def get(self, request, course_id):
        syllabus = await sync_to_async(storage.read_syllabus)(course_id)
        if syllabus is None:
            return Response({"detail": f"no syllabus found for '{course_id}'"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "grading": syllabus.get("grading", []),
            "grade_scale": syllabus.get("grade_scale") or grades.DEFAULT_GRADE_SCALE,
            "category_choices": storage.GRADING_CATEGORY_CHOICES,
        }, status=status.HTTP_200_OK)

    async def put(self, request, course_id):
        serializer = GradingConfigRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        grading = serializer.validated_data["grading"]
        grade_scale = serializer.validated_data.get("grade_scale")
        errors = storage.validate_grading_config(grading, grade_scale)
        blocking = [e for e in errors if not e.startswith("WARNING")]
        warnings = [e for e in errors if e.startswith("WARNING")]

        if blocking:
            return Response({"detail": "invalid grading config", "errors": blocking}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        orphaned = await sync_to_async(grades.find_orphaned_components)(course_id, grading)
        warnings += [
            f"WARNING: '{c}' has entered grades that won't count toward your grade anymore — "
            f"no matching category in the new setup"
            for c in orphaned
        ]

        try:
            await sync_to_async(storage.write_grading_config)(course_id, grading, grade_scale)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {"grading": grading, "grade_scale": grade_scale or grades.DEFAULT_GRADE_SCALE, "warnings": warnings},
            status=status.HTTP_200_OK,
        )


class GradesView(APIView):
    """GET /api/courses/<course_id>/grades/ — every entered item plus the
    current grade breakdown (grades.current_grade()), which itself includes
    the effective grade_scale."""

    async def get(self, request, course_id):
        try:
            grade = await sync_to_async(grades.current_grade)(course_id)
            items = (await sync_to_async(storage.read_grades)(course_id))["items"]
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.GradesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"items": items, "grade": grade}, status=status.HTTP_200_OK)


class GradeItemsView(APIView):
    """POST /api/courses/<course_id>/grades/items/
    body: {"component", "title", "score", "max_points", "date"?}"""

    async def post(self, request, course_id):
        serializer = AddGradeItemRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data

        try:
            item = await sync_to_async(grades.add_item)(
                course_id, d["component"], d["title"], d["score"], d["max_points"], d.get("date"),
            )
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(item, status=status.HTTP_201_CREATED)


class GradeItemDetailView(APIView):
    """PATCH /api/courses/<course_id>/grades/items/<item_id>/ — partial update.
    DELETE /api/courses/<course_id>/grades/items/<item_id>/"""

    async def patch(self, request, course_id, item_id):
        serializer = UpdateGradeItemRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        fields = {k: v for k, v in serializer.validated_data.items() if v is not None}

        try:
            item = await sync_to_async(grades.update_item)(course_id, item_id, **fields)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(item, status=status.HTTP_200_OK)

    async def delete(self, request, course_id, item_id):
        try:
            await sync_to_async(grades.delete_item)(course_id, item_id)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


class GradesWhatIfView(APIView):
    """GET /api/courses/<course_id>/grades/whatif/?target=<pct>"""

    async def get(self, request, course_id):
        target_raw = request.query_params.get("target")
        try:
            target_pct = float(target_raw)
        except (TypeError, ValueError):
            return Response({"detail": "query param 'target' must be a number"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            needed = await sync_to_async(grades.grade_needed)(course_id, target_pct)
            missable = await sync_to_async(grades.missable_by_category)(course_id, target_pct)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"grade_needed": needed, "missable_by_category": missable}, status=status.HTTP_200_OK)


class GradesSummaryView(APIView):
    """GET /api/grades/summary/ — all-courses rollup."""

    async def get(self, request):
        data = await sync_to_async(grades.all_courses_summary)()
        return Response(data, status=status.HTTP_200_OK)


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


class QuizHistoryView(APIView):
    """
    GET /api/courses/<course_id>/quiz/history/?limit=<int, default 10>
    Most recent quiz attempts for this course, newest first.
    """

    async def get(self, request, course_id):
        raw_limit = request.query_params.get("limit")
        limit = int(raw_limit) if raw_limit else 10

        try:
            attempts = await sync_to_async(quiz.recent_attempts)(course_id, limit=limit)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"attempts": attempts}, status=status.HTTP_200_OK)


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


class DashboardView(APIView):
    """
    GET /api/dashboard/
    Cross-course summary for the Dashboard tab: upcoming deadlines (14-day
    window) plus, per course, topics/quizzed counts, next deadline
    (uncapped), grading, and weak topics. Always 200 — a corrupt course's
    data is isolated to its own {"error": ...} slot by build_dashboard(),
    never fails the whole response.
    """

    async def get(self, request):
        data = await sync_to_async(dashboard.build_dashboard)()
        return Response(data, status=status.HTTP_200_OK)


class CalendarSyncView(APIView):
    """
    POST /api/courses/<course_id>/calendar-sync/
    body: {"date": "YYYY-MM-DD", "title": "...", "type": "exam|assignment|reading|other"}

    Pushes one deadline into the signed-in user's real Google Calendar as
    an all-day event. 409 if that (date, title) was already synced; 502 if
    the user's stored Google credentials can't be refreshed.
    """

    async def post(self, request, course_id):
        serializer = CalendarSyncRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = await sync_to_async(calendar_sync.add_deadline_to_calendar)(
                request.user, course_id,
                serializer.validated_data["date"],
                serializer.validated_data["title"],
                serializer.validated_data["type"],
            )
        except calendar_sync.AlreadySyncedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except calendar_sync.CalendarAuthError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_201_CREATED)


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
        except (storage.SyllabusStorageError, storage.NotesStorageError,
                storage.ReferencesStorageError, storage.TrustedDomainsStorageError) as e:
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


@login_required
def ontrack_page(request):
    """GET / — serves the OnTrack UI mockup (DC pseudo-component app).

    Plain sync Django view, not a DRF/adrf endpoint: it does no I/O, just
    renders a template. The template's DC bindings use the same `{{ }}`
    syntax as Django's own template language, so the whole app body is
    wrapped in `{% verbatim %}` in ontrack.html to keep Django from
    trying to resolve them itself.
    """
    return render(request, "agent/ontrack.html")
