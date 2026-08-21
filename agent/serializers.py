from rest_framework import serializers


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
    title = serializers.CharField(allow_blank=False)
    type = serializers.CharField(allow_blank=False)


class UpdateCustomEventRequestSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=False, default=None)
    date = serializers.DateField(required=False, default=None)
    time = serializers.TimeField(required=False, allow_null=True, default=None)
    title = serializers.CharField(required=False, allow_blank=False, default=None)
    type = serializers.CharField(required=False, allow_blank=False, default=None)


class ExtractSyllabusRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    course_name = serializers.CharField(required=False, allow_blank=True, default=None)
    overwrite = serializers.BooleanField(required=False, default=False)


class AskRequestSerializer(serializers.Serializer):
    question = serializers.CharField(allow_blank=False)
    session_id = serializers.CharField(required=False, allow_blank=False, default=None)


class ChunkNotesRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    lecture_id = serializers.CharField(allow_blank=False)
    date = serializers.CharField(required=False, allow_blank=True, default=None)
    overwrite = serializers.BooleanField(required=False, default=False)


class CreateCourseDraftRequestSerializer(serializers.Serializer):
    course_name = serializers.CharField(allow_blank=False)


class IngestReferenceRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(required=False, allow_blank=True, default=None)


class ApproveDomainsRequestSerializer(serializers.Serializer):
    # allow_blank=True here deliberately: an empty-string domain is a content
    # problem, not a request-shape problem, so it's left for
    # storage.validate_trusted_domains() to catch and report as 422 rather
    # than being rejected by DRF at the 400 (malformed request) layer.
    domains = serializers.ListField(child=serializers.CharField(allow_blank=True), allow_empty=True)


class GenerateQuestionRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(required=False, allow_blank=False, default=None)
    chunk_id = serializers.CharField(required=False, allow_blank=False, default=None)


class RecordAttemptRequestSerializer(serializers.Serializer):
    lecture_id = serializers.CharField(allow_blank=False)
    chunk_id = serializers.CharField(allow_blank=False)
    topic = serializers.CharField(allow_blank=False)
    question = serializers.CharField(allow_blank=False)
    correct_answer = serializers.CharField(allow_blank=False)
    user_answer = serializers.CharField(allow_blank=False)


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
