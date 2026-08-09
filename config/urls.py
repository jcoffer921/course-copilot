from django.contrib import admin
from django.urls import include, path

from agent.views import course_copilot_page

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agent.urls")),
    path("", course_copilot_page, name="course-copilot"),
]
