"""
ASGI config for course-copilot.

This is the entrypoint to run in dev and prod — e.g.:
    uvicorn config.asgi:application --reload

Do not run this project through wsgi.py; the agent's extraction/ask/quiz
endpoints are async views that call AsyncAnthropic, which needs the ASGI stack
to avoid blocking a worker thread for the duration of each API call.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_application = get_asgi_application()

# django.contrib.staticfiles only auto-serves in DEBUG through manage.py
# runserver's own command, which patches it in behind the scenes — a plain
# ASGI app never gets that patching, so every /static/ request 404s.
# ASGIStaticFilesHandler is Django's own async-native answer to this (avoids
# the sync-iterator warning staticfiles_urlpatterns() in urls.py would print
# under ASGI). Dev-only, same as runserver: a real deploy serves static
# assets via nginx/whitenoise/a CDN, not Django itself.
from django.conf import settings  # noqa: E402

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

    application = ASGIStaticFilesHandler(django_application)
else:
    application = django_application
