"""
WSGI config for course-copilot.

NOT used to run this project — the agent endpoints are async and require ASGI.
This file exists only because some tooling expects it. Run via asgi.py instead:
    uvicorn config.asgi:application --reload
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
