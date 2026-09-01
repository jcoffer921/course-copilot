import pytest
from django.urls import reverse

from agent.models import ServiceHeartbeat


pytestmark = pytest.mark.django_db


def test_health_is_public_safe_and_reports_heartbeats(client):
    ServiceHeartbeat.objects.create(name="backup", status="ok", detail="private path omitted")

    response = client.get(reverse("health"), HTTP_X_REQUEST_ID="pilot-check")

    assert response.status_code == 200
    assert response["X-Request-ID"] == "pilot-check"
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["database"] == {"status": "ok"}
    assert response.json()["heartbeats"]["backup"]["status"] == "ok"
    assert "private path omitted" not in response.content.decode()


def test_request_id_rejects_unsafe_value(client):
    response = client.get(reverse("health"), HTTP_X_REQUEST_ID="<script>")
    assert response.status_code == 200
    assert response["X-Request-ID"] != "<script>"
