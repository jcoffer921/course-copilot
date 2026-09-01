import os
from pathlib import Path

import truststore
truststore.inject_into_ssl()

BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me-before-any-real-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

if not DEBUG:
    if SECRET_KEY == "dev-insecure-key-change-me-before-any-real-deploy":
        raise ValueError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
    if os.environ.get("DJANGO_TRUST_PROXY_SSL_HEADER", "false").lower() == "true":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# oauthlib refuses to exchange tokens over a non-HTTPS redirect URI (e.g. the
# plan's own http://127.0.0.1:8031/accounts/callback/ for local dev), raising
# InsecureTransportError. Only ever set this when DEBUG is on, so it can
# never weaken a real deploy.
if DEBUG:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "adrf",
    "agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "agent.middleware.RequestLoggingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "config.asgi.application"
# WSGI_APPLICATION is kept only so manage.py / third-party tooling that expects
# it don't break. Actually run this project via an ASGI server (uvicorn/daphne),
# not through wsgi.py — the agent endpoints are async and need the ASGI stack.
WSGI_APPLICATION = "config.wsgi.application"

# sqlite here backs ONLY Django's own auth/session/admin tables.
# Course content (syllabus.json, notes, quiz_history) lives in courses/*.json
# on disk per CLAUDE.md — this is a single-user project, no DB needed for that.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Used by @login_required (added to ontrack_page in Task 4) to know where
# to send an anonymous visitor — the URL name defined in config/urls.py.
LOGIN_URL = "google-login"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["agent.authentication.SessionAuthenticationWith401"],
    "DEFAULT_THROTTLE_RATES": {
        "ai_burst": os.environ.get("ONTRACK_AI_BURST_RATE", "8/min"),
        "ai_daily": os.environ.get("ONTRACK_AI_DAILY_RATE", "100/day"),
    },
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "true").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "OnTrack <reminders@ontrack.local>")
ONTRACK_SUPPORT_EMAIL = os.environ.get("ONTRACK_SUPPORT_EMAIL", EMAIL_HOST_USER)
ONTRACK_BASE_URL = os.environ.get("ONTRACK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "config.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {
        "ontrack": {"handlers": ["console"], "level": os.environ.get("ONTRACK_LOG_LEVEL", "INFO"), "propagate": False},
        "ontrack.requests": {"handlers": ["console"], "level": os.environ.get("ONTRACK_LOG_LEVEL", "INFO"), "propagate": False},
    },
}
