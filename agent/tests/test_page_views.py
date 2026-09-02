from pathlib import Path

import pytest
from django.urls import reverse

from agent.services import storage


@pytest.fixture
def isolated_courses_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "COURSES_DIR", tmp_path)
    return tmp_path


PAGE_CASES = [
    ("dashboard-page", {}, "dashboard"),
    ("calendar-page", {}, "calendar"),
    ("courses-page", {}, "courses"),
    ("course-detail-page", {"course_id": "cs101"}, "course-detail"),
    ("course-materials-page", {"course_id": "cs101"}, "materials"),
    ("course-study-page", {"course_id": "cs101"}, "course-study"),
    ("practice-quiz-setup-page", {"course_id": "cs101"}, "practice-quiz-setup"),
    ("course-mastery-page", {"course_id": "cs101"}, "course-mastery"),
    ("course-grades-page", {"course_id": "cs101"}, "course-grades"),
    ("cora-page", {}, "cora"),
    ("study-page", {}, "study-dashboard"),
    ("exam-detail-page", {"course_id": "cs101", "exam_id": "midterm"}, "exam"),
    ("settings-page", {}, "settings"),
]


@pytest.mark.parametrize(("route_name", "kwargs", "page_name"), PAGE_CASES)
def test_anonymous_users_are_redirected_from_every_page(client, route_name, kwargs, page_name):
    path = reverse(route_name, kwargs=kwargs)
    response = client.get(path)

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('google-login')}?next=")


@pytest.mark.django_db
@pytest.mark.parametrize(("route_name", "kwargs", "page_name"), PAGE_CASES)
def test_authenticated_page_routes_render_one_addressable_section(client, django_user_model, isolated_courses_dir, route_name, kwargs, page_name):
    user = django_user_model.objects.create_user(username=f"user-{page_name}", email=f"{page_name}@example.com")
    if kwargs.get("course_id"):
        storage.write_course_draft(kwargs["course_id"], "Test course", user)
    client.force_login(user)

    response = client.get(reverse(route_name, kwargs=kwargs))
    html = response.content.decode()

    assert response.status_code == 200
    assert f'data-page="{page_name}"' in html
    assert html.count("data-page-section=") == 1
    assert f'data-page-section="{page_name}"' in html


@pytest.mark.django_db
def test_root_redirects_authenticated_user_to_dashboard(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="root-user"))

    response = client.get(reverse("ontrack"))

    assert response.status_code == 302
    assert response.url == reverse("dashboard-page")


@pytest.mark.django_db
def test_sidebar_uses_named_page_routes(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="nav-user"))

    html = client.get(reverse("dashboard-page")).content.decode()

    for route_name in ("dashboard-page", "calendar-page", "courses-page", "cora-page", "study-page", "settings-page"):
        assert f'href="{reverse(route_name)}"' in html


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", ["dashboard-page", "calendar-page", "courses-page", "cora-page", "study-page", "settings-page"])
def test_every_major_page_uses_dashboard_style_navigation_only_sidebar(client, django_user_model, route_name):
    client.force_login(django_user_model.objects.create_user(username=f"sidebar-{route_name}"))

    html = client.get(reverse(route_name)).content.decode()
    sidebar = html[html.index('<aside id="app-sidebar"'):html.index("</aside>")]

    assert 'id="app-sidebar"' in html
    assert 'class="app-course-selector"' not in sidebar
    assert "Upload notes" not in sidebar
    assert "+ Add class" not in sidebar
    for icon_name in ("home", "calendar", "book", "cora", "study", "settings"):
        assert f'href="#ot-icon-{icon_name}"' in html


@pytest.mark.django_db
def test_legacy_flashcards_url_redirects_to_interactive_workspace(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="refresh-user")
    client.force_login(user)
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "CS 101", "dates": [], "grading": [], "topics": ["Recursion"],
    }, user)
    path = reverse("study-page") + "?view=flashcards&course=cs101"

    response = client.get(path)

    assert response.status_code == 302
    assert response.url == reverse("interactive-flashcards-page", kwargs={"course_id": "cs101", "deck_id": "due"})


