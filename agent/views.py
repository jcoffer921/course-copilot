import logging
from datetime import datetime, timedelta, timezone

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.db.utils import DatabaseError
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.response import Response

from .serializers import (
    AddGradeItemRequestSerializer,
    AccountDeleteSerializer,
    ApproveDomainsRequestSerializer,
    AskRequestSerializer,
    CalendarSyncRequestSerializer,
    CitationPreviewSerializer,
    ChunkNotesRequestSerializer,
    ConfirmDeadlineActionsRequestSerializer,
    CourseDeleteSerializer,
    CourseArchiveSerializer,
    CreateCourseDraftRequestSerializer,
    CreateCustomEventRequestSerializer,
    DismissRecommendationRequestSerializer,
    ExtractSyllabusRequestSerializer,
    FlashcardProgressResetSerializer,
    FlashcardProgressUpdateSerializer,
    FlashcardReviewRequestSerializer,
    FlashcardSuspendRequestSerializer,
    GenerateFlashcardsRequestSerializer,
    GenerateQuestionRequestSerializer,
    GradingConfigRequestSerializer,
    IngestReferenceRequestSerializer,
    MaterialDeleteSerializer,
    NotificationReadSerializer,
    NavigateInteractiveFlashcardRequestSerializer,
    RecordAttemptRequestSerializer,
    RecordStudyActivityRequestSerializer,
    RateInteractiveFlashcardRequestSerializer,
    SavedSiteRequestSerializer,
    SessionDeleteSerializer,
    SessionRenameSerializer,
    StartStudySessionRequestSerializer,
    StartPracticeAttemptRequestSerializer,
    SyllabusReviewSerializer,
    UpdateCustomEventRequestSerializer,
    UpdateCourseRequestSerializer,
    UpdateExamPlanRequestSerializer,
    UpdatePracticeAttemptRequestSerializer,
    UpdateGradeItemRequestSerializer,
    UserProfileUpdateSerializer,
)
from .services import accounts, calendar_events, calendar_sync, citations, course_catalog, course_overview, custom_events, dashboard, domain_suggestions, exams, grades, interactive_study, mastery, material_files, materials, notifications, quiz, recommendations, reminders, sessions, storage, study_sessions
from .services.ask import CourseNotFoundError, ask_async, confirm_deadline_actions

logger = logging.getLogger(__name__)


def _positive_int_query_param(request, name: str, default: int):
    raw_value = request.query_params.get(name)
    if raw_value in (None, ""):
        return default, None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, f"{name} must be an integer"
    if value < 1:
        return None, f"{name} must be greater than 0"
    return value, None


def _display_name_for(user):
    if user.get_full_name().strip():
        return user.get_full_name().strip()
    if user.first_name.strip():
        return user.first_name.strip()
    if user.email:
        return user.email.split("@", 1)[0]
    return user.username


def _profile_payload(user):
    from agent.models import UserSettings

    settings, _ = UserSettings.objects.get_or_create(user=user)
    return {
        "email": user.email,
        "username": user.username,
        "display_name": _display_name_for(user),
        "notifications_enabled": settings.notifications_enabled,
        "calendar_connected": hasattr(user, "google_calendar_connection"),
        "timezone": settings.timezone,
        "preferred_session_minutes": settings.preferred_session_minutes,
        "available_study_days": settings.available_study_days,
        "reminder_lead_minutes": settings.reminder_lead_minutes,
    }


