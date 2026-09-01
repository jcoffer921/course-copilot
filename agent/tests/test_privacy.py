import pytest


@pytest.mark.django_db
def test_privacy_notice_is_public_and_explains_ai_and_metrics(client):
    response = client.get("/privacy/")
    assert response.status_code == 200
    assert b"How AI is used" in response.content
    assert b"Pilot measurement" in response.content
    assert b"do not copy note text" in response.content


@pytest.mark.django_db
def test_login_discloses_privacy_notice(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assert b"pilot privacy notice" in response.content
    assert b'href="/privacy/"' in response.content
