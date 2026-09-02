"""Django ORM models for account data and mutable user progress."""

import uuid
from datetime import time

from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    """One row per signed-in user's verified Google identity.

    Looked up by google_sub (Google's stable subject id), not email — a
    later email change on the Google side updates this row rather than
    orphaning the account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()

    def __str__(self):
        return self.email


class GoogleCalendarConnection(models.Model):
    """Optional Calendar authorization, kept separate from sign-in identity."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_calendar_connection",
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
    grant_failed_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


def default_available_study_days():
    return [0, 1, 2, 3, 4, 5, 6]


class UserSettings(models.Model):
    ACCESS_PENDING = "pending"
    ACCESS_ACTIVE = "active"
    ACCESS_SUSPENDED = "suspended"
    ACCESS_STATUS_CHOICES = [
        (ACCESS_PENDING, "Pending"),
        (ACCESS_ACTIVE, "Active"),
        (ACCESS_SUSPENDED, "Suspended"),
    ]

    TIER_PILOT = "pilot"
    TIER_FULL = "full"
    TIER_CHOICES = [
        (TIER_PILOT, "Pilot"),
        (TIER_FULL, "Full"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="settings")
    access_status = models.CharField(max_length=16, choices=ACCESS_STATUS_CHOICES, default=ACCESS_PENDING, db_index=True)
    tier = models.CharField(max_length=16, choices=TIER_CHOICES, default=TIER_PILOT)
    cohort = models.CharField(max_length=100, blank=True, default="")
    notifications_enabled = models.BooleanField(default=False)
    email_notifications_enabled = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="America/New_York")
    preferred_session_minutes = models.PositiveSmallIntegerField(default=45)
    available_study_days = models.JSONField(default=default_available_study_days, blank=True)
    reminder_lead_minutes = models.PositiveSmallIntegerField(default=15)
    study_reminder_time = models.TimeField(default=time(9, 0))
    updated_at = models.DateTimeField(auto_now=True)


class ServiceHeartbeat(models.Model):
    name = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, default="ok")
    detail = models.CharField(max_length=255, blank=True)
    checked_at = models.DateTimeField(auto_now=True)


class PilotFeedback(models.Model):
    CATEGORY_CHOICES = [
        ("bug", "Something is broken"),
        ("confusing", "Something is confusing"),
        ("idea", "Idea or request"),
        ("other", "Other"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="pilot_feedback", null=True, blank=True)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    message = models.TextField(max_length=2000)
    page = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_anonymous(self):
        return self.user_id is None


class ContactRequest(models.Model):
    TOPIC_CHOICES = [
        ("account", "Account or sign-in"),
        ("technical", "Technical problem"),
        ("privacy", "Privacy or data request"),
        ("partnership", "Pilot or partnership"),
        ("other", "Something else"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="contact_requests", null=True, blank=True)
    name = models.CharField(max_length=150)
    email = models.EmailField()
    topic = models.CharField(max_length=20, choices=TOPIC_CHOICES)
    subject = models.CharField(max_length=160)
    message = models.TextField(max_length=4000)
    status = models.CharField(max_length=16, default="new")
    request_id = models.CharField(max_length=80, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProductMetric(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_metrics")
    event = models.CharField(max_length=64, db_index=True)
    course_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["event", "created_at"], name="agent_metric_event_created_idx")]


class CourseMaterial(models.Model):
    """Operational metadata for an owned upload and its processing lifecycle.

    Validated course content remains in the existing per-user JSON store. This
    row tracks the untrusted original, processing state, and review candidate.
    """

    TYPE_SYLLABUS = "syllabus"
    TYPE_NOTES = "notes"
    TYPE_SLIDES = "slides"
    TYPE_REFERENCE = "reference"
    TYPE_CHOICES = [
        (TYPE_SYLLABUS, "Syllabus"),
        (TYPE_NOTES, "Notes"),
        (TYPE_SLIDES, "Slides"),
        (TYPE_REFERENCE, "Reference"),
    ]

    STATUS_UPLOADED = "uploaded"
    STATUS_PROCESSING = "processing"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_UPLOADED, "Uploaded"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_NEEDS_REVIEW, "Needs review"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    REVIEW_PENDING = "pending"
    REVIEW_CONFIRMED = "confirmed"
    REVIEW_NOT_REQUIRED = "not_required"
    REVIEW_SUPERSEDED = "superseded"
    REVIEW_CHOICES = [
        (REVIEW_PENDING, "Pending"),
        (REVIEW_CONFIRMED, "Confirmed"),
        (REVIEW_NOT_REQUIRED, "Not required"),
        (REVIEW_SUPERSEDED, "Superseded"),
    ]

    material_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="course_materials")
    course_id = models.CharField(max_length=64, db_index=True)
    original_filename = models.CharField(max_length=255)
    material_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    source_key = models.CharField(max_length=64, blank=True)
    source_date = models.CharField(max_length=10, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADED)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)
    review_status = models.CharField(max_length=20, choices=REVIEW_CHOICES, default=REVIEW_PENDING)
    storage_key = models.CharField(max_length=96)
    size_bytes = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=128, blank=True)
    extracted_data = models.JSONField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "course_id", "storage_key"], name="unique_material_storage_key")
        ]
        indexes = [
            models.Index(fields=["user", "course_id", "uploaded_at"], name="agent_mater_user_course_idx"),
            models.Index(fields=["user", "processing_status"], name="agent_mater_user_status_idx"),
        ]


