"""
Google Sign-In: the email allow-list (this file) and, once Task 3 lands,
the OAuth 2.0 Authorization Code flow helpers. Kept separate from
agent/auth_views.py so the Google-specific plumbing isn't tangled up with
the Django view/session code.
"""

import os


def is_email_allowed(email: str) -> bool:
    """Case-insensitive membership check against ALLOWED_GOOGLE_EMAILS (a
    comma-separated env var, e.g. "you@gmail.com,friend@gmail.com"). An
    unset/empty allow-list allows nothing — fail closed, not open."""
    allowed = os.environ.get("ALLOWED_GOOGLE_EMAILS", "")
    allowed_set = {e.strip().lower() for e in allowed.split(",") if e.strip()}
    return email.strip().lower() in allowed_set
