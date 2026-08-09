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

application = get_asgi_application()
