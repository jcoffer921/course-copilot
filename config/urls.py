from django.contrib import admin
from django.urls import include, path

from agent.auth_views import (
    google_calendar_callback,
    google_calendar_connect,
    google_calendar_disconnect,
    google_callback,
    google_login_page,
    google_login_start,
    google_logout,
    pending_access_page,
)
from agent.health_views import health
urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("accounts/login/", google_login_page, name="google-login"),
    path("accounts/login/start/", google_login_start, name="google-login-start"),
    path("accounts/callback/", google_callback, name="google-callback"),
    path("accounts/pending/", pending_access_page, name="pending-page"),
    path("accounts/calendar/connect/", google_calendar_connect, name="google-calendar-connect"),
    path("accounts/calendar/callback/", google_calendar_callback, name="google-calendar-callback"),
    path("accounts/calendar/disconnect/", google_calendar_disconnect, name="google-calendar-disconnect"),
    path("accounts/logout/", google_logout, name="google-logout"),
    path("api/", include("agent.urls")),
    path("", include("agent.page_urls")),
]
