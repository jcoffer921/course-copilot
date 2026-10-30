import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from agent.models import SavedSite, UserSettings


def make(django_user_model, name):
    user = django_user_model.objects.create_user(username=name)
    UserSettings.objects.create(user=user, access_status=UserSettings.ACCESS_ACTIVE)
    return user


@pytest.mark.django_db
def test_owner_can_delete_saved_link_and_foreign_user_gets_404(django_user_model):
    owner, other = make(django_user_model, "own"), make(django_user_model, "oth")
    site = SavedSite.objects.create(user=owner, course_id="cs101", title="t", url="https://example.com/a")
    url = reverse("saved-site-detail", args=["cs101", site.pk])

    foreign = APIClient(); foreign.force_authenticate(other)
    assert foreign.delete(url).status_code == 404
    assert SavedSite.objects.filter(pk=site.pk).exists()

    mine = APIClient(); mine.force_authenticate(owner)
    assert mine.delete(url).status_code == 204
    assert not SavedSite.objects.filter(pk=site.pk).exists()
    assert mine.delete(url).status_code == 404


@pytest.mark.django_db
def test_javascript_url_rejected(django_user_model):
    client = APIClient(); client.force_authenticate(make(django_user_model, "js"))
    response = client.post(reverse("saved-sites", args=["cs101"]), {"url": "javascript:alert(1)"}, format="json")
    assert response.status_code == 400
