"""Repeatable deployment and integration checks for a closed pilot."""

import asyncio
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import get_connection
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from . import backups, storage
from .client import MODEL_HAIKU, get_client


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _result(name, passed, ok_detail, fail_detail, warning=False):
    return Check(name, "ok" if passed else "warning" if warning else "error", ok_detail if passed else fail_detail)


async def _probe_ai():
    response = await get_client().messages.create(
        model=MODEL_HAIKU,
        max_tokens=8,
        messages=[{"role": "user", "content": "Reply with OK only."}],
    )
    return bool(response.content)


def run(*, live_smtp=False, live_ai=False):
    checks = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks.append(Check("database", "ok", "Database query succeeded."))
    except Exception as exc:
        checks.append(Check("database", "error", type(exc).__name__))

    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    checks.append(_result("migrations", not pending, "All migrations applied.", f"{len(pending)} migrations pending."))

    parent = storage.COURSES_DIR if storage.COURSES_DIR.exists() else storage.COURSES_DIR.parent
    writable = parent.exists() and os.access(parent, os.R_OK | os.W_OK)
    checks.append(_result("private_storage", writable, "Private storage is readable and writable.", "Private storage is unavailable."))

    ai_configured = bool(os.environ.get("ANTHROPIC_API_KEY"))
    checks.append(_result("anthropic_config", ai_configured, "Anthropic key is configured.", "ANTHROPIC_API_KEY is missing."))

    google_ready = bool(os.environ.get("GOOGLE_OAUTH_CLIENT_ID") and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    checks.append(_result("google_oauth_config", google_ready, "Google OAuth credentials are configured.", "Google OAuth credentials are missing."))

    backend = str(settings.EMAIL_BACKEND)
    smtp_ready = "smtp" in backend and bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER)
    checks.append(_result("smtp_config", smtp_ready, "SMTP delivery is configured.", "SMTP delivery is not configured."))

    parsed = urlparse(settings.ONTRACK_BASE_URL)
    public_url = parsed.scheme == "https" and bool(parsed.netloc) and parsed.hostname not in {"localhost", "127.0.0.1"}
    checks.append(_result(
        "public_url", public_url, "Public HTTPS URL is configured.",
        "ONTRACK_BASE_URL is local or not HTTPS.", warning=True,
    ))

    archives = sorted((settings.BASE_DIR / "backups").glob("ontrack-backup-*.zip"), reverse=True)
    try:
        backups.verify_backup(archives[0])
        checks.append(Check("latest_backup", "ok", f"Verified {archives[0].name}."))
    except (IndexError, backups.BackupError) as exc:
        checks.append(Check("latest_backup", "error", "No valid backup is available."))

    if live_smtp:
        try:
            mail_connection = get_connection()
            opened = mail_connection.open()
            mail_connection.close()
            checks.append(Check("smtp_connectivity", "ok" if opened is not False else "error", "SMTP authentication succeeded." if opened is not False else "SMTP connection failed."))
        except Exception as exc:
            checks.append(Check("smtp_connectivity", "error", type(exc).__name__))
    if live_ai:
        try:
            checks.append(Check("anthropic_connectivity", "ok" if asyncio.run(_probe_ai()) else "error", "Anthropic probe succeeded."))
        except Exception as exc:
            checks.append(Check("anthropic_connectivity", "error", type(exc).__name__))
    return [asdict(check) for check in checks]
