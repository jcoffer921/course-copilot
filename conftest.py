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

truststore.inject_into_ssl()


@pytest.fixture(autouse=True)
def isolate_django_cache():
    """Prevent throttle and login counters from leaking between tests."""
    for cache in caches.all():
        cache.clear()
    yield
    for cache in caches.all():
        cache.clear()
