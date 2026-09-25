import pytest
import logging

from agent.models import PilotFeedback, ProductMetric


@pytest.mark.django_db
def test_feedback_is_anonymous_by_default(client, django_user_model):
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)

    response = client.post(
        "/api/feedback/",
        data={"category": "bug", "message": "The timer jumped.", "page": "/study/"},
        content_type="application/json",
    )

    assert response.status_code == 201
    saved = PilotFeedback.objects.get()
    assert saved.user is None
    assert saved.page == ""
    assert saved.message == "The timer jumped."
    assert not ProductMetric.objects.filter(user=user, event="feedback_submitted").exists()


@pytest.mark.django_db
def test_user_can_invite_follow_up_on_feedback(client, django_user_model):
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)
    response = client.post(
        "/api/feedback/",
        data={"category": "idea", "message": "Add focus music.", "anonymous": False, "page": "/study/"},
        content_type="application/json",
    )
    assert response.status_code == 201
    saved = PilotFeedback.objects.get()
    assert saved.user == user
    assert saved.page == "/study/"
    assert ProductMetric.objects.filter(user=user, event="feedback_submitted").exists()


@pytest.mark.django_db
def test_feedback_rejects_invalid_or_unauthenticated_requests(client, django_user_model):
    assert client.post("/api/feedback/", data={}, content_type="application/json").status_code in {401, 403}
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)
    response = client.post("/api/feedback/", data={"category": "nope", "message": ""}, content_type="application/json")
    assert response.status_code == 400
    assert not PilotFeedback.objects.exists()


@pytest.mark.django_db
def test_dashboard_links_to_dedicated_feedback_and_contact_pages(client, django_user_model):
    user = django_user_model.objects.create_user(username="pilot", password="secret", email="pilot@example.com")
    client.force_login(user)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b'href="/feedback/"' in response.content
    assert b'href="/contact/"' in response.content
    assert b'id="pilot-feedback-dialog"' not in response.content


@pytest.mark.django_db
def test_feedback_page_is_authenticated_and_defaults_to_anonymous(client, django_user_model):
    assert client.get("/feedback/").status_code == 302
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)
    response = client.get("/feedback/")
    assert response.status_code == 200
    assert b'id="feedback-page-form"' in response.content
    assert b'id="feedback-anonymous" type="checkbox" checked' in response.content


@pytest.mark.django_db
def test_anonymous_feedback_suppresses_user_id_in_request_log(client, django_user_model, caplog):
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)
    with caplog.at_level(logging.INFO, logger="ontrack.requests"):
        response = client.post(
            "/api/feedback/",
            data={"category": "other", "message": "Anonymous note", "anonymous": True},
            content_type="application/json",
        )
    assert response.status_code == 201
    records = [record for record in caplog.records if getattr(record, "path", None) == "/api/feedback/"]
    assert records
    assert records[-1].user_id is None