@pytest.mark.django_db
def test_legacy_quiz_url_redirects_to_modern_quiz_setup(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="legacy-quiz-user")
    client.force_login(user)
    storage.write_course_draft("cs101", "CS 101", user)

    response = client.get(reverse("study-page") + "?view=quiz&course=cs101")

    assert response.status_code == 302
    assert response.url == reverse("practice-quiz-setup-page", kwargs={"course_id": "cs101"})


@pytest.mark.django_db
@pytest.mark.parametrize("legacy_view", ["quiz", "flashcards"])
def test_course_less_legacy_study_urls_redirect_to_dashboard(client, django_user_model, legacy_view):
    client.force_login(django_user_model.objects.create_user(username=f"legacy-{legacy_view}-user"))

    response = client.get(reverse("study-page") + f"?view={legacy_view}")

    assert response.status_code == 302
    assert response.url == reverse("study-page")


@pytest.mark.django_db
def test_legacy_quiz_and_flashcard_markup_is_not_rendered(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="no-legacy-study-ui"))

    html = client.get(reverse("study-page") + "?view=progress").content.decode()

    for legacy_hook in (
        'id="study-subnav-quiz"', 'id="study-subnav-flashcards"',
        "Set up your quiz", "All Cards", "flashcard-stage",
    ):
        assert legacy_hook not in html


@pytest.mark.django_db
def test_course_study_page_only_links_to_new_study_experiences(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="modern-study-links")
    storage.write_course_draft("cs101", "CS 101", user)
    client.force_login(user)

    html = client.get(reverse("course-study-page", kwargs={"course_id": "cs101"})).content.decode()

    assert reverse("interactive-flashcards-page", kwargs={"course_id": "cs101", "deck_id": "due"}) in html
    assert reverse("practice-quiz-setup-page", kwargs={"course_id": "cs101"}) in html
    assert 'id="practice-quiz"' in html
    assert "view=quiz" not in html
    assert "view=flashcards" not in html


@pytest.mark.django_db
def test_practice_quiz_setup_renders_only_the_modern_quiz_launcher(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="quiz-setup-user")
    storage.write_syllabus("cs101", {
        "course_id": "cs101", "course_name": "Data Structures", "dates": [], "grading": [], "topics": ["Trees"],
    }, user)
    client.force_login(user)

    response = client.get(reverse("practice-quiz-setup-page", kwargs={"course_id": "cs101"}))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'data-page-section="practice-quiz-setup"' in html
    assert 'id="qs-form"' in html
    assert 'id="qs-count"' in html
    assert 'id="qs-decrement"' in html
    assert 'id="qs-increment"' in html
    assert 'data-count="20"' in html
    assert 'id="qs-scope"' in html
    assert 'id="qs-topic"' in html
    assert 'id="qs-start"' in html
    assert 'agent/js/practice_quiz_setup.js?v=quiz-loading-20260831-1' in html
    assert 'id="qs-generation-overlay"' in html
    assert 'id="qs-generation-status"' in html
    assert html.count('data-generation-step=') == 5
    assert "Reading course materials" in html
    assert "Generating questions" in html
    sidebar = html[html.index('<aside id="app-sidebar"'):html.index("</aside>")]
    assert f'href="{reverse("study-page")}" class="app-nav-link active"' in sidebar
    assert f'href="{reverse("dashboard-page")}" class="app-nav-link active"' not in sidebar
    assert "Grounded in your course materials" in html
    assert "Not enough course material yet" in html
    assert "view=quiz" not in html
    for legacy_overlay_token in (
        "{{ deadlineDate }}", "{{ deadlineTime }}", "{{ deadlineEndTime }}",
        "{{ deadlineEstimatedEffort }}", "{{ closeUpload }}",
    ):
        assert legacy_overlay_token not in html


