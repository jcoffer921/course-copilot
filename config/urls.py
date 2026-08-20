from django.contrib import admin
from django.urls import include, path

from agent.auth_views import google_callback, google_login, google_logout
from agent.views import ontrack_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", google_login, name="google-login"),
    path("accounts/callback/", google_callback, name="google-callback"),
    path("accounts/logout/", google_logout, name="google-logout"),
    path("api/", include("agent.urls")),
    path("", ontrack_page, name="ontrack"),
]
