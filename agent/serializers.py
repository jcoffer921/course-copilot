from rest_framework import serializers


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