@pytest.mark.django_db
def test_study_page_embeds_topic_from_recommendation_link(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="topic-prefill-user"))
    path = reverse("study-page") + "?view=session&course=cs101&topic=Recursion"

    html = client.get(path).content.decode()

    assert 'window.ONTRACK_INITIAL_TAB = "session"' in html
    assert 'window.ONTRACK_INITIAL_COURSE = "cs101"' in html
    assert 'window.ONTRACK_INITIAL_TOPIC = "Recursion"' in html


@pytest.mark.django_db
def test_study_topic_query_param_is_escaped_not_executable(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="topic-escape-user"))
    path = reverse("study-page") + '?topic=</script><script>alert(1)</script>'

    html = client.get(path).content.decode()

    assert "<script>alert(1)</script>" not in html


@pytest.mark.django_db
def test_exam_detail_page_renders_workspace_hooks(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="exam-page-user")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)

    response = client.get(reverse("exam-detail-page", kwargs={"course_id": "cs101", "exam_id": "midterm"}))
    html = response.content.decode()

    assert response.status_code == 200
    for hook in ('id="exam-loading"', 'id="exam-topics"', 'id="exam-materials"', 'id="exam-generate-guide"', 'id="exam-practice-start"'):
        assert hook in html
    assert 'data-exam-id="midterm"' in html
    assert 'src="/static/agent/js/exams.js"' in html


@pytest.mark.django_db
def test_cora_page_embeds_initial_question_from_dashboard_quick_entry(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="cora-prefill-user"))
    path = reverse("cora-page") + "?q=What is a linked list?"

    html = client.get(path).content.decode()

    assert 'window.ONTRACK_INITIAL_QUESTION = "What is a linked list?"' in html
    for hook in ('id="cora-grid"', 'id="cora-course-select"', 'id="cora-session-list"', 'id="cora-messages"', 'id="cora-source-panel"', 'id="cora-composer"', 'id="cora-material-picker"', 'id="cora-grounding-mode"'):
        assert hook in html
    assert 'href="#ot-icon-paperclip"' in html
    assert 'src="/static/agent/js/cora.js"' in html
    assert 'src="/static/agent/support.js"' not in html


@pytest.mark.django_db
def test_cora_question_query_param_is_escaped_not_executable(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="cora-escape-user"))
    path = reverse("cora-page") + '?q=</script><script>alert(1)</script>'

    html = client.get(path).content.decode()

    assert "<script>alert(1)</script>" not in html


@pytest.mark.django_db
def test_dashboard_renders_all_mockup_sections(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="dashboard-sections-user", first_name="Jason"))

    html = client.get(reverse("dashboard-page")).content.decode()

    for hook in (
        'id="dash-next-deadline-link"', 'id="dash-next-exam-link"', 'id="dash-streak-week"',
        'id="dash-plan-list"', 'id="dash-recommendation-title"', 'id="dash-recommendation-start"',
        'id="dash-courses-grid"', 'id="dash-deadlines-list"', 'id="dash-cora-form"',
        'id="dash-notification-toggle"', 'id="dash-notification-popover"', 'id="dash-courses-empty"',
    ):
        assert hook in html
    assert ", Jason</h1>" in html
    assert 'data-timezone="America/New_York"' in html
    assert "cora-dashboard.png" in html
    for icon_name in ("bell", "calendar", "pencil", "flame"):
        assert f'href="#ot-icon-{icon_name}"' in html
    assert "▣" not in html
    assert "♨" not in html
    assert 'src="/static/agent/js/dashboard.js"' in html


@pytest.mark.django_db
def test_study_session_view_renders_guided_session_panel_visibly(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="guided-session-user"))

    html = client.get(reverse("study-page") + "?view=session").content.decode()

    assert 'window.ONTRACK_INITIAL_TAB = "session"' in html
    assert 'id="guided-session-root"' in html
    assert 'id="guided-session-setup"' in html
    assert 'id="guided-plan-list"' in html
    assert 'id="guided-plan-source-list"' in html
    assert "Generated from your sources" in html
    assert 'src="/static/agent/js/study.js"' in html