class UserProfileView(APIView):
    """GET/PATCH/DELETE /api/profile/ — current user's account."""

    async def get(self, request):
        data = await sync_to_async(_profile_payload)(request.user)
        return Response(data, status=status.HTTP_200_OK)

    async def patch(self, request):
        serializer = UserProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        def update_profile():
            from agent.models import UserSettings

            user = request.user
            if "username" in data:
                username = data["username"].strip()
                if User.objects.exclude(pk=user.pk).filter(username__iexact=username).exists():
                    raise ValueError("That username is already taken.")
                user.username = username
            if "display_name" in data:
                user.first_name = data["display_name"].strip()
                user.last_name = ""
            user.save()

            settings_obj, _ = UserSettings.objects.get_or_create(user=user)
            changed = []
            for field in (
                "notifications_enabled", "timezone", "preferred_session_minutes",
                "available_study_days", "reminder_lead_minutes",
            ):
                if field in data:
                    setattr(settings_obj, field, data[field])
                    changed.append(field)
            if changed:
                settings_obj.save(update_fields=[*changed, "updated_at"])
            return _profile_payload(user)

        try:
            profile = await sync_to_async(update_profile)()
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(profile, status=status.HTTP_200_OK)

    async def delete(self, request):
        serializer = AccountDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            await sync_to_async(accounts.delete_account)(
                request.user, serializer.validated_data["confirmation"]
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountExportView(APIView):
    """Download a JSON export containing only the authenticated user's safe data."""

    async def get(self, request):
        payload = await sync_to_async(accounts.export_account_data)(request.user)
        response = HttpResponse(accounts.serialize_export(payload), content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, "ontrack-data.json")
        return response


class ExtractSyllabusView(APIView):
    """
    POST /api/courses/<course_id>/syllabus/extract/
    Stages an upload for human review. Extraction never replaces the current
    confirmed syllabus; the separate confirmation endpoint performs the write.
    """

    async def post(self, request, course_id):
        serializer = ExtractSyllabusRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload = serializer.validated_data["file"]
        course_name_hint = serializer.validated_data.get("course_name")
        try:
            material = await materials.stage_syllabus(
                request.user, course_id, upload, course_name_hint
            )
        except material_files.UploadValidationError as e:
            return Response({"code": e.code, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except materials.MaterialProcessingError as e:
            return Response(
                {
                    "code": e.code,
                    "detail": e.public_message,
                    "material": materials.serialize_material(e.material),
                },
                status=e.http_status,
            )

        return Response(
            {"material": materials.serialize_material(material, include_candidate=True)},
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

    DELETE /api/courses/<course_id>/ body: {"confirmation": "<course_id>"}

    Deletes the course entirely — syllabus, notes, references, sessions,
    quiz history, mastery scores. Irreversible; the server requires the exact
    course ID as typed confirmation (plan-then-pause per CLAUDE.md).
    404 if course_id doesn't exist as either a draft or a real course.
    """

    async def post(self, request, course_id):
        serializer = CreateCourseDraftRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = dict(serializer.validated_data)
        data.setdefault("semester", course_catalog.current_semester())
        course_name = data["course_name"]

        try:
            await sync_to_async(course_catalog.create_course)(request.user, course_id, data)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseAlreadyExistsError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"course_id": course_id, "course_name": course_name},
            status=status.HTTP_201_CREATED,
        )

    async def patch(self, request, course_id):
        serializer = UpdateCourseRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated = await sync_to_async(course_catalog.update_course)(request.user, course_id, dict(serializer.validated_data))
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except course_catalog.SemesterMoveRequiresConfirmation as e:
            return Response({"code": "semester_move_confirmation_required", "detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"course_id": course_id, "course_name": updated["name"]}, status=status.HTTP_200_OK)

    async def delete(self, request, course_id):
        serializer = CourseDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if serializer.validated_data["confirmation"] != course_id:
            return Response(
                {"detail": f'Type "{course_id}" to confirm course deletion.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            await sync_to_async(storage.delete_course)(course_id, request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        # Custom events aren't stored under courses/<course_id>/ (they live
        # in the top-level custom_events.json), so deleting the course
        # directory above doesn't touch them — without this they'd linger
        # as orphaned rows labeled with a course_id that no longer exists.
        await sync_to_async(custom_events.delete_events_for_course)(course_id, user=request.user)

        return Response(status=status.HTTP_204_NO_CONTENT)


class CoursesOverviewView(APIView):
    async def get(self, request):
        semester = request.query_params.get("semester") or None
        if semester:
            try:
                course_catalog.semester_label(semester)
            except ValueError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        archived = request.query_params.get("archived") == "1"
        data = await sync_to_async(course_catalog.build_courses_page)(request.user, semester=semester, archived=archived)
        return Response(data, status=status.HTTP_200_OK)


class CourseArchiveView(APIView):
    async def patch(self, request, course_id):
        serializer = CourseArchiveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            course = await sync_to_async(course_catalog.set_archived)(
                request.user, course_id, serializer.validated_data["archived"]
            )
        except (storage.InvalidCourseIdError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError:
            return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"course": course}, status=status.HTTP_200_OK)


class CourseHeaderView(APIView):
    """GET /api/courses/<course_id>/header/ — the course-workspace header
    (identity, next confirmed deadline, mastery) shared by the Overview and
    Materials pages."""

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(course_catalog.build_course_header)(course_id, request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError:
            return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        except (storage.SyllabusStorageError, storage.CourseMetadataStorageError, OSError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(data, status=status.HTTP_200_OK)


class CourseOverviewView(APIView):
    """GET /api/courses/<course_id>/overview/ — the Course Overview hub's
    mini-preview cards. Course-level 404/400 mirror CourseHeaderView
    exactly; a section-level failure never surfaces as an HTTP error — see
    course_overview.build_course_overview's own per-section isolation."""

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(course_overview.build_course_overview)(course_id, request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError:
            return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        except (storage.SyllabusStorageError, storage.CourseMetadataStorageError, OSError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(data, status=status.HTTP_200_OK)


class ChunkNotesView(APIView):
    """
    POST /api/courses/<course_id>/notes/chunk/
    multipart/form-data: file=<notes PDF/PPTX/DOCX/TXT/MD>,
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
        lecture_date_value = serializer.validated_data.get("date")
        lecture_date = lecture_date_value.isoformat() if lecture_date_value else None
        overwrite = serializer.validated_data.get("overwrite", False)

        try:
            material = await materials.process_notes(
                request.user,
                course_id,
                upload,
                lecture_id,
                lecture_date,
                overwrite=overwrite,
            )
        except material_files.UploadValidationError as e:
            return Response({"code": e.code, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (storage.InvalidCourseIdError, storage.InvalidLectureIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (storage.CourseNotFoundError, CourseNotFoundError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except materials.MaterialConflictError as e:
            return Response(
                {
                    "detail": str(e),
                    "existing_preview": e.existing_preview,
                    "resolution": "Resend the request with overwrite=true to replace it.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except materials.MaterialProcessingError as e:
            return Response(
                {
                    "code": e.code,
                    "detail": e.public_message,
                    "material": materials.serialize_material(e.material),
                },
                status=e.http_status,
            )

        data = await sync_to_async(storage.read_lecture)(course_id, lecture_id, request.user)
        return Response(
            {
                "course_id": course_id,
                "notes": data,
                "material": materials.serialize_material(material),
                "warnings": [],
            },
            status=status.HTTP_201_CREATED,
        )


class ReferencesView(APIView):
    """
    POST /api/courses/<course_id>/references/
    multipart/form-data: file=<reference PDF/PPTX/DOCX/TXT/MD>, title=<optional>

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
            material = await materials.process_reference(request.user, course_id, upload, title=title)
        except material_files.UploadValidationError as e:
            return Response({"code": e.code, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except materials.MaterialProcessingError as e:
            return Response(
                {
                    "code": e.code,
                    "detail": e.public_message,
                    "material": materials.serialize_material(e.material),
                },
                status=e.http_status,
            )

        data = await sync_to_async(storage.read_reference)(course_id, material.source_key, request.user)
        return Response(
            {
                "course_id": course_id,
                "reference": data,
                "material": materials.serialize_material(material),
            },
            status=status.HTTP_201_CREATED,
        )

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(storage.read_references)(course_id, request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.ReferencesStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"references": data}, status=status.HTTP_200_OK)


class CourseMaterialsView(APIView):
    """GET /api/courses/<course_id>/materials/ — owned upload lifecycle."""

    async def get(self, request, course_id):
        try:
            exists = await sync_to_async(storage.course_or_draft_exists)(course_id, request.user)
            if not exists:
                raise storage.CourseNotFoundError(f"no course '{course_id}' found")
            data = await sync_to_async(materials.list_materials)(request.user, course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except (storage.SyllabusStorageError, storage.NotesStorageError, storage.ReferencesStorageError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"materials": data}, status=status.HTTP_200_OK)


class CourseMaterialDetailView(APIView):
    """Poll or explicitly delete one owned material record."""

    async def get(self, request, course_id, material_id):
        try:
            data = await sync_to_async(materials.get_material)(request.user, course_id, material_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except materials.MaterialNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response({"material": data}, status=status.HTTP_200_OK)

    async def delete(self, request, course_id, material_id):
        serializer = MaterialDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            await sync_to_async(materials.delete_material)(
                request.user,
                course_id,
                material_id,
                serializer.validated_data["confirmation"],
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except materials.MaterialNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SyllabusReviewView(APIView):
    """Confirm an edited extraction candidate before replacing syllabus.json."""

    async def post(self, request, course_id, material_id):
        serializer = SyllabusReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            material = await sync_to_async(materials.confirm_syllabus)(
                request.user,
                course_id,
                material_id,
                serializer.validated_data["syllabus"],
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except materials.MaterialNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except materials.MaterialConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        syllabus = await sync_to_async(storage.read_syllabus)(course_id, request.user)
        return Response(
            {"material": materials.serialize_material(material), "syllabus": syllabus},
            status=status.HTTP_200_OK,
        )


class MaterialRetryView(APIView):
    """POST .../materials/<material_id>/retry/ — re-run processing on an
    already-failed material's stored file in place, no re-upload needed."""

    async def post(self, request, course_id, material_id):
        try:
            material = await materials.retry_material(request.user, course_id, material_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except materials.MaterialNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except materials.MaterialConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except materials.MaterialProcessingError as e:
            return Response(
                {
                    "code": e.code,
                    "detail": e.public_message,
                    "material": materials.serialize_material(e.material),
                },
                status=e.http_status,
            )
        except FileNotFoundError:
            logger.exception("Material row exists but its stored file is missing")
            return Response({"detail": "This material's file is unavailable."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(
            {"material": materials.serialize_material(material, include_candidate=True)},
            status=status.HTTP_200_OK,
        )


class MaterialDownloadView(APIView):
    """GET .../materials/<material_id>/download/ — streams the original
    uploaded file, owner-checked, with a safe attachment disposition."""

    async def get(self, request, course_id, material_id):
        try:
            material, data = await sync_to_async(materials.read_material_bytes)(request.user, course_id, material_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except materials.MaterialNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except FileNotFoundError:
            logger.exception("Material row exists but its stored file is missing")
            return Response({"detail": "This material's file is unavailable."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = HttpResponse(data, content_type=material.content_type or "application/octet-stream")
        response.headers["Content-Disposition"] = content_disposition_header(
            as_attachment=True, filename=material.original_filename,
        )
        return response


class DomainSuggestionsView(APIView):
    """
    POST /api/courses/<course_id>/domains/suggest/ — read-only. Asks Claude
    to propose candidate trusted domains from this course's syllabus. Never
    writes anything; the human approves (or hand-edits) the list via
    PUT /domains/ separately.
    """

    async def post(self, request, course_id):
        try:
            domains = await domain_suggestions.suggest_domains(course_id, request.user)
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
            domains = await sync_to_async(storage.read_trusted_domains)(course_id, request.user)
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
            await sync_to_async(storage.write_trusted_domains)(course_id, domains, request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"course_id": course_id, "domains": domains}, status=status.HTTP_200_OK)


class SavedSitesView(APIView):
    """
    GET /api/courses/<course_id>/saved-sites/ — saved URL metadata only.
    POST /api/courses/<course_id>/saved-sites/
    body: {"url": "https://...", "title": "optional"}
    """

    async def get(self, request, course_id):
        try:
            sites = await sync_to_async(storage.list_saved_sites)(course_id, user=request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DatabaseError:
            logger.exception("Database error listing saved sites")
            return Response(
                {"detail": "The saved sites database is not ready. Run database migrations, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"sites": sites}, status=status.HTTP_200_OK)

    async def post(self, request, course_id):
        serializer = SavedSiteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            site = await sync_to_async(storage.save_site)(
                course_id,
                serializer.validated_data["url"],
                title=serializer.validated_data.get("title") or None,
                user=request.user,
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except DatabaseError:
            logger.exception("Database error saving site")
            return Response(
                {"detail": "The saved sites database is not ready. Run database migrations, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"course_id": course_id, "site": site}, status=status.HTTP_201_CREATED)


class GradingConfigView(APIView):
    """
    GET /api/courses/<course_id>/grading/ — the grading array plus the
    effective grade scale (the course's own, or the default one if it
    hasn't set one).

    PUT /api/courses/<course_id>/grading/
    body: {"grading": [{"component", "weight_pct", "total_items"?, "drop_lowest"?}, ...], "grade_scale"?: {...}}
    """

    async def get(self, request, course_id):
        syllabus = await sync_to_async(storage.read_syllabus)(course_id, request.user)
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

        orphaned = await sync_to_async(grades.find_orphaned_components)(course_id, grading, user=request.user)
        warnings += [
            f"WARNING: '{c}' has entered grades that won't count toward your grade anymore — "
            f"no matching category in the new setup"
            for c in orphaned
        ]

        try:
            await sync_to_async(storage.write_grading_config)(course_id, grading, request.user, grade_scale=grade_scale)
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
            grade = await sync_to_async(grades.current_grade)(course_id, user=request.user)
            items = (await sync_to_async(storage.read_grades)(course_id, user=request.user))["items"]
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
                user=request.user,
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
            item = await sync_to_async(grades.update_item)(course_id, item_id, user=request.user, **fields)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(item, status=status.HTTP_200_OK)

    async def delete(self, request, course_id, item_id):
        try:
            await sync_to_async(grades.delete_item)(course_id, item_id, user=request.user)
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
            needed = await sync_to_async(grades.grade_needed)(course_id, target_pct, user=request.user)
            missable = await sync_to_async(grades.missable_by_category)(course_id, target_pct, user=request.user)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response({"grade_needed": needed, "missable_by_category": missable}, status=status.HTTP_200_OK)


class GradeProjectionView(APIView):
    """GET /api/courses/<course_id>/grades/project/ — "if I score X on this
    assignment" projection. Either ?item_id=<id>&score=<pct>&max_points=<pts>
    (substitutes a hypothetical score onto an already-entered item) or
    ?component=<name>&score=<pct>&max_points=<pts>[&title=<title>] (projects
    a not-yet-entered/upcoming item). Never writes to storage — see
    grades.project_grade() for why this is a different question than
    grades-whatif's target-seeking grade_needed()."""

    async def get(self, request, course_id):
        item_id = request.query_params.get("item_id") or None
        component = request.query_params.get("component") or None
        title = request.query_params.get("title") or None
        try:
            score = float(request.query_params.get("score"))
            max_points = float(request.query_params.get("max_points"))
        except (TypeError, ValueError):
            return Response({"detail": "query params 'score' and 'max_points' must be numbers"}, status=status.HTTP_400_BAD_REQUEST)
        if score < 0 or max_points < 0.01:
            return Response({"detail": "'score' must be >= 0 and 'max_points' must be >= 0.01"}, status=status.HTTP_400_BAD_REQUEST)
        if not item_id and not component:
            return Response({"detail": "provide either 'item_id' or 'component'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            projection = await sync_to_async(grades.project_grade)(
                course_id, score, max_points, item_id=item_id, component=component, title=title, user=request.user,
            )
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except grades.ItemNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(projection, status=status.HTTP_200_OK)


class GradesSummaryView(APIView):
    """GET /api/grades/summary/ — all-courses rollup."""

    async def get(self, request):
        data = await sync_to_async(grades.all_courses_summary)(user=request.user)
        return Response(data, status=status.HTTP_200_OK)


class MasteryView(APIView):
    """GET /api/courses/<course_id>/mastery/ — topic scores, weakest-first.
    [] if mastery_scores.json hasn't been built yet (POST .../mastery/rebuild/ first)."""

    async def get(self, request, course_id):
        try:
            if not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user):
                return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
            scores = await sync_to_async(mastery.weak_topics)(course_id, user=request.user)
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
            if not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user):
                return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
            data = await sync_to_async(mastery.rebuild_scores)(course_id, user=request.user)
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
        question_type = serializer.validated_data.get("question_type")
        previous_questions = serializer.validated_data.get("previous_questions")

        try:
            q = await quiz.generate_assessment_question_async(
                course_id, topic=topic, chunk_id=chunk_id,
                question_type=question_type, previous_questions=previous_questions,
                user=request.user,
            )
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except quiz.NoChunksAvailableError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ValueError as e:
            return Response({"detail": f"question generation failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        q["citation"] = await sync_to_async(citations.citation_for_chunk)(
            request.user, course_id, q.get("lecture_id"), q.get("chunk_id")
        )
        return Response(q, status=status.HTTP_200_OK)


class FlashcardsGenerateView(APIView):
    """
    POST /api/courses/<course_id>/flashcards/generate/
    body: {"topic": "<optional>", "chunk_id": "<optional>", "count": 1..12, "regenerate": false}

    Returns saved flashcards by default for an unscoped request (no topic or
    chunk_id). Uses Haiku when no saved deck exists, when regenerate=true is
    explicitly requested, or whenever topic/chunk_id narrows the request —
    the saved deck isn't scoped by topic/chunk, so it can't answer those.
    """

    async def post(self, request, course_id):
        serializer = GenerateFlashcardsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        topic = serializer.validated_data.get("topic")
        chunk_id = serializer.validated_data.get("chunk_id")
        count = serializer.validated_data.get("count", 8)
        regenerate = serializer.validated_data.get("regenerate", False)

        try:
            saved_flashcards = []
            if not regenerate and not topic and not chunk_id:
                saved_flashcards = await sync_to_async(storage.read_saved_flashcards)(course_id, user=request.user)
            if saved_flashcards:
                deck = {
                    "course_id": course_id,
                    "model": "saved",
                    "flashcards": saved_flashcards,
                }
            else:
                deck = await quiz.generate_flashcards_async(
                    course_id, topic=topic, chunk_id=chunk_id, count=count, user=request.user
                )
                deck["flashcards"] = await sync_to_async(storage.annotate_flashcards_with_progress)(
                    course_id, deck.get("flashcards", []), user=request.user
                )
                await sync_to_async(storage.remember_generated_flashcards)(
                    course_id, deck.get("flashcards", []), user=request.user
                )
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.FlashcardProgressStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except quiz.NoChunksAvailableError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ValueError as e:
            return Response({"detail": f"flashcard generation failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(deck, status=status.HTTP_200_OK)


class FlashcardProgressView(APIView):
    """
    PATCH /api/courses/<course_id>/flashcards/progress/
    body: {"key", "term", "definition", "status", "starred"}
    """

    async def patch(self, request, course_id):
        serializer = FlashcardProgressUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            if await sync_to_async(storage.read_syllabus)(course_id, request.user) is None:
                return Response({"detail": f"no syllabus found for '{course_id}'"}, status=status.HTTP_404_NOT_FOUND)
            result = await sync_to_async(storage.update_flashcard_progress)(
                course_id, serializer.validated_data, user=request.user
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.SyllabusStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except storage.FlashcardProgressStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class FlashcardProgressResetView(APIView):
    """
    POST /api/courses/<course_id>/flashcards/progress/reset/
    body: {"keys": ["..."]}
    """

    async def post(self, request, course_id):
        serializer = FlashcardProgressResetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            if await sync_to_async(storage.read_syllabus)(course_id, request.user) is None:
                return Response({"detail": f"no syllabus found for '{course_id}'"}, status=status.HTTP_404_NOT_FOUND)
            await sync_to_async(storage.reset_flashcard_progress)(
                course_id, serializer.validated_data["keys"], user=request.user
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.SyllabusStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except storage.FlashcardProgressStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class FlashcardReviewView(APIView):
    """
    POST /api/courses/<course_id>/flashcards/review/
    body: {"key", "rating": "again|hard|good|easy"}

    Records a spaced-repetition review and returns the card's new scheduling
    state. 409 if the card is suspended — reviewing it would silently pull it
    back into the due queue, which the learner didn't ask for.
    """

    async def post(self, request, course_id):
        serializer = FlashcardReviewRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = await sync_to_async(storage.review_flashcard)(
                course_id, serializer.validated_data["key"], serializer.validated_data["rating"],
                user=request.user,
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.FlashcardSuspendedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(result, status=status.HTTP_200_OK)


class FlashcardSuspendView(APIView):
    """
    POST /api/courses/<course_id>/flashcards/suspend/
    body: {"key", "suspended": true|false}
    """

    async def post(self, request, course_id):
        serializer = FlashcardSuspendRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = await sync_to_async(storage.suspend_flashcard)(
                course_id, serializer.validated_data["key"], serializer.validated_data["suspended"],
                user=request.user,
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class FlashcardsDueView(APIView):
    """GET /api/courses/<course_id>/flashcards/due/?limit=<int> — cards due now."""

    async def get(self, request, course_id):
        limit, error = _positive_int_query_param(request, "limit", 20)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user):
                return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
            due = await sync_to_async(storage.due_flashcards)(course_id, user=request.user, limit=limit)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"cards": due}, status=status.HTTP_200_OK)


class StudySessionsView(APIView):
    """
    GET  /api/courses/<course_id>/study/sessions/?limit=<int> — session history for this course.
    POST /api/courses/<course_id>/study/sessions/ body: {"topic", "duration_minutes", "mode"} — start a session.
    """

    async def get(self, request, course_id):
        limit, error = _positive_int_query_param(request, "limit", 20)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user):
                return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
            sessions_list = await sync_to_async(study_sessions.list_sessions)(request.user, course_id=course_id, limit=limit)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"sessions": sessions_list}, status=status.HTTP_200_OK)

    async def post(self, request, course_id):
        serializer = StartStudySessionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        try:
            session = await sync_to_async(study_sessions.start_session)(
                request.user, course_id, topic=d["topic"], duration_minutes=d["duration_minutes"], mode=d["mode"],
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(session, status=status.HTTP_201_CREATED)


class StudySessionDetailView(APIView):
    """GET /api/courses/<course_id>/study/sessions/<session_id>/ — session plus its activity stream."""

    async def get(self, request, course_id, session_id):
        try:
            detail = await sync_to_async(study_sessions.session_detail)(request.user, session_id)
        except study_sessions.StudySessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        if detail["course_id"] != course_id:
            return Response({"detail": "no such study session"}, status=status.HTTP_404_NOT_FOUND)
        return Response(detail, status=status.HTTP_200_OK)


class StudySessionActivityView(APIView):
    """POST /api/courses/<course_id>/study/sessions/<session_id>/activities/ body: {"kind", "payload"}."""

    async def post(self, request, course_id, session_id):
        serializer = RecordStudyActivityRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            detail = await sync_to_async(study_sessions.session_detail)(request.user, session_id)
            if detail["course_id"] != course_id:
                return Response({"detail": "no such study session"}, status=status.HTTP_404_NOT_FOUND)
            activity = await sync_to_async(study_sessions.record_activity)(
                request.user, session_id,
                serializer.validated_data["kind"], serializer.validated_data["payload"],
            )
        except study_sessions.StudySessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except study_sessions.InvalidStudySessionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(activity, status=status.HTTP_201_CREATED)


class StudySessionCompleteView(APIView):
    """POST /api/courses/<course_id>/study/sessions/<session_id>/complete/ — ends the session, returns its summary."""

    async def post(self, request, course_id, session_id):
        try:
            detail = await sync_to_async(study_sessions.session_detail)(request.user, session_id)
            if detail["course_id"] != course_id:
                return Response({"detail": "no such study session"}, status=status.HTTP_404_NOT_FOUND)
            result = await sync_to_async(study_sessions.complete_session)(request.user, session_id)
        except study_sessions.StudySessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except study_sessions.InvalidStudySessionStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(result, status=status.HTTP_200_OK)


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
                user=request.user,
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except quiz.InvalidChunkReferenceError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class QuizHistoryView(APIView):
    """
    GET /api/courses/<course_id>/quiz/history/?limit=<int, default 10>
    Most recent quiz attempts for this course, newest first.
    """

    async def get(self, request, course_id):
        limit, error = _positive_int_query_param(request, "limit", 10)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            attempts = await sync_to_async(quiz.recent_attempts)(course_id, limit=limit, user=request.user)
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
        within_days, error = _positive_int_query_param(request, "within_days", 14)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        course_id = request.query_params.get("course_id")
        course_ids = [course_id] if course_id else None

        deadlines = await sync_to_async(reminders.upcoming_deadlines)(
            request.user, within_days=within_days, course_ids=course_ids,
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
        await sync_to_async(notifications.generate_overdue_deadline_notifications)(user=request.user)
        data = await sync_to_async(dashboard.build_dashboard)(user=request.user)
        return Response(data, status=status.HTTP_200_OK)


class RecommendationsView(APIView):
    """
    GET /api/recommendations/?limit=<int, default 3>&session_minutes=<int, optional>
    Deterministic "what to study next" ranking across every course — no LLM;
    every result's rank_score/reason trace back to the same structured
    facts (deadline urgency, assessment importance, mastery gap, recency).
    session_minutes only changes each result's suggested_mode, never the
    ranking order. Always 200 with a possibly-empty list — missing mastery,
    grading, or deadline data is a normal state here, not an error.
    """

    async def get(self, request):
        limit, error = _positive_int_query_param(request, "limit", 3)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        session_minutes = None
        if request.query_params.get("session_minutes"):
            session_minutes, error = _positive_int_query_param(request, "session_minutes", None)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        items = await sync_to_async(recommendations.rank_recommendations)(
            request.user, session_minutes=session_minutes, limit=limit,
        )
        return Response({"recommendations": items}, status=status.HTTP_200_OK)


class RecommendationDismissView(APIView):
    """
    POST /api/recommendations/dismiss/
    body: {"course_id", "topic", "defer_hours": <int, optional>}
    Hides one (course, topic) recommendation — indefinitely, or until
    defer_hours from now when given. Never touches quiz/flashcard/deadline
    data; the recommendation is simply recomputed (and can reappear) later.
    """

    async def post(self, request):
        serializer = DismissRecommendationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        defer_until = None
        if d.get("defer_hours"):
            defer_until = datetime.now(timezone.utc) + timedelta(hours=d["defer_hours"])

        try:
            await sync_to_async(recommendations.dismiss_recommendation)(
                request.user, d["course_id"], d["topic"], defer_until=defer_until,
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class ExamsListView(APIView):
    """GET /api/courses/<course_id>/exams/ — every confirmed test_quiz event for this course, soonest first."""

    async def get(self, request, course_id):
        try:
            items = await sync_to_async(exams.list_exams)(request.user, course_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"exams": items}, status=status.HTTP_200_OK)


class ExamWorkspaceView(APIView):
    """GET /api/courses/<course_id>/exams/<event_id>/ — countdown, plan, per-topic
    readiness, and the owned source library for one confirmed exam. 404 if
    event_id doesn't resolve to a live, owned, test_quiz-type event — which
    is also what a deleted or rescheduled exam looks like, safely."""

    async def get(self, request, course_id, event_id):
        try:
            workspace = await sync_to_async(exams.build_workspace)(request.user, course_id, event_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except exams.ExamNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(workspace, status=status.HTTP_200_OK)


class ExamPlanView(APIView):
    """
    PATCH /api/courses/<course_id>/exams/<event_id>/plan/
    body: {"included_topics": [...] | null, "included_material_ids": [...] | null}
    Confirms in-scope topics/materials; null (omitted) leaves that side
    untouched. Anything not actually owned/valid is silently dropped rather
    than rejected — a stale client-side list is a normal state here.
    """

    async def patch(self, request, course_id, event_id):
        serializer = UpdateExamPlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        try:
            plan = await sync_to_async(exams.update_plan)(
                request.user, course_id, event_id,
                included_topics=d["included_topics"], included_material_ids=d["included_material_ids"],
            )
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except exams.ExamNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

        return Response(plan, status=status.HTTP_200_OK)


class ExamStudyGuideView(APIView):
    """
    POST /api/courses/<course_id>/exams/<event_id>/study-guide/
    Generates a study guide from only the plan's currently-included topics
    and materials, with a citation per section resolved through the
    existing owned-source citation resolver. 422 if nothing usable is
    selected; never fabricates content beyond the selected material.
    """

    async def post(self, request, course_id, event_id):
        try:
            guide = await exams.generate_study_guide(request.user, course_id, event_id)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except exams.ExamNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except exams.NoStudyMaterialSelectedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ValueError as e:
            return Response({"detail": f"study guide generation failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(guide, status=status.HTTP_200_OK)


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
                serializer.validated_data["date"].isoformat(),
                serializer.validated_data["title"],
                serializer.validated_data["type"],
            )
        except calendar_sync.AlreadySyncedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except calendar_sync.CalendarNotConnectedError as e:
            return Response(
                {"code": "calendar_not_connected", "detail": str(e)},
                status=status.HTTP_409_CONFLICT,
            )
        except calendar_sync.CalendarAuthError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            # Last-resort safety net: no future unexpected exception from the
            # service layer should ever surface as a raw 500 on this
            # endpoint. Must stay last — Python checks except clauses in
            # order, and this is intentionally broad, not a substitute for
            # the specific handlers above.
            logger.exception("Unexpected error in calendar sync")
            return Response({"detail": "Could not add to Google Calendar."}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_201_CREATED)


class DeadlinesView(APIView):
    """
    GET /api/deadlines/ — every upcoming deadline, syllabus-extracted and
    manually-added combined, unbounded (no 14-day cap).
    POST /api/deadlines/ — create a manually-added deadline.
    body: {"course_id"?, "date", "time"?, "title", "type"}
    course_id omitted/null means a general (not course-specific) event.
    """

    async def get(self, request):
        course_id = request.query_params.get("course_id") or None
        if course_id == "all":
            course_id = None
        if course_id is not None and not await sync_to_async(storage.course_or_draft_exists)(course_id, request.user):
            return Response({"detail": f"no course '{course_id}' found"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        try:
            await sync_to_async(notifications.generate_overdue_deadline_notifications)(user=request.user)
            data = await sync_to_async(reminders.list_all_deadlines)(user=request.user, course_id=course_id)
        except storage.CustomEventsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(data, status=status.HTTP_200_OK)

    async def post(self, request):
        serializer = CreateCustomEventRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        d = serializer.validated_data

        if d["course_id"] is not None and not await sync_to_async(storage.course_exists)(d["course_id"], request.user):
            return Response({"detail": f"no course '{d['course_id']}' found"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            event = await sync_to_async(custom_events.create_event)(
                d["course_id"],
                d["date"].isoformat(),
                d["time"].strftime("%H:%M") if d["time"] else None,
                d["title"], d["type"], user=request.user,
                end_time=d["end_time"].strftime("%H:%M") if d.get("end_time") else None,
                replaces_syllabus_key=d.get("replaces_syllabus_key"),
                completed=d.get("completed", False),
                estimated_effort_minutes=d.get("estimated_effort_minutes"),
                source_material_id=d.get("source_material_id"),
                location=d.get("location", ""),
                notes=d.get("notes", ""),
            )
        except storage.CustomEventsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError as e:
            return Response(
                {"detail": "Deadline storage is not migrated yet. Run manage.py migrate, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(event, status=status.HTTP_201_CREATED)


class CalendarView(APIView):
    """GET /api/calendar/ — complete confirmed, owner-scoped calendar data."""

    async def get(self, request):
        data = await sync_to_async(calendar_events.calendar_snapshot)(request.user)
        return Response(data, status=status.HTTP_200_OK)


class CustomEventDetailView(APIView):
    """
    PATCH /api/deadlines/<event_id>/ — partial update.
    DELETE /api/deadlines/<event_id>/
    """

    async def patch(self, request, event_id):
        serializer = UpdateCustomEventRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        # Keyed off request.data (what the client actually sent), not
        # validated_data (where every omitted field also defaults to None) —
        # otherwise an explicit {"time": null} to clear a field is
        # indistinguishable from the field simply being absent, and gets
        # silently dropped instead of applied.
        fields = {k: v for k, v in serializer.validated_data.items() if k in request.data}
        if "date" in fields:
            fields["date"] = fields["date"].isoformat()
        if "time" in fields:
            fields["time"] = fields["time"].strftime("%H:%M") if fields["time"] else None
        if "end_time" in fields:
            fields["end_time"] = fields["end_time"].strftime("%H:%M") if fields["end_time"] else None
        if "source_material_id" in fields and fields["source_material_id"] is not None:
            fields["source_material_id"] = str(fields["source_material_id"])

        if fields.get("course_id") is not None and not await sync_to_async(storage.course_exists)(fields["course_id"], request.user):
            return Response({"detail": f"no course '{fields['course_id']}' found"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            event = await sync_to_async(custom_events.update_event)(event_id, user=request.user, **fields)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.CustomEventsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError as e:
            return Response(
                {"detail": "Deadline storage is not migrated yet. Run manage.py migrate, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(event, status=status.HTTP_200_OK)

    async def delete(self, request, event_id):
        try:
            await sync_to_async(custom_events.delete_event)(event_id, user=request.user)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except storage.CustomEventsStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError as e:
            return Response(
                {"detail": "Deadline storage is not migrated yet. Run manage.py migrate, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationsView(APIView):
    """GET /api/notifications/ and PATCH /api/notifications/read/."""

    async def get(self, request):
        data = await sync_to_async(notifications.list_notifications)(user=request.user)
        return Response(data, status=status.HTTP_200_OK)


class NotificationsReadView(APIView):
    async def patch(self, request):
        serializer = NotificationReadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = await sync_to_async(notifications.mark_notifications_read)(
            user=request.user,
            ids=serializer.validated_data.get("ids"),
        )
        return Response(data, status=status.HTTP_200_OK)


class CustomEventCalendarSyncView(APIView):
    """POST /api/deadlines/<event_id>/calendar-sync/ — push a custom event
    to the signed-in user's real Google Calendar. 404 if the event doesn't
    exist, 409 if already synced, 502 if Google credentials can't be used
    (including any unexpected failure — never an unhandled 500)."""

    async def post(self, request, event_id):
        try:
            result = await sync_to_async(custom_events.sync_event_to_calendar)(request.user, event_id)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except calendar_sync.AlreadySyncedError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except calendar_sync.CalendarNotConnectedError as e:
            return Response(
                {"code": "calendar_not_connected", "detail": str(e)},
                status=status.HTTP_409_CONFLICT,
            )
        except calendar_sync.CalendarAuthError as e:
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("Unexpected error in custom event calendar sync")
            return Response({"detail": "Could not add to Google Calendar."}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_201_CREATED)


class SyllabusDetailView(APIView):
    """GET /api/courses/<course_id>/syllabus/ — returns the stored syllabus.json, or 404."""

    async def get(self, request, course_id):
        try:
            data = await sync_to_async(storage.read_syllabus)(course_id, request.user)
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
        request_id = serializer.validated_data.get("client_request_id")

        try:
            result = await ask_async(
                course_id,
                question,
                session_id=session_id,
                user=request.user,
                client_request_id=str(request_id) if request_id else None,
                allow_web=serializer.validated_data["grounding_mode"] == "course_materials_and_web",
            )
        except CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except sessions.SessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (storage.SyllabusStorageError, storage.NotesStorageError,
                storage.ReferencesStorageError, storage.TrustedDomainsStorageError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError:
            logger.exception("Database error in ask endpoint")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except ValueError as e:
            return Response({"detail": f"ask failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result, status=status.HTTP_200_OK)


class ConfirmDeadlineActionsView(APIView):
    """
    POST /api/courses/<course_id>/sessions/<session_id>/deadlines/confirm/
    body: {"actions": [{"action": "create"|"update"|"delete", "event_id"?,
    "title"?, "date"?, "time"?, "end_time"?, "type"?, "course_id"?}, ...]}

    Executes one or more calendar actions Cora proposed earlier in this
    session, then appends one confirmation turn. This is the only path that
    lets a Cora conversation actually write to the calendar — ask_async only
    ever proposes a pending_deadline/pending_deadlines for the user to
    review; nothing is written until they explicitly confirm here. event_id
    ownership is re-resolved against the signed-in user's own events
    server-side regardless of what the model proposed.
    """

    async def post(self, request, course_id, session_id):
        serializer = ConfirmDeadlineActionsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = await sync_to_async(confirm_deadline_actions)(
                course_id, session_id, serializer.validated_data["actions"], user=request.user,
            )
        except sessions.SessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except custom_events.EventNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(session, status=status.HTTP_200_OK)


class SessionsView(APIView):
    """
    POST /api/courses/<course_id>/sessions/ — creates a new session, 201 with
    {"session_id", "created_at"}. 404 if no syllabus.json exists for course_id.

    GET /api/courses/<course_id>/sessions/ — 200 with a list of session
    summaries (session_id, created_at, updated_at, message_count).
    """

    async def post(self, request, course_id):
        try:
            session = await sync_to_async(sessions.create_session)(course_id, user=request.user)
        except storage.InvalidCourseIdError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except storage.CourseNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DatabaseError:
            logger.exception("Database error creating chat session")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"session_id": session["session_id"], "created_at": session["created_at"]},
            status=status.HTTP_201_CREATED,
        )

    async def get(self, request, course_id):
        try:
            exists = await sync_to_async(storage.course_or_draft_exists)(course_id, request.user)
            if not exists:
                return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
            summaries = await sync_to_async(sessions.list_sessions)(course_id, user=request.user)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError:
            logger.exception("Database error listing chat sessions")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(summaries, status=status.HTTP_200_OK)


class SessionDetailView(APIView):
    """Read, rename, or explicitly delete one owned Cora conversation."""

    async def get(self, request, course_id, session_id):
        try:
            session = await sync_to_async(sessions.get_session)(course_id, session_id, user=request.user)
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionStorageError as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError:
            logger.exception("Database error loading chat session")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if session is None:
            return Response(
                {"detail": f"no session '{session_id}' found for course '{course_id}'"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(session)

    async def patch(self, request, course_id, session_id):
        serializer = SessionRenameSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            session = await sync_to_async(sessions.rename_session)(
                course_id, session_id, serializer.validated_data["title"], user=request.user
            )
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DatabaseError:
            logger.exception("Database error renaming chat session")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(session, status=status.HTTP_200_OK)

    async def delete(self, request, course_id, session_id):
        serializer = SessionDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            await sync_to_async(sessions.delete_session)(
                course_id,
                session_id,
                serializer.validated_data["confirmation"],
                user=request.user,
            )
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except sessions.SessionNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DatabaseError:
            logger.exception("Database error deleting chat session")
            return Response(
                {"detail": "The chat database is not ready. Run database migrations, then try Cora again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SourcePreviewView(APIView):
    """POST an identifying citation and return only an owner-verified preview."""

    async def post(self, request, course_id):
        serializer = CitationPreviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            source = await sync_to_async(citations.preview_stored_source)(
                request.user, course_id, serializer.validated_data
            )
        except (storage.InvalidCourseIdError, sessions.InvalidSessionIdError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except citations.CitationNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except (
            storage.SyllabusStorageError,
            storage.NotesStorageError,
            storage.ReferencesStorageError,
            storage.TrustedDomainsStorageError,
        ) as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError:
            logger.exception("Database error resolving Cora source preview")
            return Response(
                {"detail": "The source index is not ready. Run database migrations, then try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"source": source}, status=status.HTTP_200_OK)


class PracticeAttemptsView(APIView):
    """Create or resume the user's active practice attempt for an owned exam."""

    async def post(self, request, course_id, quiz_id):
        serializer = StartPracticeAttemptRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = await interactive_study.create_practice_attempt(
                request.user, course_id, quiz_id, serializer.validated_data["question_count"],
            )
        except (storage.CourseNotFoundError, exams.ExamNotFoundError, study_sessions.StudySessionNotFoundError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except interactive_study.InteractiveStudyValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            logger.exception("Practice attempt generation returned invalid structured output")
            return Response({"detail": "Practice questions could not be prepared. Try again."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result, status=status.HTTP_201_CREATED)


class PracticeAttemptDetailView(APIView):
    async def get(self, request, course_id, attempt_id):
        try:
            result = await sync_to_async(interactive_study.practice_detail)(request.user, course_id, attempt_id)
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result)

    async def patch(self, request, course_id, attempt_id):
        serializer = UpdatePracticeAttemptRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = await sync_to_async(interactive_study.update_practice)(
                request.user, course_id, attempt_id, **serializer.validated_data,
            )
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except interactive_study.InteractiveStudyValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except interactive_study.InteractiveStudyConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(result)


class PracticeAttemptFinalizeView(APIView):
    async def post(self, request, course_id, attempt_id):
        try:
            result = await sync_to_async(interactive_study.finalize_practice)(request.user, course_id, attempt_id)
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except interactive_study.InteractiveStudyConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(result)


class InteractiveFlashcardSessionsView(APIView):
    async def post(self, request, course_id, deck_id):
        try:
            result = await sync_to_async(interactive_study.start_flashcard_session)(request.user, course_id, deck_id)
        except storage.CourseNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result, status=status.HTTP_201_CREATED)


class InteractiveFlashcardDetailView(APIView):
    async def get(self, request, course_id, session_id):
        try:
            result = await sync_to_async(interactive_study.flashcard_detail)(request.user, course_id, session_id)
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result)

    async def patch(self, request, course_id, session_id):
        serializer = NavigateInteractiveFlashcardRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = await sync_to_async(interactive_study.navigate_flashcard)(
                request.user, course_id, session_id, serializer.validated_data["position"],
            )
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except interactive_study.InteractiveStudyValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class InteractiveFlashcardRevealView(APIView):
    async def post(self, request, course_id, session_id):
        try:
            result = await sync_to_async(interactive_study.reveal_flashcard)(request.user, course_id, session_id)
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except interactive_study.InteractiveStudyConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(result)


class InteractiveFlashcardRateView(APIView):
    async def post(self, request, course_id, session_id):
        serializer = RateInteractiveFlashcardRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = await sync_to_async(interactive_study.rate_flashcard)(
                request.user, course_id, session_id, **serializer.validated_data,
            )
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except (interactive_study.InteractiveStudyConflictError, storage.FlashcardSuspendedError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(result)


class InteractiveFlashcardEndView(APIView):
    async def post(self, request, course_id, session_id):
        try:
            result = await sync_to_async(interactive_study.end_flashcard_session)(request.user, course_id, session_id)
        except study_sessions.StudySessionNotFoundError:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result)
