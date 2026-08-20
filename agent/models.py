"""
Django ORM models — account/auth data only, stored in the existing
db.sqlite3 alongside the built-in auth/session/admin tables. Never course
content: that stays flat-file JSON under courses/, per storage.py's
module docstring.
"""

from django.conf import settings
from django.db import models


class GoogleAccount(models.Model):
    """One row per signed-in user's Google identity and OAuth tokens.

    Looked up by google_sub (Google's stable subject id), not email — a
    later email change on the Google side updates this row rather than
    orphaning the account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()

    def __str__(self):
        return self.email