def test_guided_quiz_centers_copy_and_ignores_stale_question_responses():
    root = Path(__file__).resolve().parents[2]
    controller = (root / "agent/static/agent/js/study.js").read_text(encoding="utf-8")
    styles = (root / "agent/static/agent/css/guided_study.css").read_text(encoding="utf-8")

    assert "questionRequestId" in controller
    assert "requestId !== state.questionRequestId" in controller
    assert "state.questionLoading || !state.session" in controller
    assert "state.sessionTransitioning" in controller
    assert ".guided-quiz-step{align-items:center}" in styles
    assert ".guided-step-copy{width:min(760px,100%);margin-inline:auto;text-align:center}" in styles


@pytest.mark.django_db
def test_unsafe_query_course_is_not_embedded_as_application_state(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="safe-course-user"))

    html = client.get(reverse("cora-page"), {"course": "../../private"}).content.decode()

    assert 'window.ONTRACK_INITIAL_COURSE = "all"' in html
    assert "../../private" not in html


def test_existing_api_route_names_are_unchanged():
    assert reverse("dashboard") == "/api/dashboard/"
    assert reverse("deadlines") == "/api/deadlines/"
    assert reverse("ask-course", kwargs={"course_id": "cs101"}) == "/api/courses/cs101/ask/"
    assert reverse("quiz-generate", kwargs={"course_id": "cs101"}) == "/api/courses/cs101/quiz/generate/"


@pytest.mark.django_db
def test_calendar_page_uses_page_owned_runtime_only(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="module-user"))

    html = client.get(reverse("calendar-page")).content.decode()

    assert 'src="/static/agent/js/calendar.js?v=calendar-20260902-1"' in html
    assert 'src="/static/agent/support.js"' not in html
    assert "class Component extends window.createOnTrackComponent(DCLogic)" not in html
    assert "{{ deadlineDate }}" not in html
    assert "function readJsonResponse" not in html


@pytest.mark.django_db
def test_exam_and_settings_pages_use_native_runtime_and_accessible_dialogs(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="native-pages", email="native@example.com")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)

    exam_html = client.get(reverse("exam-detail-page", kwargs={"course_id": "cs101", "exam_id": "midterm"})).content.decode()
    settings_html = client.get(reverse("settings-profile-page")).content.decode()

    for html in (exam_html, settings_html):
        assert 'src="/static/agent/support.js"' not in html
        assert "data-dc-script" not in html
    assert 'id="exam-topics-dialog" class="settings-dialog-backdrop" hidden' in exam_html
    assert 'role="dialog" aria-modal="true"' in exam_html
    assert 'id="ontrack-action-dialog"' in settings_html
    assert 'id="profile-form"' in settings_html
    assert 'aria-current="page"' in settings_html
    for icon_name in ("profile", "clock", "bell", "link", "shield"):
        assert f'href="#ot-icon-{icon_name}"' in settings_html

    notification_html = client.get(reverse("settings-notifications-page")).content.decode()
    assert 'id="notifications-form"' in notification_html
    assert 'id="settings-reminder-time" type="time"' in notification_html

    data_html = client.get(reverse("settings-data-page")).content.decode()
    assert 'href="/api/profile/export/"' in data_html
    assert 'id="export"' in data_html


@pytest.mark.django_db
@pytest.mark.parametrize("route_name,heading", [
    ("settings-profile-page", "Profile information"),
    ("settings-account-page", "Account &amp; security"),
    ("settings-preferences-page", "Preferences"),
    ("settings-notifications-page", "Notifications"),
    ("settings-privacy-page", "Privacy"),
    ("settings-apps-page", "Connected apps"),
    ("settings-subscription-page", "Subscription"),
    ("settings-data-page", "Data &amp; storage"),
])
def test_settings_nested_routes_require_auth_and_render_active_view(client, django_user_model, route_name, heading):
    url = reverse(route_name)
    anonymous = client.get(url)
    assert anonymous.status_code == 302
    assert anonymous.url.startswith("/accounts/login/")

    client.force_login(django_user_model.objects.create_user(username=f"user-{route_name}"))
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert heading in html
    assert 'class="active" aria-current="page"' in html
    assert 'class="app-nav-link active" aria-current="page"' in html


