from pathlib import Path

import pytest
from django.urls import reverse

from agent.models import UserSettings


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", [
    "dashboard-page",
    "courses-page",
    "settings-page",
    "study-page",
])
def test_authenticated_pages_use_one_shared_notification_center(client, django_user_model, route_name):
    user = django_user_model.objects.create_user(username=f"notifications-{route_name}")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    client.force_login(user)

    html = client.get(reverse(route_name)).content.decode()

    assert html.count('id="site-notification-toggle"') == 1
    assert html.count('id="site-notification-popover"') == 1
    sidebar = html[html.index('<aside id="app-sidebar"'):html.index("</aside>")]
    assert 'id="site-notifications"' not in sidebar
    assert html.index('id="site-notifications"') > html.index('<div class="app-main">')
    assert 'agent/js/core/notifications.js' in html
    assert 'agent/css/notifications.css' in html
    assert 'id="dash-notification-toggle"' not in html
    assert 'id="courses-notification-toggle"' not in html


@pytest.mark.django_db
def test_calendar_page_does_not_render_notification_center(client, django_user_model):
    user = django_user_model.objects.create_user(username="calendar-without-notifications")
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    client.force_login(user)

    html = client.get(reverse("calendar-page")).content.decode()

    assert 'id="site-notifications"' not in html
    assert 'id="site-notification-toggle"' not in html


def test_shared_notification_controller_owns_complete_behavior():
    root = Path(__file__).resolve().parents[2]
    controller = (root / "agent/static/agent/js/core/notifications.js").read_text(encoding="utf-8")
    dashboard = (root / "agent/static/agent/js/dashboard.js").read_text(encoding="utf-8")
    courses = (root / "agent/static/agent/js/courses.js").read_text(encoding="utf-8")

    assert 'apiRequest("/api/notifications/")' in controller
    assert 'apiRequest("/api/notifications/read/"' in controller
    assert "data-notification-id" in controller
    assert 'event.target.closest("#site-notifications-read")' in controller
    assert 'event.key === "Escape"' in controller
    assert "/api/notifications/" not in dashboard
    assert "/api/notifications/" not in courses
