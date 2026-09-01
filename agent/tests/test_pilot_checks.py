import zipfile

import pytest

from agent.services import pilot_checks


pytestmark = pytest.mark.django_db


def test_pilot_checks_report_safe_named_results(monkeypatch, settings, tmp_path):
    settings.BASE_DIR = tmp_path
    settings.ONTRACK_BASE_URL = "http://127.0.0.1:8000"
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    results = {row["name"]: row for row in pilot_checks.run()}

    assert results["database"]["status"] == "ok"
    assert results["public_url"]["status"] == "warning"
    assert results["anthropic_config"]["status"] == "error"
    assert results["latest_backup"]["status"] == "error"
    assert not any("password" in row["detail"].lower() for row in results.values())
