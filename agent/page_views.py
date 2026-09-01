"""Authenticated browser pages for the OnTrack application shell."""

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode
from zoneinfo import available_timezones

from .services import storage
from .services import interactive_study
from .services.study_sessions import StudySessionNotFoundError
from .services.storage import COURSE_ID_RE


PAGE_SCRIPTS = {
    "dashboard": "agent/js/dashboard.js",
    "calendar": "agent/js/calendar.js",
    "courses": "agent/js/courses.js",
    "course-detail": "agent/js/course_overview.js",
    "materials": "agent/js/materials.js",
    "course-study": "agent/js/course_study.js",
    "practice-quiz-setup": "agent/js/practice_quiz_setup.js",
    "course-mastery": "agent/js/course_mastery.js",
    "course-grades": "agent/js/course_grades.js",
    "cora": "agent/js/cora.js",
    "study-dashboard": "agent/js/study_dashboard.js",
    "study": "agent/js/study.js",
    "exam": "agent/js/exams.js",
    "settings": "agent/js/settings.js",
    "practice-attempt": "agent/js/practice_attempt.js",
    "interactive-flashcards": "agent/js/interactive_flashcards.js",
}


def _safe_initial_course(request, course_id=None):
    candidate = course_id or request.GET.get("course", "")
    return candidate if candidate and COURSE_ID_RE.fullmatch(candidate) else "all"


def _safe_initial_topic(request):
    # Topic names are free text (not a slug like course_id), so this can't
    # be validated against a strict pattern — capped length plus the
    # template's `|escapejs` is what keeps it safe to embed as a JS string.
    return request.GET.get("topic", "")[:255]


def _safe_initial_question(request):
    # Same reasoning as _safe_initial_topic: free text, capped length,
    # relies on the template's `|escapejs` for safe embedding.
    return request.GET.get("q", "")[:500]


def _identity_context(user):
    display_name = (user.get_full_name() or user.first_name or user.email or user.username).strip()
    first_name = display_name.split()[0] if display_name else "there"
    words = display_name.split()
    initials = "".join(word[0] for word in words[:2]).upper() or "OT"
    return {"display_name": display_name, "first_name": first_name, "user_initials": initials}


def _render_page(request, template_name, *, page_name, page_title, initial_tab, course_id=None, **context):
    modern_page_names = {
        "calendar", "courses", "cora", "course-detail", "materials", "course-study",
        "course-mastery", "course-grades", "study-dashboard", "exam", "settings",
        "practice-quiz-setup", "practice-attempt", "interactive-flashcards",
    }
    modern_shell = page_name in modern_page_names or (page_name == "study" and initial_tab == "session")
    return render(
        request,
        template_name,
        {
            "page_name": page_name,
            "page_title": page_title,
            "initial_tab": initial_tab,
            "modern_shell": modern_shell,
            "initial_course_id": _safe_initial_course(request, course_id),
            "page_script": PAGE_SCRIPTS[page_name],
            "page_asset_version": (
                "calendar-20260826-4" if page_name == "calendar"
                else "courses-20260826-2" if page_name == "courses"
                else "workspace-20260826-3" if page_name in ("materials", "course-detail", "course-study", "course-mastery", "course-grades", "study-dashboard")
                else "quiz-loading-20260831-1" if page_name == "practice-quiz-setup"
                else "interactive-20260831-4" if page_name in ("practice-attempt", "interactive-flashcards")
                else ""
            ),
            "course_id": course_id,
            **_identity_context(request.user),
            **context,
        },
    )


def _require_owned_course(request, course_id):
    """Keep existence and ownership indistinguishable at browser-page boundaries."""
    if not storage.course_or_draft_exists(course_id, request.user):
        raise Http404("Course not found.")


@login_required
def app_root(request):
    return redirect("dashboard-page")


@login_required
def dashboard_page(request):
    hour = timezone.localtime().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    return _render_page(
        request, "agent/dashboard.html", page_name="dashboard", page_title="Dashboard",
        initial_tab="dashboard", dashboard_greeting=greeting, dashboard_timezone=settings.TIME_ZONE,
    )


@login_required
def calendar_page(request):
    return _render_page(request, "agent/calendar.html", page_name="calendar", page_title="Calendar", initial_tab="deadlines")


