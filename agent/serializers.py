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


class IngestReferenceRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(required=False, allow_blank=True, default=None)


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
