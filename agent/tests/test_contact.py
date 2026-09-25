import pytest

from agent.models import ContactRequest


@pytest.mark.django_db
def test_contact_page_is_public(client):
    response = client.get("/contact/")
    assert response.status_code == 200
    assert b"How can we help?" in response.content
    assert b"Send a message" in response.content


@pytest.mark.django_db
def test_public_contact_submission_is_stored_and_notified(client, monkeypatch):
    notified = []
    monkeypatch.setattr("agent.page_views.support.notify_support", lambda request: notified.append(request.pk))
    response = client.post("/contact/", data={
        "name": "Taylor Student",
        "email": "taylor@example.com",
        "topic": "technical",
        "subject": "Upload is stuck",
        "message": "My notes upload has been processing for ten minutes.",
        "website": "",
    })
    assert response.status_code == 200
    assert b"Your message is on its way" in response.content
    saved = ContactRequest.objects.get()
    assert saved.user is None
    assert saved.email == "taylor@example.com"
    assert notified == [saved.pk]


@pytest.mark.django_db
def test_authenticated_contact_submission_attaches_account(client, django_user_model, monkeypatch):
    monkeypatch.setattr("agent.page_views.support.notify_support", lambda request: True)
    user = django_user_model.objects.create_user(username="pilot", password="secret", email="pilot@example.com")
    client.force_login(user)
    response = client.post("/contact/", data={
        "name": "Pilot User", "email": "pilot@example.com", "topic": "account",
        "subject": "Account question", "message": "Please help with my account.", "website": "",
    })
    assert response.status_code == 200
    assert ContactRequest.objects.get().user == user


@pytest.mark.django_db
def test_contact_form_rejects_invalid_submission(client):
    response = client.post("/contact/", data={"name": "", "email": "not-email", "topic": "bad"})
    assert response.status_code == 200
    assert not ContactRequest.objects.exists()
    assert b"Enter a valid email address" in response.content
