import pytest


@pytest.mark.django_db
def test_app_shell_includes_branded_dialogs(client, django_user_model):
    user = django_user_model.objects.create_user(username="pilot", password="secret")
    client.force_login(user)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b'id="ontrack-action-dialog"' in response.content
    assert response.content.count(b"agent/js/core/dialogs.js") == 1
    assert b"agent/js/feedback.js" not in response.content
    html = response.content.decode()
    assert html.index("</x-dc>") < html.index('id="ontrack-action-dialog"')
    assert 'id="pilot-feedback-dialog"' not in html


def test_feedback_page_uses_hydration_safe_delegated_events():
    feedback_source = open("agent/static/agent/js/feedback.js", encoding="utf-8").read()
    assert 'document.addEventListener("submit"' in feedback_source
    assert 'document.addEventListener("change"' in feedback_source
    assert 'feedback-submitted' in feedback_source