@login_required
def courses_page(request):
    return _render_page(request, "agent/courses/list.html", page_name="courses", page_title="Courses", initial_tab="dashboard")


@login_required
def course_detail_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/courses/detail.html", page_name="course-detail", page_title="Course workspace", initial_tab="dashboard", course_id=course_id)


@login_required
def course_materials_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/courses/materials.html", page_name="materials", page_title="Course materials", initial_tab="dashboard", course_id=course_id)


@login_required
def course_study_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/courses/study.html", page_name="course-study", page_title="Course study", initial_tab="dashboard", course_id=course_id)


@login_required
def practice_quiz_setup_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(
        request, "agent/study/practice_quiz_setup.html", page_name="practice-quiz-setup",
        page_title="Set up practice quiz", initial_tab="study", course_id=course_id,
    )


@login_required
def course_mastery_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/courses/mastery.html", page_name="course-mastery", page_title="Course mastery", initial_tab="dashboard", course_id=course_id)


@login_required
def course_schedule_redirect(request, course_id):
    _require_owned_course(request, course_id)
    safe = {key: request.GET[key] for key in ("date", "event", "view") if request.GET.get(key) and len(request.GET[key]) <= 100}
    safe["course"] = course_id
    return redirect(f"{reverse('calendar-page')}?{urlencode(safe)}")


@login_required
def course_grades_page(request, course_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/courses/grades.html", page_name="course-grades", page_title="Course grades", initial_tab="dashboard", course_id=course_id)


@login_required
def cora_page(request):
    return _render_page(
        request, "agent/cora.html", page_name="cora", page_title="Ask Cora", initial_tab="chat",
        initial_question=_safe_initial_question(request),
    )


@login_required
def study_page(request):
    requested_view = request.GET.get("view")
    if not requested_view:
        return _render_page(request, "agent/study_dashboard.html", page_name="study-dashboard", page_title="Study", initial_tab="dashboard")
    if requested_view in {"flashcards", "quiz"}:
        course_id = request.GET.get("course", "")
        if not course_id:
            return redirect("study-page")
        if not COURSE_ID_RE.fullmatch(course_id):
            raise Http404("Course not found.")
        _require_owned_course(request, course_id)
        if requested_view == "flashcards":
            return redirect("interactive-flashcards-page", course_id=course_id, deck_id="due")
        return redirect("practice-quiz-setup-page", course_id=course_id)
    initial_tab = requested_view if requested_view in {"progress", "grades", "session"} else "progress"
    return _render_page(
        request, "agent/study.html", page_name="study", page_title="Study", initial_tab=initial_tab,
        initial_topic=_safe_initial_topic(request),
    )


@login_required
def exam_detail_page(request, course_id, exam_id):
    _require_owned_course(request, course_id)
    return _render_page(request, "agent/exams/detail.html", page_name="exam", page_title="Exam workspace", initial_tab="dashboard", course_id=course_id, exam_id=exam_id)


@login_required
def practice_attempt_page(request, course_id, quiz_id, attempt_id):
    _require_owned_course(request, course_id)
    try:
        attempt = interactive_study.practice_detail(request.user, course_id, attempt_id)
    except StudySessionNotFoundError as exc:
        raise Http404("Practice attempt not found.") from exc
    if attempt["quiz_id"] != quiz_id:
        raise Http404("Practice attempt not found.")
    return _render_page(
        request, "agent/study/practice_attempt.html", page_name="practice-attempt",
        page_title=attempt["title"], initial_tab="study", course_id=course_id,
        quiz_id=quiz_id, attempt_id=attempt_id, course_practice=quiz_id == "course-practice",
    )


@login_required
def interactive_flashcards_page(request, course_id, deck_id):
    _require_owned_course(request, course_id)
    return _render_page(
        request, "agent/study/interactive_flashcards.html", page_name="interactive-flashcards",
        page_title="Flashcards", initial_tab="study", course_id=course_id, deck_id=deck_id,
    )


@login_required
def settings_page(request):
    return _render_page(
        request, "agent/settings.html", page_name="settings", page_title="Settings", initial_tab="dashboard",
        timezone_choices=sorted(available_timezones()),
    )
