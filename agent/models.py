"""Django ORM models for account data and mutable user progress."""

from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    """One row per signed-in user's Google identity and OAuth tokens.

    Looked up by google_sub (Google's stable subject id), not email — a
    later email change on the Google side updates this row rather than
    orphaning the account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()

    def __str__(self):
        return self.email


class UserSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="settings")
    notifications_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class FlashcardProgress(models.Model):
    """Saved study state for generated flashcards.

    The generated deck remains transient. A deterministic card_key lets the
    same term/definition pair pick up its saved status when regenerated.
    """

    STATUS_MASTERED = "mastered"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_CHOICES = [
        (STATUS_MASTERED, "Mastered"),
        (STATUS_IN_PROGRESS, "In Progress"),
    ]

    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="flashcard_progress",
    )
    card_key = models.CharField(max_length=64)
    term = models.TextField(blank=True)
    definition = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    starred = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course_id", "user", "card_key"],
                name="unique_flashcard_progress_per_user",
            )
        ]
        indexes = [
            models.Index(fields=["course_id", "user"]),
        ]

    def __str__(self):
        return f"{self.course_id}:{self.card_key}"


class GradeItem(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="grade_items",
    )
    item_id = models.CharField(max_length=64)
    component = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    score = models.FloatField()
    max_points = models.FloatField()
    date = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["course_id", "user", "item_id"], name="unique_grade_item_per_user")
        ]
        indexes = [models.Index(fields=["course_id", "user"])]


class CalendarSyncRecord(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="calendar_sync_records",
    )
    date = models.CharField(max_length=10)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=32)
    google_event_id = models.CharField(max_length=255)
    synced_at = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["course_id", "user"])]


class CustomEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="custom_events",
    )
    course_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    date = models.CharField(max_length=10)
    time = models.CharField(max_length=5, null=True, blank=True)
    end_time = models.CharField(max_length=5, null=True, blank=True)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=32)
    replaces_syllabus_key = models.CharField(max_length=512, null=True, blank=True)
    completed = models.BooleanField(default=False)
    synced = models.BooleanField(default=False)
    google_event_id = models.CharField(max_length=255, null=True, blank=True)
    synced_at = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "date"], name="agent_custo_user_id_994047_idx"),
            models.Index(fields=["course_id"], name="agent_custo_course__56006f_idx"),
            models.Index(fields=["user", "replaces_syllabus_key"], name="agent_custo_user_id_587bc2_idx"),
        ]


class Notification(models.Model):
    KIND_OVERDUE_DEADLINE = "overdue_deadline"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_key = models.CharField(max_length=255)
    kind = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    course_id = models.CharField(max_length=64, null=True, blank=True)
    deadline_id = models.CharField(max_length=64, null=True, blank=True)
    due_date = models.CharField(max_length=10, null=True, blank=True)
    category = models.CharField(max_length=32, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "notification_key"], name="unique_notification_per_user_key")
        ]
        indexes = [
            models.Index(fields=["user", "read", "created_at"], name="agent_notif_user_id_07b8f0_idx"),
            models.Index(fields=["user", "kind"], name="agent_notif_user_id_8cfca3_idx"),
        ]


class QuizAttempt(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    lecture_id = models.CharField(max_length=64)
    chunk_id = models.CharField(max_length=64)
    topic = models.CharField(max_length=255)
    question = models.TextField()
    correct_answer = models.TextField()
    user_answer = models.TextField()
    correct = models.BooleanField()
    timestamp = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["course_id", "user", "timestamp"])]


class MasteryScore(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="mastery_scores",
    )
    topic = models.CharField(max_length=255)
    score = models.FloatField()
    attempts = models.PositiveIntegerField()
    last_seen = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)
    rebuilt_at = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["course_id", "user", "topic"], name="unique_mastery_score_per_user")
        ]
        indexes = [models.Index(fields=["course_id", "user", "score"])]


class CourseSession(models.Model):
    session_id = models.CharField(max_length=64, unique=True)
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="course_sessions",
    )
    created_at = models.CharField(max_length=64)
    updated_at = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["course_id", "user"])]


class SessionMessage(models.Model):
    session = models.ForeignKey(CourseSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16)
    content = models.TextField()
    timestamp = models.CharField(max_length=64)
    sources = models.JSONField(default=list, blank=True)
    grounded = models.BooleanField(null=True, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_session_message_position")
        ]
        ordering = ["position"]
