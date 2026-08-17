from django.contrib import admin
from django.urls import include, path

from agent.views import ontrack_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agent.urls")),
    path("", ontrack_page, name="ontrack"),
]
