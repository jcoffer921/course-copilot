import os

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import storage


def record_heartbeat(name, status="ok", detail=""):
    from agent.models import ServiceHeartbeat
    return ServiceHeartbeat.objects.update_or_create(
        name=name, defaults={"status": status, "detail": str(detail)[:255]},
    )[0]


def health_snapshot():
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = {"status": "ok"}
    except Exception:
        checks["database"] = {"status": "error"}
    storage_parent = storage.COURSES_DIR if storage.COURSES_DIR.exists() else storage.COURSES_DIR.parent
    checks["private_storage"] = {
        "status": "ok" if storage_parent.exists() and os.access(storage_parent, os.R_OK | os.W_OK) else "error",
    }
    email_backend = str(settings.EMAIL_BACKEND)
    checks["email"] = {
        "status": "configured" if "console" not in email_backend and settings.EMAIL_HOST else "development",
    }
    checks["ai"] = {"status": "configured" if os.environ.get("ANTHROPIC_API_KEY") else "missing"}
    from agent.models import ServiceHeartbeat
    heartbeats = {
        row.name: {
            "status": row.status,
            "checked_at": row.checked_at.isoformat(),
        }
        for row in ServiceHeartbeat.objects.all()
    }
    ready = checks["database"]["status"] == checks["private_storage"]["status"] == "ok"
    return {
        "status": "ok" if ready else "error",
        "checked_at": timezone.now().isoformat(),
        "checks": checks,
        "heartbeats": heartbeats,
    }, ready
