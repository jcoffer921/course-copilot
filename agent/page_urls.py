from django.urls import path

from . import page_views


urlpatterns = [
    path("", page_views.app_root, name="ontrack"),
    path("dashboard/", page_views.dashboard_page, name="dashboard-page"),
    path("calendar/", page_views.calendar_page, name="calendar-page"),
    path("courses/", page_views.courses_page, name="courses-page"),
    path("courses/<slug:course_id>/materials/", page_views.course_materials_page, name="course-materials-page"),
    path("courses/<slug:course_id>/schedule/", page_views.course_schedule_redirect, name="course-schedule-page"),
    path("courses/<slug:course_id>/study/", page_views.course_study_page, name="course-study-page"),
    path("courses/<slug:course_id>/study/quiz/", page_views.practice_quiz_setup_page, name="practice-quiz-setup-page"),
    path("courses/<slug:course_id>/study/quizzes/<str:quiz_id>/attempts/<uuid:attempt_id>/", page_views.practice_attempt_page, name="practice-attempt-page"),
    path("courses/<slug:course_id>/study/flashcards/<slug:deck_id>/", page_views.interactive_flashcards_page, name="interactive-flashcards-page"),
    path("courses/<slug:course_id>/mastery/", page_views.course_mastery_page, name="course-mastery-page"),
    path("courses/<slug:course_id>/grades/", page_views.course_grades_page, name="course-grades-page"),
    path("courses/<slug:course_id>/exams/<slug:exam_id>/", page_views.exam_detail_page, name="exam-detail-page"),
    path("courses/<slug:course_id>/", page_views.course_detail_page, name="course-detail-page"),
    path("cora/", page_views.cora_page, name="cora-page"),
    path("study/", page_views.study_page, name="study-page"),
    path("settings/", page_views.settings_page, name="settings-page"),
]
