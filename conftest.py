"""
Session-wide pytest setup. truststore.inject_into_ssl() makes Python's ssl
module use the OS certificate trust store instead of the certifi bundle —
needed on machines where TLS-inspecting endpoint security software presents
a corporate root CA that certifi doesn't know about (verified necessary on
this dev machine; harmless no-op everywhere else).
"""

import truststore

truststore.inject_into_ssl()
