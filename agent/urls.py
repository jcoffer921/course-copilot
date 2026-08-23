from django.urls import path

from . import views

urlpatterns = [
    path("profile/", views.UserProfileView.as_view(), name="profile"),
    # slug converter ([-a-zA-Z0-9_]+) rejects "/" and ".." in course_id at the
    # routing layer, before it can reach storage.py as a path segment.
    path("courses/<slug:course_id>/syllabus/extract/", views.ExtractSyllabusView.as_view(), name="extract-syllabus"),
    path("courses/<slug:course_id>/syllabus/", views.SyllabusDetailView.as_view(), name="syllabus-detail"),
    path("courses/<slug:course_id>/notes/chunk/", views.ChunkNotesView.as_view(), name="chunk-notes"),
    path("courses/<slug:course_id>/references/", views.ReferencesView.as_view(), name="references"),
    path("courses/<slug:course_id>/domains/suggest/", views.DomainSuggestionsView.as_view(), name="domains-suggest"),
    path("courses/<slug:course_id>/domains/", views.DomainsView.as_view(), name="domains"),
    path("courses/<slug:course_id>/grading/", views.GradingConfigView.as_view(), name="grading-config"),
    path("courses/<slug:course_id>/calendar-sync/", views.CalendarSyncView.as_view(), name="calendar-sync"),
    path("courses/<slug:course_id>/grades/", views.GradesView.as_view(), name="grades-detail"),
    path("courses/<slug:course_id>/grades/items/", views.GradeItemsView.as_view(), name="grade-items"),
    path("courses/<slug:course_id>/grades/items/<str:item_id>/", views.GradeItemDetailView.as_view(), name="grade-item-detail"),
    path("courses/<slug:course_id>/grades/whatif/", views.GradesWhatIfView.as_view(), name="grades-whatif"),
    path("courses/<slug:course_id>/mastery/", views.MasteryView.as_view(), name="mastery"),
    path("courses/<slug:course_id>/mastery/rebuild/", views.MasteryRebuildView.as_view(), name="mastery-rebuild"),
    path("courses/<slug:course_id>/flashcards/generate/", views.FlashcardsGenerateView.as_view(), name="flashcards-generate"),
    path("courses/<slug:course_id>/flashcards/progress/", views.FlashcardProgressView.as_view(), name="flashcards-progress"),
    path("courses/<slug:course_id>/flashcards/progress/reset/", views.FlashcardProgressResetView.as_view(), name="flashcards-progress-reset"),
    path("courses/<slug:course_id>/quiz/generate/", views.QuizGenerateView.as_view(), name="quiz-generate"),
    path("courses/<slug:course_id>/quiz/record/", views.QuizRecordView.as_view(), name="quiz-record"),
    path("courses/<slug:course_id>/quiz/history/", views.QuizHistoryView.as_view(), name="quiz-history"),
    path("courses/<slug:course_id>/ask/", views.AskView.as_view(), name="ask-course"),
    path("courses/<slug:course_id>/sessions/", views.SessionsView.as_view(), name="sessions-list-create"),
    path(
        "courses/<slug:course_id>/sessions/<slug:session_id>/",
        views.SessionDetailView.as_view(),
        name="session-detail",
    ),
    path("courses/<slug:course_id>/", views.CourseView.as_view(), name="course-detail"),
    path("reminders/", views.RemindersView.as_view(), name="reminders"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("grades/summary/", views.GradesSummaryView.as_view(), name="grades-summary"),
    path("deadlines/", views.DeadlinesView.as_view(), name="deadlines"),
    path("deadlines/<str:event_id>/", views.CustomEventDetailView.as_view(), name="custom-event-detail"),
    path("deadlines/<str:event_id>/calendar-sync/", views.CustomEventCalendarSyncView.as_view(), name="custom-event-calendar-sync"),
    path("notifications/", views.NotificationsView.as_view(), name="notifications"),
    path("notifications/read/", views.NotificationsReadView.as_view(), name="notifications-read"),
]