class FlashcardProgress(models.Model):
    """Saved study state for generated flashcards.

    Card text is cached (see remember_generated_flashcards), and this row is
    also where spaced-repetition scheduling state lives. A deterministic
    card_key lets the same term/definition pair pick up its saved status when
    regenerated.
    """

    STATUS_MASTERED = "mastered"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_CHOICES = [
        (STATUS_MASTERED, "Mastered"),
        (STATUS_IN_PROGRESS, "In Progress"),
    ]

    RATING_AGAIN = "again"
    RATING_HARD = "hard"
    RATING_GOOD = "good"
    RATING_EASY = "easy"
    RATING_CHOICES = [
        (RATING_AGAIN, "Again"),
        (RATING_HARD, "Hard"),
        (RATING_GOOD, "Good"),
        (RATING_EASY, "Easy"),
    ]

    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="flashcard_progress",
    )
    card_key = models.CharField(max_length=64)
    term = models.TextField(blank=True)
    definition = models.TextField(blank=True)
    topic = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)
    starred = models.BooleanField(default=False)
    suspended = models.BooleanField(default=False)
    last_reviewed = models.DateTimeField(null=True, blank=True)
    next_review = models.DateTimeField(null=True, blank=True)
    rating = models.CharField(max_length=10, choices=RATING_CHOICES, null=True, blank=True)
    interval_days = models.PositiveIntegerField(default=0)
    review_count = models.PositiveIntegerField(default=0)
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
    SOURCE_MANUAL = "manual"
    SOURCE_STUDY_PLAN = "study_plan"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_STUDY_PLAN, "Study plan"),
    ]

    event_id = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_events",
    )
    course_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    date = models.CharField(max_length=10)
    time = models.CharField(max_length=5, null=True, blank=True)
    end_time = models.CharField(max_length=5, null=True, blank=True)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=32)
    location = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    estimated_effort_minutes = models.PositiveIntegerField(null=True, blank=True)
    source_material_id = models.UUIDField(null=True, blank=True)
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
    KIND_STUDY_REMINDER = "study_reminder"
    KIND_CORA_MESSAGE = "cora_message"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
    action_url = models.CharField(max_length=1024, blank=True)
    read = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "notification_key"], name="unique_notification_per_user_key")
        ]
        indexes = [
            models.Index(fields=["user", "read", "created_at"], name="agent_notif_user_id_07b8f0_idx"),
            models.Index(fields=["user", "kind"], name="agent_notif_user_id_8cfca3_idx"),
        ]


class SavedSite(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_sites",
    )
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=2048)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course_id", "user", "url"],
                name="unique_saved_site_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["course_id", "user"], name="agent_saveds_crs_usr_idx"),
        ]


class QuizAttempt(models.Model):
    course_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
        on_delete=models.CASCADE,
        related_name="mastery_scores",
    )
    topic = models.CharField(max_length=255)
    score = models.FloatField()
    attempts = models.PositiveIntegerField()
    last_seen = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32)
    reason = models.CharField(max_length=255, blank=True, default="")
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
        on_delete=models.CASCADE,
        related_name="course_sessions",
    )
    title = models.CharField(max_length=255, default="New chat")
    created_at = models.CharField(max_length=64)
    updated_at = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["course_id", "user"])]


