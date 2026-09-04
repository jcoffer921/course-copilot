from rest_framework import serializers
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .services import storage


def _validate_deadline_type(value):
    raw = str(value or "other").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in storage.VALID_DATE_TYPES or raw in storage.LEGACY_DATE_TYPE_MAP:
        return storage.normalize_date_type(raw)
    raise serializers.ValidationError("Invalid deadline category.")


class UserProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=False, max_length=150)
    username = serializers.CharField(required=False, allow_blank=False, max_length=150)
    bio = serializers.CharField(required=False, allow_blank=True, max_length=500)
    university = serializers.CharField(required=False, allow_blank=True, max_length=150)
    major = serializers.CharField(required=False, allow_blank=True, max_length=150)
    graduation_year = serializers.IntegerField(required=False, allow_null=True, min_value=1900, max_value=2200)
    notifications_enabled = serializers.BooleanField(required=False)
    email_notifications_enabled = serializers.BooleanField(required=False)
    timezone = serializers.CharField(required=False, max_length=64)
    preferred_session_minutes = serializers.ChoiceField(required=False, choices=[15, 25, 30, 45, 60, 90])
    available_study_days = serializers.ListField(
        required=False, allow_empty=False, child=serializers.IntegerField(min_value=0, max_value=6), max_length=7,
    )
    reminder_lead_minutes = serializers.ChoiceField(required=False, choices=[0, 5, 10, 15, 30, 60, 1440])
    study_reminder_time = serializers.TimeField(required=False, format="%H:%M", input_formats=["%H:%M"])

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise serializers.ValidationError("Use a valid IANA timezone identifier.")
        return value

    def validate_available_study_days(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Study days cannot contain duplicates.")
        return sorted(value)


class AccountDeleteSerializer(serializers.Serializer):
    confirmation = serializers.CharField(allow_blank=False)


class CalendarSyncRequestSerializer(serializers.Serializer):
    # DateField (not CharField) so a malformed date ("not-a-date") is
    # rejected here with a 400 at the serializer layer, rather than passing
    # validation and later blowing up datetime.strptime() in calendar_sync.py.
    date = serializers.DateField()
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)


class CreateCustomEventRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    date = serializers.DateField()
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    end_time = serializers.TimeField(required=False, allow_null=True, default=None)
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)
    location = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    completed = serializers.BooleanField(required=False, default=False)
    estimated_effort_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    source_material_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    replaces_syllabus_key = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)

    def validate(self, attrs):
        attrs["type"] = _validate_deadline_type(attrs.get("type"))
        if attrs.get("end_time") and not attrs.get("time"):
            raise serializers.ValidationError({"end_time": "End time requires a start time."})
        if attrs.get("time") and attrs.get("end_time") and attrs["end_time"] <= attrs["time"]:
            raise serializers.ValidationError({"end_time": "End time must be later than start time."})
        return attrs


class UpdateCustomEventRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    date = serializers.DateField(required=False, default=None)
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    end_time = serializers.TimeField(required=False, allow_null=True, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    type = serializers.CharField(required=False, allow_blank=False, default=None)
    location = serializers.CharField(required=False, allow_blank=True, max_length=255, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default=None)
    completed = serializers.BooleanField(required=False, default=None)
    estimated_effort_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    source_material_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if attrs.get("type") is not None:
            attrs["type"] = _validate_deadline_type(attrs.get("type"))
        if attrs.get("end_time") and not attrs.get("time") and "time" in self.initial_data:
            raise serializers.ValidationError({"end_time": "End time requires a start time."})
        if attrs.get("time") and attrs.get("end_time") and attrs["end_time"] <= attrs["time"]:
            raise serializers.ValidationError({"end_time": "End time must be later than start time."})
        return attrs


class ConfirmDeadlineActionItemSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["create", "update", "delete"], default="create")
    event_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    date = serializers.DateField(required=False, allow_null=True, default=None)
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    end_time = serializers.TimeField(required=False, allow_null=True, default=None)
    type = serializers.CharField(required=False, allow_blank=False, default=None)

    def validate(self, attrs):
        if attrs.get("type") is not None:
            attrs["type"] = _validate_deadline_type(attrs.get("type"))
        if attrs["action"] in ("update", "delete") and not attrs.get("event_id"):
            raise serializers.ValidationError({"event_id": f"event_id is required for action '{attrs['action']}'."})
        return attrs


class ConfirmDeadlineActionsRequestSerializer(serializers.Serializer):
    actions = ConfirmDeadlineActionItemSerializer(many=True)

    def validate_actions(self, value):
        if not value:
            raise serializers.ValidationError("At least one action is required.")
        # A full-semester recurring class schedule (ask.py's CLASS_SCHEDULE_WEEKS
        # = 15 weeks, up to 3 meetings/week) can legitimately propose up to ~45
        # items in one confirmation — capped well above that, not at an
        # arbitrary round number, so a real MWF/TTh semester schedule never
        # gets rejected.
        if len(value) > 150:
            raise serializers.ValidationError("Too many actions in one confirmation.")
        return value


class NotificationReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True, default=None)


class PilotFeedbackSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=["bug", "confusing", "idea", "other"])
    message = serializers.CharField(allow_blank=False, max_length=2000, trim_whitespace=True)
    page = serializers.CharField(required=False, allow_blank=True, max_length=255)
    anonymous = serializers.BooleanField(required=False, default=True, write_only=True)


class ExtractSyllabusRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    course_name = serializers.CharField(required=False, allow_blank=True, default=None)
    overwrite = serializers.BooleanField(required=False, default=False)


class AskRequestSerializer(serializers.Serializer):
    question = serializers.CharField(allow_blank=False, max_length=4000)
    session_id = serializers.CharField(required=False, allow_blank=False, default=None)
    client_request_id = serializers.UUIDField(required=False, default=None)
    grounding_mode = serializers.ChoiceField(
        choices=["course_materials", "course_materials_and_web"],
        required=False,
        default="course_materials",
    )

    def validate(self, attrs):
        if attrs.get("client_request_id") and not attrs.get("session_id"):
            raise serializers.ValidationError({"client_request_id": "A session_id is required for retry safety."})
        return attrs


class SessionRenameSerializer(serializers.Serializer):
    title = serializers.CharField(allow_blank=False, max_length=255)


class SessionDeleteSerializer(serializers.Serializer):
    confirmation = serializers.CharField(allow_blank=False)


class CitationPreviewSerializer(serializers.Serializer):
    session_id = serializers.CharField(allow_blank=False, max_length=64)
    message_index = serializers.IntegerField(min_value=0)
    citation_index = serializers.IntegerField(min_value=0, max_value=11)
    material_id = serializers.CharField(allow_blank=False, max_length=128)
    material_type = serializers.ChoiceField(choices=["syllabus", "notes", "slides", "reference", "web"])
    lecture_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64)
    chunk_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=128)
    url = serializers.URLField(required=False, allow_blank=True, allow_null=True, max_length=2048)

    def validate(self, attrs):
        if attrs["material_type"] == "web" and not attrs.get("url"):
            raise serializers.ValidationError({"url": "A web citation requires its URL."})
        if attrs["material_type"] in {"notes", "slides"} and not attrs.get("lecture_id"):
            raise serializers.ValidationError({"lecture_id": "A lecture citation requires its lecture ID."})
        return attrs


class ChunkNotesRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    lecture_id = serializers.CharField(allow_blank=False)
    date = serializers.DateField(required=False, allow_null=True, default=None)
    overwrite = serializers.BooleanField(required=False, default=False)


class CreateCourseDraftRequestSerializer(serializers.Serializer):
    course_name = serializers.CharField(allow_blank=False)
    course_code = serializers.CharField(required=False, allow_blank=True, max_length=64, default="")
    instructor = serializers.CharField(required=False, allow_blank=True, max_length=150, default="")
    semester = serializers.RegexField(regex=r"^(spring|summer|fall|winter)-\d{4}$", required=False)
    color = serializers.RegexField(regex=r"^#[0-9a-fA-F]{6}$", required=False)


class UpdateCourseRequestSerializer(serializers.Serializer):
    course_name = serializers.CharField(required=False, allow_blank=False)
    course_code = serializers.CharField(required=False, allow_blank=True, max_length=64)
    instructor = serializers.CharField(required=False, allow_blank=True, max_length=150)
    semester = serializers.RegexField(regex=r"^(spring|summer|fall|winter)-\d{4}$", required=False)
    color = serializers.RegexField(regex=r"^#[0-9a-fA-F]{6}$", required=False)
    confirm_semester_move = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not any(key != "confirm_semester_move" for key in attrs):
            raise serializers.ValidationError("At least one course field is required.")
        return attrs


class CourseArchiveSerializer(serializers.Serializer):
    archived = serializers.BooleanField()


class CourseDeleteSerializer(serializers.Serializer):
    confirmation = serializers.CharField(allow_blank=False)


class SyllabusReviewSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()
    syllabus = serializers.JSONField()

    def validate_confirm(self, value):
        if value is not True:
            raise serializers.ValidationError("Explicit confirmation is required.")
        return value


class MaterialDeleteSerializer(serializers.Serializer):
    confirmation = serializers.CharField(allow_blank=False)


class IngestReferenceRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(required=False, allow_blank=True, default=None)


class SavedSiteRequestSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)
    title = serializers.CharField(required=False, allow_blank=True, max_length=255, default=None)

    def validate_url(self, value):
        try:
            return storage.validate_saved_site_url(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))


class ApproveDomainsRequestSerializer(serializers.Serializer):
    # allow_blank=True here deliberately: an empty-string domain is a content
    # problem, not a request-shape problem, so it's left for
    # storage.validate_trusted_domains() to catch and report as 422 rather
    # than being rejected by DRF at the 400 (malformed request) layer.
    domains = serializers.ListField(child=serializers.CharField(allow_blank=True), allow_empty=True)


class GenerateQuestionRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(required=False, allow_blank=False, default=None)
    chunk_id = serializers.CharField(required=False, allow_blank=False, default=None)
    mode = serializers.ChoiceField(required=False, choices=["assessment"], default="assessment")
    question_type = serializers.ChoiceField(
        required=False,
        choices=["multiple_choice", "true_false", "open_ended"],
        default="multiple_choice",
    )
    previous_questions = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_empty=True,
        max_length=15,
        default=list,
    )


class GenerateFlashcardsRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(required=False, allow_blank=False, default=None)
    chunk_id = serializers.CharField(required=False, allow_blank=False, default=None)
    count = serializers.IntegerField(required=False, min_value=1, max_value=12, default=8)
    regenerate = serializers.BooleanField(required=False, default=False)


class FlashcardProgressUpdateSerializer(serializers.Serializer):
    key = serializers.CharField(required=False, allow_blank=False, default=None)
    term = serializers.CharField(allow_blank=False)
    definition = serializers.CharField(allow_blank=False)
    status = serializers.ChoiceField(choices=["mastered", "in_progress", "not_started"])
    starred = serializers.BooleanField(required=False, default=False)


class FlashcardProgressResetSerializer(serializers.Serializer):
    keys = serializers.ListField(child=serializers.CharField(allow_blank=False), allow_empty=True)


class FlashcardReviewRequestSerializer(serializers.Serializer):
    key = serializers.CharField(allow_blank=False)
    rating = serializers.ChoiceField(choices=["again", "hard", "good", "easy"])


class FlashcardSuspendRequestSerializer(serializers.Serializer):
    key = serializers.CharField(allow_blank=False)
    suspended = serializers.BooleanField(required=False, default=True)


class UpdateExamPlanRequestSerializer(serializers.Serializer):
    included_topics = serializers.ListField(
        child=serializers.CharField(allow_blank=False), required=False, allow_null=True, default=None,
    )
    included_material_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False), required=False, allow_null=True, default=None,
    )


class DismissRecommendationRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(allow_blank=False)
    topic = serializers.CharField(allow_blank=False)
    defer_hours = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)


class MasteryInsightRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(required=False, allow_blank=False, default=None)


class StartStudySessionRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(required=False, allow_blank=True, default="")
    duration_minutes = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)
    mode = serializers.ChoiceField(choices=["mixed", "flashcards", "quiz"], required=False, default="mixed")


class RecordStudyActivityRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["flashcard_reviewed", "quiz_answered"],
    )
    payload = serializers.JSONField(required=False, default=dict)


class RecordAttemptRequestSerializer(serializers.Serializer):
    lecture_id = serializers.CharField(allow_blank=False)
    chunk_id = serializers.CharField(allow_blank=False)
    topic = serializers.CharField(allow_blank=False)
    question = serializers.CharField(allow_blank=False)
    correct_answer = serializers.CharField(allow_blank=False)
    user_answer = serializers.CharField(allow_blank=False)


class StartPracticeAttemptRequestSerializer(serializers.Serializer):
    question_count = serializers.IntegerField(required=False, min_value=1, max_value=20, default=10)
    topics = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=255),
        required=False,
        allow_empty=False,
        max_length=50,
    )


class UpdatePracticeAttemptRequestSerializer(serializers.Serializer):
    question_id = serializers.CharField(allow_blank=False)
    user_answer = serializers.CharField(required=False, allow_blank=False)
    flagged = serializers.BooleanField(required=False)
    position = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        if not any(key in attrs for key in ("user_answer", "flagged", "position")):
            raise serializers.ValidationError("Provide an answer, flag state, or position.")
        return attrs


class RateInteractiveFlashcardRequestSerializer(serializers.Serializer):
    card_key = serializers.CharField(allow_blank=False)
    rating = serializers.ChoiceField(choices=["again", "hard", "good", "easy"])


class NavigateInteractiveFlashcardRequestSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=0)


class GradingCategorySerializer(serializers.Serializer):
    component = serializers.CharField(allow_blank=False)
    weight_pct = serializers.FloatField()
    total_items = serializers.IntegerField(required=False, allow_null=True, default=None)
    drop_lowest = serializers.IntegerField(required=False, allow_null=True, default=None)


class GradingConfigRequestSerializer(serializers.Serializer):
    grading = GradingCategorySerializer(many=True)
    grade_scale = serializers.DictField(required=False, allow_null=True, default=None)


class AddGradeItemRequestSerializer(serializers.Serializer):
    component = serializers.CharField(allow_blank=False)
    title = serializers.CharField(allow_blank=False)
    score = serializers.FloatField(min_value=0)
    max_points = serializers.FloatField(min_value=0.01)
    date = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class UpdateGradeItemRequestSerializer(serializers.Serializer):
    component = serializers.CharField(required=False, allow_blank=False, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    score = serializers.FloatField(required=False, min_value=0, default=None)
    max_points = serializers.FloatField(required=False, min_value=0.01, default=None)
    date = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