@pytest.mark.django_db
def test_calendar_page_renders_week_month_filters_and_accessible_dialogs(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="calendar-page-user"))
    html = client.get(reverse("calendar-page") + "?view=month&date=2026-08-24").content.decode()
    for hook in ('id="cal-week"', 'id="cal-month"', 'id="mini-grid"', 'id="cal-course-filters"',
                 'id="cal-type-filters"', 'id="cal-event-modal"', 'id="cal-delete-modal"'):
        assert hook in html
    assert 'role="dialog" aria-modal="true"' in html
    assert 'id="cal-event-modal" hidden' in html
    assert 'id="cal-delete-modal" hidden' in html
    assert 'data-calendar-api="/api/calendar/"' in html
    assert 'src="/static/agent/js/calendar.js?v=calendar-20260902-1"' in html

    controller = (Path(__file__).parents[1] / "static/agent/js/calendar.js").read_text(encoding="utf-8")
    assert '$("#cal-week").hidden = state.view !== "week"' in controller
    assert '$("#cal-month").hidden = state.view !== "month"' in controller


@pytest.mark.django_db
def test_calendar_page_renders_hidden_reconnect_banner(client, django_user_model):
    """The banner exists but stays hidden until calendar.js's profile fetch
    finds calendar_connected is false — see loadCalendarConnectionBanner()."""
    client.force_login(django_user_model.objects.create_user(username="calendar-banner-user"))

    html = client.get(reverse("calendar-page")).content.decode()

    assert 'id="cal-reconnect-banner" hidden' in html
    assert 'href="/accounts/calendar/connect/"' in html


@pytest.mark.django_db
def test_courses_page_uses_page_owned_runtime_and_accessible_closed_dialogs(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="courses-page-user"))

    html = client.get(reverse("courses-page")).content.decode()

    for hook in ('id="courses-semester"', 'id="courses-grid"', 'id="course-form"',
                 'id="course-archive-backdrop"', 'id="course-delete-backdrop"'):
        assert hook in html
    assert 'id="course-form-backdrop" class="courses-modal-backdrop" hidden' in html
    assert 'id="course-archive-backdrop" class="courses-modal-backdrop" hidden' in html
    assert 'id="course-delete-backdrop" class="courses-modal-backdrop" hidden' in html
    assert 'class="courses-account-row"' in html
    assert 'class="courses-controls-row"' in html
    assert 'class="courses-empty" hidden><h2' in html
    assert 'src="/static/agent/js/courses.js?v=courses-20260826-2"' in html
    assert 'href="/static/agent/css/app.css?v=courses-20260826-2"' in html
    assert 'src="/static/agent/support.js"' not in html
    assert "class Component extends window.createOnTrackComponent(DCLogic)" not in html


@pytest.mark.django_db
def test_course_detail_page_renders_header_subnav_and_overview_grid(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="course-detail-user")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)

    response = client.get(reverse("course-detail-page", kwargs={"course_id": "cs101"}))
    html = response.content.decode()

    assert response.status_code == 200
    for hook in (
        'id="course-header"', 'id="course-header-avatar"',
        'id="course-overview-grid"', 'id="course-overview-loading"', 'id="course-overview-error"',
        'id="ov-card-priority"', 'id="ov-card-materials"', 'id="ov-card-study"',
        'id="ov-card-mastery"', 'id="ov-card-grades"', 'id="ov-card-schedule"', 'id="ov-card-cora"',
    ):
        assert hook in html
    assert "Overview isn't built yet" not in html
    assert "{{ courseName }}" not in html
    assert "showDashboardLoading" not in html
    assert 'src="/static/agent/js/course_overview.js?v=workspace-20260826-3"' in html
    assert 'src="/static/agent/support.js"' not in html


@pytest.mark.django_db
def test_course_workspace_has_complete_subnav_without_schedule(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="workspace-nav-user")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)

    html = client.get(reverse("course-materials-page", kwargs={"course_id": "cs101"})).content.decode()

    for label in ("Overview", "Materials", "Study", "Mastery", "Grades"):
        assert f">{label}</a>" in html
    assert ">Schedule</a>" not in html
    assert 'aria-current="page">Materials</a>' in html