class StudySession(models.Model):
    """One guided study session: flashcards, then quiz, then a summary.

    An append-only StudyActivity stream (below) records what happened during
    the session; this row tracks the session's own setup and lifecycle.
    """

    MODE_MIXED = "mixed"
    MODE_FLASHCARDS = "flashcards"
    MODE_QUIZ = "quiz"
    MODE_CHOICES = [
        (MODE_MIXED, "Mixed"),
        (MODE_FLASHCARDS, "Flashcards only"),
        (MODE_QUIZ, "Quiz only"),
    ]

    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ABANDONED, "Abandoned"),
    ]

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_sessions",
    )
    course_id = models.CharField(max_length=64, db_index=True)
    topic = models.CharField(max_length=255, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_MIXED)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    state = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "course_id", "started_at"], name="agent_studysess_usr_crs_idx"),
        ]


class StudyActivity(models.Model):
    """One append-only event within a StudySession (a card reviewed, a
    question answered, or a lifecycle marker) — never edited in place."""

    KIND_SESSION_STARTED = "session_started"
    KIND_FLASHCARD_REVIEWED = "flashcard_reviewed"
    KIND_QUIZ_ANSWERED = "quiz_answered"
    KIND_SESSION_COMPLETED = "session_completed"
    KIND_CHOICES = [
        (KIND_SESSION_STARTED, "Session started"),
        (KIND_FLASHCARD_REVIEWED, "Flashcard reviewed"),
        (KIND_QUIZ_ANSWERED, "Quiz answered"),
        (KIND_SESSION_COMPLETED, "Session completed"),
    ]

    session = models.ForeignKey(StudySession, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_study_activity_position"),
        ]
        ordering = ["position"]


class SessionMessage(models.Model):
    session = models.ForeignKey(CourseSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16)
    content = models.TextField()
    timestamp = models.CharField(max_length=64)
    sources = models.JSONField(default=list, blank=True)
    grounded = models.BooleanField(null=True, blank=True)
    client_request_id = models.CharField(max_length=64, null=True, blank=True)
    response_metadata = models.JSONField(default=dict, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_session_message_position"),
            models.UniqueConstraint(
                fields=["session", "client_request_id"],
                condition=models.Q(client_request_id__isnull=False),
                name="unique_session_client_request",
            ),
        ]
        ordering = ["position"]


class RecommendationDismissal(models.Model):
    """A student's decision to hide one (course, topic) study recommendation.

    Deliberately separate from Notification: dismissal is temporary/one-shot
    UI state over a *derived* ranking, never a record of anything academic —
    clearing this table can never lose quiz/flashcard/deadline data. A null
    `dismissed_until` means "dismissed" (hidden until explicitly cleared); a
    set value means "deferred" (hidden only until that time).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recommendation_dismissals",
    )
    course_id = models.CharField(max_length=64, db_index=True)
    topic = models.CharField(max_length=255)
    dismissed_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "course_id", "topic"], name="unique_recommendation_dismissal")
        ]


class LlmUsage(models.Model):
    """One row per user per calendar day, counting Anthropic-calling
    requests (not tokens — see agent/services/llm_usage.py) so a daily cap
    can be enforced and inspected without an extra Google/Anthropic
    round-trip."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="llm_usage",
    )
    date = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_llm_usage_per_user_day")
        ]
        indexes = [models.Index(fields=["user", "date"])]


class ExamPlan(models.Model):
    """Mutable plan state layered over one confirmed test_quiz-type calendar
    event — never duplicates the event itself. `event_id` is that event's
    canonical id from calendar_events.py, always re-resolved live against
    the current calendar rather than cached here; a deleted or rescheduled
    event (which changes a syllabus-derived event's id) simply makes this
    row's event_id stop resolving to anything, so the workspace safely
    reports "not found" instead of showing stale data — the row itself is
    left in place rather than requiring cleanup.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exam_plans",
    )
    course_id = models.CharField(max_length=64, db_index=True)
    event_id = models.CharField(max_length=128, db_index=True)
    included_topics = models.JSONField(default=list, blank=True)
    included_material_ids = models.JSONField(default=list, blank=True)
    study_guide = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event_id"], name="unique_exam_plan_per_event")
        ]
        indexes = [
            models.Index(fields=["user", "course_id"], name="agent_examplan_user_course_idx"),
        ]
