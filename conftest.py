"""
Session-wide pytest setup. truststore.inject_into_ssl() makes Python's ssl
module use the OS certificate trust store instead of the certifi bundle —
needed on machines where TLS-inspecting endpoint security software presents
a corporate root CA that certifi doesn't know about (verified necessary on
this dev machine; harmless no-op everywhere else).
"""

import truststore
import pytest
from django.core.cache import caches
from django.test import Client as DjangoClient
from rest_framework.test import APIClient

truststore.inject_into_ssl()


@pytest.fixture(autouse=True)
def isolate_django_cache():
    """Prevent throttle and login counters from leaking between tests."""
    for cache in caches.all():
        cache.clear()
    yield
    for cache in caches.all():
        cache.clear()


def _ensure_active_settings(user):
    if not user or not getattr(user, "pk", None):
        return
    from agent.models import UserSettings
    UserSettings.objects.get_or_create(user=user, defaults={"access_status": UserSettings.ACCESS_ACTIVE})


@pytest.fixture(autouse=True)
def default_test_authenticated_users_to_active(monkeypatch):
    """Test infra only. UserSettings.access_status now gates every API view
    and app page (see agent/authentication.py's ActiveAccessPermission and
    agent/middleware.py's AccessStatusMiddleware); most of this suite
    predates that and authenticates test users via force_login/
    force_authenticate expecting ordinary (active) behavior. Rather than
    edit every one of those call sites, default any user authenticated this
    way to active — get_or_create only applies that default on first
    creation, so a test that creates the user's UserSettings row itself
    beforehand (with access_status='pending'/'suspended') is unaffected;
    that's how the access-gate tests in test_user_access.py opt out."""
    original_force_authenticate = APIClient.force_authenticate
    original_force_login = DjangoClient.force_login

    def patched_force_authenticate(self, user=None, token=None):
        _ensure_active_settings(user)
        return original_force_authenticate(self, user=user, token=token)

    def patched_force_login(self, user, backend=None):
        _ensure_active_settings(user)
        return original_force_login(self, user, backend=backend)

    monkeypatch.setattr(APIClient, "force_authenticate", patched_force_authenticate)
    monkeypatch.setattr(DjangoClient, "force_login", patched_force_login)