@pytest.mark.django_db
def test_course_schedule_redirects_to_owned_filtered_calendar(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="schedule-owner")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)
    response = client.get(reverse("course-schedule-page", kwargs={"course_id": "cs101"}), {"date": "2026-08-26", "view": "month", "unsafe": "ignored"})
    assert response.status_code == 302
    assert response.url == "/calendar/?date=2026-08-26&view=month&course=cs101"


def test_anonymous_course_schedule_redirect_requires_login(client):
    response = client.get(reverse("course-schedule-page", kwargs={"course_id": "cs101"}))
    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('google-login')}?next=")


@pytest.mark.django_db
def test_course_schedule_redirect_hides_foreign_course(client, django_user_model, isolated_courses_dir):
    owner = django_user_model.objects.create_user(username="schedule-private-owner")
    viewer = django_user_model.objects.create_user(username="schedule-private-viewer")
    storage.write_course_draft("private", "Private", owner)
    client.force_login(viewer)
    assert client.get(reverse("course-schedule-page", kwargs={"course_id": "private"})).status_code == 404


@pytest.mark.django_db
def test_course_overview_keeps_filtered_global_schedule_preview_link(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="overview-schedule-link")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)
    html = client.get(reverse("course-detail-page", kwargs={"course_id": "cs101"})).content.decode()
    assert 'href="/calendar/?course=cs101">View full schedule' in html


@pytest.mark.django_db
def test_materials_page_renders_review_upload_and_library_states(client, django_user_model, isolated_courses_dir):
    user = django_user_model.objects.create_user(username="materials-page-user")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)

    response = client.get(reverse("course-materials-page", kwargs={"course_id": "cs101"}))
    html = response.content.decode()

    assert response.status_code == 200
    for hook in (
        'id="syllabus-upload-form"',
        'id="lecture-upload-form"',
        'id="reference-upload-form"',
        'id="syllabus-review"',
        'id="materials-loading"',
        'id="materials-empty"',
        'id="materials-error"',
    ):
        assert hook in html
    assert 'src="/static/agent/js/materials.js?v=workspace-20260826-3"' in html
    assert 'src="/static/agent/support.js"' not in html


@pytest.mark.django_db
@pytest.mark.parametrize(("route_name", "page_name", "active_label"), [
    ("course-study-page", "course-study", "Study"),
    ("course-mastery-page", "course-mastery", "Mastery"),
    ("course-grades-page", "course-grades", "Grades"),
])
def test_course_learning_pages_use_native_runtime_and_active_tab(client, django_user_model, isolated_courses_dir, route_name, page_name, active_label):
    user = django_user_model.objects.create_user(username=f"learning-{page_name}")
    storage.write_course_draft("cs101", "Test course", user)
    client.force_login(user)
    html = client.get(reverse(route_name, kwargs={"course_id": "cs101"})).content.decode()
    assert f'data-page-section="{page_name}"' in html
    assert f'aria-current="page">{active_label}</a>' in html
    assert 'src="/static/agent/support.js"' not in html
    assert ">Schedule</a>" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("route_name,kwargs", [
    ("course-detail-page", {"course_id": "private"}),
    ("course-materials-page", {"course_id": "private"}),
    ("course-study-page", {"course_id": "private"}),
    ("practice-quiz-setup-page", {"course_id": "private"}),
    ("course-mastery-page", {"course_id": "private"}),
    ("course-grades-page", {"course_id": "private"}),
    ("exam-detail-page", {"course_id": "private", "exam_id": "midterm"}),
])
def test_course_workspace_pages_hide_foreign_courses(client, django_user_model, isolated_courses_dir, route_name, kwargs):
    owner = django_user_model.objects.create_user(username=f"owner-{route_name}")
    viewer = django_user_model.objects.create_user(username=f"viewer-{route_name}")
    storage.write_course_draft("private", "Private course", owner)
    client.force_login(viewer)

    response = client.get(reverse(route_name, kwargs=kwargs))

    assert response.status_code == 404
