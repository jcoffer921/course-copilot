from django.contrib import admin
from django.urls import include, path

from agent.auth_views import google_callback, google_login_page, google_login_start, google_logout
from agent.views import ontrack_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", google_login_page, name="google-login"),
    path("accounts/login/start/", google_login_start, name="google-login-start"),
    path("accounts/callback/", google_callback, name="google-callback"),
    path("accounts/logout/", google_logout, name="google-logout"),
    path("api/", include("agent.urls")),
    path("", ontrack_page, name="ontrack"),
]
